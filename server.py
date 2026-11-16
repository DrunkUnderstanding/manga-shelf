"""漫画书架的本地后端（由 app.py 在随机端口启动，前端是 index.html）。
- 漫画库默认是程序旁边的 library 文件夹，可用 config.json 的 "library" 覆盖
- 可从 Kindle 电脑版导入没有 DRM 的个人文档（见 kindle.py）
- 支持手动旋转单页（存在 rotations.json）
调试用: python server.py [端口]   然后用浏览器打开 http://127.0.0.1:端口/
"""
import http.server, io, json, os, re, socketserver, sys, threading, time, urllib.parse, zipfile

import kindle

FROZEN = getattr(sys, 'frozen', False)
# RES：程序自带的文件（index.html、icon.ico）；DATA：可写的数据（进度、缓存、配置），打包后放在 exe 旁边
RES = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.dirname(sys.executable) if FROZEN else os.path.dirname(os.path.abspath(__file__))
CONF = {'library': os.path.join(DATA, 'library'), 'kindle_dir': None}
try:
    CONF.update(json.load(open(os.path.join(DATA, 'config.json'), encoding='utf-8')))
except Exception:
    pass
LIB = os.path.abspath(os.path.expandvars(os.path.expanduser(CONF['library'])))
META = os.path.join(DATA, '.cache')
PROG = os.path.join(DATA, 'progress.json')
ROTS = os.path.join(DATA, 'rotations.json')
LOG = os.path.join(DATA, 'server.log')
os.makedirs(META, exist_ok=True)
os.makedirs(LIB, exist_ok=True)
IMG = re.compile(r'\.(jpe?g|png|webp|gif|bmp)$', re.I)
lock = threading.Lock()
zips = {}


