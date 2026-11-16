"""从 Kindle 电脑版的本地内容目录导入漫画，转成 CBZ。

只处理通过 Send to Kindle 发送的个人文档（*_PDOC.azw，KFX 容器、未加密）：
- 每页只取大图（KFX 里每页还附带一张 512px 预览图）
- 有些漫画源会把横向跨页侧放进竖页，这里检测出来转回横向

既是阅读器的模块，也可以单独在命令行用：
    python kindle.py                 列出找到的书
    python kindle.py <输出目录>      把所有书导入到输出目录
"""
import glob, io, json, os, re, struct, sys, zipfile

PDOC = re.compile(r'([A-Z0-9]{20,40})_PDOC$')


def _kindle_pkg_dirs():
    base = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Packages')
    return glob.glob(os.path.join(base, 'AMZNKindle.*'))


def _log_lines():
    for pkg in _kindle_pkg_dirs():
        for f in sorted(glob.glob(os.path.join(pkg, 'LocalState', 'logs', '**', '*'), recursive=True),
                        key=lambda p: os.path.getmtime(p) if os.path.isfile(p) else 0):
            if os.path.isfile(f):
                try:
                    with open(f, encoding='utf-8', errors='ignore') as fh:
                        yield from fh
                except OSError:
                    pass


def find_content_dirs(extra=None):
    """Kindle 电脑版存书的目录。新版商店应用可以把书放到别的盘，所以优先看它自己的日志。"""
    found = []
    if extra:
        found.append(extra)
    pat = re.compile(r'([A-Za-z]:[/\\][^()\r\n]*?)[/\\][A-Z0-9]{20,40}_PDOC[/\\][A-Z0-9]{20,40}_PDOC\.azw')
    for line in _log_lines():
        m = pat.search(line)
        if m:
            found.append(m.group(1))
    home = os.path.expanduser('~')
    found += [os.path.join(home, 'Documents', 'My Kindle Content')]
    found += [os.path.join(p, 'LocalState', 'Classic', 'Content') for p in _kindle_pkg_dirs()]
    out, seen = [], set()
    for d in found:
        d = os.path.normpath(d)
        key = os.path.realpath(d).lower()   # 日志里常是 8.3 短路径，统一一下
        if key not in seen and os.path.isdir(d):
            seen.add(key); out.append(d)
    return out


def title_map():
    """ASIN -> 书名，来自 Kindle 电脑版日志里的 [loadMetadata]。"""
    titles, cur = {}, None
    for line in _log_lines():
        if '[loadMetadata] ASIN: ' in line:
            cur = line.split('ASIN: ', 1)[1].strip()
        elif '[loadMetadata] title: ' in line and cur:
            titles[cur] = line.split('title: ', 1)[1].strip()
            cur = None
    return titles


def safe_name(s):
    return re.sub(r'[\\/:*?"<>|\r\n]+', '_', s).strip(' .') or 'untitled'


def list_books(extra_dir=None):
    titles = title_map()
    books, seen = [], set()
    for d in find_content_dirs(extra_dir):
        for sub in sorted(os.listdir(d)):
            m = PDOC.match(sub)
            path = os.path.join(d, sub, sub + '.azw')
            if not m or m.group(1) in seen or not os.path.isfile(path):
                continue
            try:
                with open(path, 'rb') as f:
                    if f.read(4) != b'CONT':
                        continue
            except OSError:
                continue
            asin = m.group(1); seen.add(asin)
            books.append({'asin': asin, 'title': titles.get(asin) or asin, 'path': path,
                          'size': os.path.getsize(path), 'mtime': os.path.getmtime(path)})
    return books


def _images(b):
    starts, i = [], b.find(b'ENTY')
    while i != -1:
        ver, hlen = struct.unpack_from('<HI', b, i + 4)
        if ver == 1 and 10 <= hlen < 4096:
            starts.append((i, hlen))
        i = b.find(b'ENTY', i + 4)
    for k, (s, hlen) in enumerate(starts):
        end = starts[k + 1][0] if k + 1 < len(starts) else len(b)
        d = b[s + hlen:end]
        if d[:3] == b'\xff\xd8\xff' or d[:4] == b'\x89PNG':
            yield d


def extract(path, dst, progress=None):
    """把一本 KFX 漫画写成 dst（.cbz）。返回 (页数, 转正的跨页数)。没有图片的书（小说）抛 ValueError。"""
    from PIL import Image
    with open(path, 'rb') as f:
        b = f.read()
    raw = []
    for d in _images(b):
        try:
            w, h = Image.open(io.BytesIO(d)).size
        except Exception:
            continue
        if h < 800 and w < 800:
            continue            # 512px 预览图
        raw.append((d, w, h))
    if len(raw) < 8:
        raise ValueError('这本书里几乎没有图片，可能不是漫画')
    body = raw[1:-3] or raw
    capW = max(w for _, w, _ in body)
    medW = sorted(w for _, w, _ in body)[len(body) // 2]
    tmp = dst + '.part'
    rot = 0
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_STORED) as z:
        for n, (d, w, h) in enumerate(raw, 1):
            # 侧放的跨页：比普通页明显宽、宽度贴着全书最大值、高宽比 1.18~1.42；封面和书末几页不动
            if (1 < n <= len(raw) - 3 and w >= 0.98 * capW and w > 1.12 * medW and 1.18 <= h / w <= 1.42):
                im = Image.open(io.BytesIO(d)).transpose(Image.Transpose.ROTATE_270)
                buf = io.BytesIO()
                im.convert('RGB' if im.mode not in ('L', 'RGB') else im.mode).save(buf, 'JPEG', quality=95)
                d = buf.getvalue(); rot += 1
            z.writestr(f'{n:03d}.jpg', d)
            if progress:
                progress(n, len(raw))
    os.replace(tmp, dst)
    return len(raw), rot


if __name__ == '__main__':
    bs = list_books()
    if len(sys.argv) < 2:
        for x in bs:
            print(f"{x['size'] / 1048576:7.1f} MB  {x['title']}")
        sys.exit(0)
    out = sys.argv[1]; os.makedirs(out, exist_ok=True)
    for x in bs:
        dst = os.path.join(out, safe_name(x['title']) + '.cbz')
        if os.path.exists(dst):
            print('skip', x['title']); continue
        try:
            print('ok', x['title'], *extract(x['path'], dst))
        except ValueError as e:
            print('skip', x['title'], e)
