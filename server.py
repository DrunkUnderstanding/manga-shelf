"""漫画书架：本地 Kindle 风格漫画阅读器的后端。
- 读取 config.json 里 library 目录下的 .cbz / .zip
- 以 Edge 应用模式（无地址栏）打开前端；窗口关掉约 2 分钟后自动退出
用法: pythonw server.py
"""
import http.server, io, json, os, re, socketserver, subprocess, sys, threading, time, urllib.parse, urllib.request, webbrowser, zipfile

FROZEN = getattr(sys, 'frozen', False)
# RES：程序自带的文件（index.html）；DATA：可写的数据（进度、缓存、配置），打包后放在 exe 旁边
RES = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.dirname(sys.executable) if FROZEN else os.path.dirname(os.path.abspath(__file__))
HERE = RES
CONF = {'library': r'E:\KindleKCC\cbz', 'port': 47615}
try:
    CONF.update(json.load(open(os.path.join(DATA, 'config.json'), encoding='utf-8')))
except Exception:
    pass
LIB, PORT = CONF['library'], int(CONF['port'])
META = os.path.join(DATA, '.cache')
PROG = os.path.join(DATA, 'progress.json')
LOG = os.path.join(DATA, 'server.log')
os.makedirs(META, exist_ok=True)
IMG = re.compile(r'\.(jpe?g|png|webp|gif|bmp)$', re.I)
last_ping = START = time.time()
lock = threading.Lock()
zips = {}


def natural(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', s)]


def books():
    out = []
    for f in sorted(os.listdir(LIB), key=natural):
        if f.lower().endswith(('.cbz', '.zip')):
            out.append(f)
    return out


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
            zips[bid] = (zipfile.ZipFile(p), m, threading.Lock())
        return zips[bid]


def pages(bid):
    z, _, _ = open_zip(bid)
    return sorted((n for n in z.namelist() if IMG.search(n) and not n.startswith('__MACOSX')), key=natural)


def read_entry(bid, name):
    z, _, zl = open_zip(bid)
    with zl:
        return z.read(name)


def load_progress():
    try:
        return json.load(open(PROG, encoding='utf-8'))
    except Exception:
        return {}


def book_meta(bid):
    """每页宽高（跨页判断要用），按文件修改时间缓存。"""
    from PIL import Image
    p = safe_path(bid)
    key = re.sub(r'[^\w.-]', '_', bid) + '.json'
    cache = os.path.join(META, key)
    m = os.path.getmtime(p)
    try:
        c = json.load(open(cache, encoding='utf-8'))
        if c.get('mtime') == m:
            return c
    except Exception:
        pass
    names = pages(bid)
    dims = []
    for n in names:
        try:
            dims.append(list(Image.open(io.BytesIO(read_entry(bid, n))).size))
        except Exception:
            dims.append([1, 1])
    c = {'mtime': m, 'names': names, 'dims': dims}
    json.dump(c, open(cache, 'w', encoding='utf-8'))
    return c


def cover(bid):
    from PIL import Image
    key = re.sub(r'[^\w.-]', '_', bid)
    p = os.path.join(META, key + f'.{int(os.path.getmtime(safe_path(bid)))}.cover.jpg')
    if not os.path.exists(p):
        names = pages(bid)
        im = Image.open(io.BytesIO(read_entry(bid, names[0]))).convert('RGB')
        im.thumbnail((360, 540), Image.LANCZOS)
        im.save(p, quality=86)
    return open(p, 'rb').read()


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
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        global last_ping
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        try:
            if u.path in ('/', '/index.html'):
                return self.send(200, open(os.path.join(HERE, 'index.html'), 'rb').read(), 'text/html; charset=utf-8')
            if u.path == '/api/ping':
                last_ping = time.time()
                return self.send(200, {'ok': True, 'app': 'manga-shelf'})
            if u.path == '/api/books':
                prog = load_progress()
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
                return self.send(200, {'id': q['id'], 'dims': c['dims'], 'progress': load_progress().get(q['id'])})
            if u.path == '/cover':
                return self.send(200, cover(q['id']), 'image/jpeg', cache=True)
            if u.path == '/page':
                names = book_meta(q['id'])['names']
                n = names[int(q['n'])]
                ct = 'image/png' if n.lower().endswith('.png') else 'image/webp' if n.lower().endswith('.webp') else 'image/jpeg'
                return self.send(200, read_entry(q['id'], n), ct, cache=True)
            self.send(404, {'error': 'not found'})
        except (FileNotFoundError, KeyError, IndexError, ValueError) as e:
            self.send(404, {'error': str(e)})

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == '/api/log':
            msg = self.rfile.read(int(self.headers.get('Content-Length', 0))).decode('utf-8', 'replace')
            self.log_message('CLIENT %s', msg[:2000])
            return self.send(200, {'ok': True})
        if u.path != '/api/progress':
            return self.send(404, {'error': 'not found'})
        try:
            d = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
            safe_path(d['id'])
            with lock:
                prog = load_progress()
                prog[d['id']] = {'page': int(d['page']), 'total': int(d['total']), 'ts': time.time()}
                tmp = PROG + '.tmp'
                json.dump(prog, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False)
                os.replace(tmp, PROG)
            self.send(200, {'ok': True})
        except Exception as e:
            self.send(400, {'error': str(e)})


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = False


def open_window():
    url = f'http://127.0.0.1:{PORT}/'
    for edge in (r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
                 r'C:\Program Files\Microsoft\Edge\Application\msedge.exe'):
        if os.path.exists(edge):
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 1  # SW_SHOWNORMAL：pythonw 启动时子进程可能继承“隐藏/最小化”
            prof = os.path.join(HERE, '.edge-profile')  # 独立配置，不受日常 Edge 的扩展和窗口记忆影响
            subprocess.Popen([edge, f'--app={url}', f'--user-data-dir={prof}', '--window-size=1400,1000',
                              '--window-position=120,60', '--no-first-run', '--no-default-browser-check'], startupinfo=si)
            return
    webbrowser.open(url)


def already_running():
    try:
        r = urllib.request.urlopen(f'http://127.0.0.1:{PORT}/api/ping', timeout=1).read()
        return b'manga-shelf' in r
    except Exception:
        return False


def watchdog():
    while True:
        time.sleep(10)
        # 窗口关闭后约 2.5 分钟退出；刚启动时多给点时间
        if time.time() - last_ping > (300 if time.time() - START < 300 else 150):
            os._exit(0)


if __name__ == '__main__':
    if already_running():
        if '--no-window' not in sys.argv:
            open_window()
        sys.exit(0)
    srv = Server(('127.0.0.1', PORT), H)
    threading.Thread(target=watchdog, daemon=True).start()
    if '--no-window' not in sys.argv:
        threading.Timer(0.3, open_window).start()
    srv.serve_forever()