def natural(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', s)]


def books():
    try:
        names = os.listdir(LIB)
    except OSError:
        return []
    return sorted((f for f in names if f.lower().endswith(('.cbz', '.zip'))), key=natural)


def safe_path(bid):
    if bid not in books():
        raise FileNotFoundError(bid)
    return os.path.join(LIB, bid)


def open_zip(bid):
    p = safe_path(bid)
    m = os.path.getmtime(p)
    with lock:
        z = zips.get(bid)
        if not z or z[1] != m:
            if z:
                z[0].close()
            zips[bid] = (zipfile.ZipFile(p), m, threading.Lock())
        return zips[bid]


def pages(bid):
    z, _, _ = open_zip(bid)
    return sorted((n for n in z.namelist() if IMG.search(n) and not n.startswith('__MACOSX')), key=natural)


def read_entry(bid, name):
    z, _, zl = open_zip(bid)
    with zl:
        return z.read(name)


def load_json(path):
    try:
        return json.load(open(path, encoding='utf-8'))
    except Exception:
        return {}


def save_json(path, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


def cache_key(bid):
    return re.sub(r'[^\w.-]', '_', bid)


def rotations(bid):
    """{页码: 角度}，角度为顺时针 90/180/270。"""
    return {int(k): v for k, v in load_json(ROTS).get(bid, {}).items() if v % 360}


def book_meta(bid):
    """每页宽高（跨页判断要用），按文件修改时间缓存。这里是原图尺寸，不含手动旋转。"""
    from PIL import Image
    p = safe_path(bid)
    cache = os.path.join(META, cache_key(bid) + '.json')
    m = os.path.getmtime(p)
    c = load_json(cache)
    if c.get('mtime') == m:
        return c
    names = pages(bid)
    dims = []
    for n in names:
        try:
            dims.append(list(Image.open(io.BytesIO(read_entry(bid, n))).size))
        except Exception:
            dims.append([1, 1])
    c = {'mtime': m, 'names': names, 'dims': dims}
    save_json(cache, c)
    return c


def cover(bid):
    from PIL import Image
    p = os.path.join(META, cache_key(bid) + f'.{int(os.path.getmtime(safe_path(bid)))}.cover.jpg')
    if not os.path.exists(p):
        names = pages(bid)
        im = Image.open(io.BytesIO(read_entry(bid, names[0]))).convert('RGB')
        im.thumbnail((360, 540), Image.LANCZOS)
        im.save(p, quality=86)
    return open(p, 'rb').read()


def page_image(bid, n):
    """返回 (图片字节, Content-Type)。手动旋转过的页转好后缓存到 .cache。"""
    names = book_meta(bid)['names']
    name = names[n]
    deg = rotations(bid).get(n, 0)
    if not deg:
        low = name.lower()
        ct = 'image/png' if low.endswith('.png') else 'image/webp' if low.endswith('.webp') else 'image/jpeg'
        return read_entry(bid, name), ct
    p = os.path.join(META, f'{cache_key(bid)}.{int(os.path.getmtime(safe_path(bid)))}.p{n}.r{deg}.jpg')
    if not os.path.exists(p):
        from PIL import Image
        im = Image.open(io.BytesIO(read_entry(bid, name)))
        im = im.rotate(-deg, expand=True)          # PIL 是逆时针，这里存的是顺时针角度
        if im.mode not in ('L', 'RGB'):
            im = im.convert('RGB')
        im.save(p + '.tmp', 'JPEG', quality=95)
        os.replace(p + '.tmp', p)
    return open(p, 'rb').read(), 'image/jpeg'


# ---------------- Kindle 导入 ----------------
job = {'running': False, 'items': [], 'index': -1, 'page': 0, 'pages': 0, 'finished': 0}
job_lock = threading.Lock()


def kindle_dst(title):
    return kindle.safe_name(title) + '.cbz'


def kindle_list():
    have = {f.lower() for f in books()}
    out, dirs = [], []
    for b in kindle.list_books(CONF.get('kindle_dir')):
        f = kindle_dst(b['title'])
        out.append({'asin': b['asin'], 'title': b['title'], 'size': b['size'], 'mtime': b['mtime'],
                    'file': f, 'imported': f.lower() in have})
        d = os.path.realpath(os.path.dirname(os.path.dirname(b['path'])))   # 日志里常是 8.3 短路径，显示时换成长路径
        if d not in dirs:
            dirs.append(d)
    out.sort(key=lambda x: natural(x['title']))
    return out, dirs


def import_worker(items):
    for i, it in enumerate(items):
        with job_lock:
            job.update(index=i, page=0, pages=0)
            it['state'] = 'doing'

        def prog(n, total):
            job['page'], job['pages'] = n, total
        dst = os.path.join(LIB, kindle_dst(it['title']))
        try:
            if os.path.exists(dst):
                it.update(state='skip', msg='已存在')
            else:
                n, rot = kindle.extract(it['path'], dst, prog)
                it.update(state='done', msg=f'{n} 页' + (f'，转正 {rot} 张跨页' if rot else ''))
        except ValueError as e:
            it.update(state='skip', msg=str(e))
        except Exception as e:
            it.update(state='error', msg=f'{type(e).__name__}: {e}')
            try:
                os.remove(dst + '.part')
            except OSError:
                pass
    with job_lock:
        job.update(running=False, index=-1, finished=time.time())


def start_import(asins):
    with job_lock:
        if job['running']:
            raise RuntimeError('已有导入任务在进行')
        found = {b['asin']: b for b in kindle.list_books(CONF.get('kindle_dir'))}
        items = [{'asin': a, 'title': found[a]['title'], 'path': found[a]['path'], 'state': 'wait', 'msg': ''}
                 for a in asins if a in found]
        if not items:
            raise ValueError('没有选中可导入的书')
        job.update(running=True, items=items, index=0, page=0, pages=0, finished=0)
    threading.Thread(target=import_worker, args=(items,), daemon=True).start()


def job_status():
    with job_lock:
        return {'running': job['running'], 'index': job['index'], 'page': job['page'], 'pages': job['pages'],
                'finished': job['finished'],
                'items': [{k: it[k] for k in ('asin', 'title', 'state', 'msg')} for it in job['items']]}


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):
        try:
            with open(LOG, 'a', encoding='utf-8') as f:
                f.write(time.strftime('%H:%M:%S ') + (fmt % a) + '\n')
        except Exception:
            pass

    def send(self, code, body, ctype='application/json; charset=utf-8', cache=False):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
        elif isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'max-age=86400' if cache else 'no-store')
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def body(self):
        return json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        try:
            if u.path in ('/', '/index.html'):
                return self.send(200, open(os.path.join(RES, 'index.html'), 'rb').read(), 'text/html; charset=utf-8')
            if u.path == '/api/books':
                prog = load_json(PROG)
                out = []
                for b in books():
                    try:
                        n = len(pages(b))
                    except Exception:
                        continue
                    out.append({'id': b, 'title': re.sub(r'\.(cbz|zip)$', '', b, flags=re.I), 'total': n,
                                'progress': prog.get(b), 'added': os.path.getmtime(os.path.join(LIB, b))})
                return self.send(200, out)
            if u.path == '/api/book':
                c = book_meta(q['id'])
                rot = rotations(q['id'])
                dims = [d[::-1] if rot.get(i, 0) % 180 else d for i, d in enumerate(c['dims'])]
                return self.send(200, {'id': q['id'], 'dims': dims, 'rot': [rot.get(i, 0) for i in range(len(dims))],
                                       'progress': load_json(PROG).get(q['id'])})
            if u.path == '/cover':
                return self.send(200, cover(q['id']), 'image/jpeg', cache=True)
            if u.path == '/page':
                data, ct = page_image(q['id'], int(q['n']))
                return self.send(200, data, ct, cache=True)   # 前端 URL 里带了角度，旋转后不会命中旧缓存
            if u.path == '/api/kindle':
                bs, dirs = kindle_list()
                return self.send(200, {'library': LIB, 'dirs': dirs, 'books': bs, 'job': job_status()})
            if u.path == '/api/kindle/status':
                return self.send(200, job_status())
            self.send(404, {'error': 'not found'})
        except (FileNotFoundError, KeyError, IndexError, ValueError) as e:
            self.send(404, {'error': str(e)})
        except Exception as e:
            self.log_message('ERROR %s %r', self.path, e)
            self.send(500, {'error': str(e)})

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        try:
            if u.path == '/api/log':
                msg = self.rfile.read(int(self.headers.get('Content-Length', 0))).decode('utf-8', 'replace')
                self.log_message('CLIENT %s', msg[:2000])
                return self.send(200, {'ok': True})
            if u.path == '/api/progress':
                d = self.body()
                safe_path(d['id'])
                with lock:
                    prog = load_json(PROG)
                    prog[d['id']] = {'page': int(d['page']), 'total': int(d['total']), 'ts': time.time()}
                    save_json(PROG, prog)
                return self.send(200, {'ok': True})
            if u.path == '/api/rotate':
                # {"id": 书, "n": 页码, "by": 90 / -90}  或  {"id", "n", "deg": 0} 直接设定（0 = 还原）
                d = self.body()
                bid, n = d['id'], int(d['n'])
                if not 0 <= n < len(book_meta(bid)['names']):
                    raise IndexError(n)
                with lock:
                    allr = load_json(ROTS)
                    cur = allr.get(bid, {})
                    deg = (int(d['deg']) if 'deg' in d else int(cur.get(str(n), 0)) + int(d.get('by', 90))) % 360
                    if deg % 90:
                        raise ValueError('角度必须是 90 的倍数')
                    if deg:
                        cur[str(n)] = deg
                    else:
                        cur.pop(str(n), None)
                    if cur:
                        allr[bid] = cur
                    else:
                        allr.pop(bid, None)
                    save_json(ROTS, allr)
                return self.send(200, {'ok': True, 'n': n, 'deg': deg})
            if u.path == '/api/kindle/import':
                start_import(self.body().get('asins') or [])
                return self.send(200, job_status())
            self.send(404, {'error': 'not found'})
        except Exception as e:
            self.send(400, {'error': str(e)})


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = False


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 47615
    print(f'http://127.0.0.1:{port}/  library={LIB}')
    Server(('127.0.0.1', port), H).serve_forever()
