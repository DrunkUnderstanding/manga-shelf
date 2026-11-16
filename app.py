"""漫画书架：独立窗口版（不经过浏览器）。
窗口用 pywebview 原生窗口，标题栏改成 Kindle 电脑版那种深色；关窗口即退出。
用法: pythonw app.py
"""
import ctypes, os, sys, threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import server  # noqa: E402
import webview  # noqa: E402

ICON = os.path.join(server.RES, 'icon.ico')
TITLE = '漫画书架'


def make_icon():
    if os.path.exists(ICON):
        return
    from PIL import Image, ImageDraw
    im = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((8, 8, 248, 248), 48, fill=(20, 20, 20, 255))
    d.polygon([(52, 64), (118, 64), (126, 72), (126, 200), (112, 188), (52, 188)], fill=(240, 163, 58, 255))
    d.polygon([(204, 64), (138, 64), (130, 72), (130, 200), (144, 188), (204, 188)], fill=(240, 163, 58, 255))
    im.save(ICON, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def style_window(hwnd):
    """Kindle 风格：深色标题栏 + 自己的图标。"""
    dwm = ctypes.windll.dwmapi
    on = ctypes.c_int(1)
    dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), 4)             # 深色模式标题栏
    cap = ctypes.c_int(0x001B1B1B)                                        # 标题栏底色 #1b1b1b（BGR）
    dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(cap), 4)
    txt = ctypes.c_int(0x00E3E6E8)                                        # 标题文字
    dwm.DwmSetWindowAttribute(hwnd, 36, ctypes.byref(txt), 4)
    u = ctypes.windll.user32
    for size, which in ((16, 0), (32, 1)):                                # ICON_SMALL / ICON_BIG
        h = u.LoadImageW(None, ICON, 1, size, size, 0x10)                 # IMAGE_ICON, LR_LOADFROMFILE
        if h:
            u.SendMessageW(hwnd, 0x80, which, h)                          # WM_SETICON


def fit_to_screen(hwnd):
    """屏幕放不下默认尺寸（比如 1080p 再开 200% 缩放）时，缩小并居中，别让窗口底部钻到任务栏下面。"""
    from ctypes import wintypes as wt

    class MONITORINFO(ctypes.Structure):
        _fields_ = [('cbSize', wt.DWORD), ('rcMonitor', wt.RECT), ('rcWork', wt.RECT), ('dwFlags', wt.DWORD)]
    u = ctypes.windll.user32
    r = wt.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))
    mi = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
    u.GetMonitorInfoW(u.MonitorFromWindow(hwnd, 2), ctypes.byref(mi))   # MONITOR_DEFAULTTONEAREST
    wa = mi.rcWork
    if r.left >= wa.left and r.top >= wa.top and r.right <= wa.right and r.bottom <= wa.bottom:
        return
    ww, wh = wa.right - wa.left, wa.bottom - wa.top
    w, h = min(r.right - r.left, int(ww * 0.94)), min(r.bottom - r.top, int(wh * 0.94))
    u.SetWindowPos(hwnd, 0, wa.left + (ww - w) // 2, wa.top + (wh - h) // 2, w, h, 0x0014)  # SWP_NOZORDER | SWP_NOACTIVATE


def on_shown(win):
    hwnd = 0
    try:
        hwnd = int(win.native.Handle.ToInt64())
    except Exception:
        hwnd = ctypes.windll.user32.FindWindowW(None, TITLE)
    if hwnd:
        for f in (style_window, fit_to_screen):
            try:
                f(hwnd)
            except Exception:
                pass


if __name__ == '__main__':
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('MangaShelf.Reader')  # 任务栏用自己的图标
    except Exception:
        pass
    make_icon()
    srv = server.Server(('127.0.0.1', 0), server.H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    win = webview.create_window(TITLE, f'http://127.0.0.1:{port}/', width=1400, height=1000,
                                min_size=(800, 600), background_color='#141414', text_select=False)
    win.events.shown += lambda: on_shown(win)
    webview.start(private_mode=False, storage_path=os.path.join(server.DATA, '.webview'))
    os._exit(0)
