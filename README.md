# MangaShelf 漫画书架

Windows 上的本地漫画阅读器，界面仿 Kindle 电脑版。读取本地的 `.cbz` / `.zip` 漫画，也可以直接从 Kindle 电脑版导入漫画。

> **只支持没有 DRM 的个人文档**：也就是你自己通过「发送到 Kindle（Send to Kindle）」传上去的文件（Kindle 内容目录里的 `*_PDOC.azw`，KFX 格式、未加密）。在 Kindle 商店购买的书带 DRM，本程序不能也不会处理。

## 功能

- **书架**：封面网格、搜索、按最近阅读或书名排序，首页显示「继续阅读」
- **阅读器**
  - 单页 / 双页；双页时封面单独显示，跨页自动单独占一屏
  - 横向跨页整张铺满
  - 从右往左（日漫）或从左往右翻页
  - 点屏幕两侧翻页，点中间显示菜单；键盘 ← → / 空格 / PageUp / PageDown / Home / End、滚轮翻页，F 全屏，Esc 返回
  - 黑色 / 深灰 / 纸白背景
  - 自动记住每本书读到哪一页，读完后可直接跳到下一卷
- **从 Kindle 导入**：书架右上角点「从 Kindle 导入」，勾选要导入的书，带进度条，导完自动出现在书架上
  - 自动找到 Kindle 电脑版的内容目录（读取 Kindle 的日志，书放在其他盘也能找到），书名也从日志里取
  - 每页只取原图，丢掉 KFX 里附带的预览小图
  - 有些漫画源会把横向跨页侧着放进竖页，导入时会自动检测并转正
- **旋转本页**：阅读时点 Aa 菜单里的「旋转本页」，可以左转、右转或还原。自动转正偶尔会把目录页之类误判成跨页，用这个手动修正；旋转记录保存在 `rotations.json`，不改动原文件
- 原生窗口（pywebview + WebView2），深色标题栏，不需要打开浏览器

## 运行

需要 Windows 10/11（自带 WebView2）和 Python 3.9+。

```bash
pip install pywebview pillow      # 或 pip install -r requirements.txt
python app.py
```

漫画库默认是程序目录下的 `library` 文件夹，第一次运行会自动创建。把 `.cbz` / `.zip` 放进去，或者用「从 Kindle 导入」。

想用别的目录，在程序目录下新建 `config.json`：

```json
{
  "library": "D:/Manga",
  "kindle_dir": "D:/Kindle/My Kindle Content"
}
```

`kindle_dir` 可以不写，只有自动找不到 Kindle 内容目录时才需要。

程序目录下会生成这些运行数据（都已加入 `.gitignore`）：

| 文件 | 内容 |
| --- | --- |
| `progress.json` | 阅读进度 |
| `rotations.json` | 手动旋转过的页 |
| `.cache/` | 封面缩略图、每页尺寸、旋转后的图片 |
| `.webview/` | 窗口的本地存储（阅读设置等） |
| `server.log` | 请求日志 |

## 打包成 exe

```bash
pip install pyinstaller
python -m PyInstaller app.py --name MangaShelf --noconsole --onedir ^
  --icon <绝对路径>\icon.ico ^
  --add-data "<绝对路径>\index.html;." ^
  --add-data "<绝对路径>\icon.ico;." ^
  --collect-all webview
```

`--add-data` 里必须写绝对路径。生成的程序在 `dist\MangaShelf\`，运行数据会写在 `MangaShelf.exe` 旁边。升级时只替换 `MangaShelf.exe` 和 `_internal`，保留 `config.json`、`progress.json`、`rotations.json` 和 `.cache`。

## 命令行导入

`kindle.py` 也可以单独使用：

```bash
python kindle.py              # 列出找到的书
python kindle.py <输出目录>    # 全部导入为 CBZ（已存在的跳过）
```

## 文件说明

| 文件 | 作用 |
| --- | --- |
| `app.py` | 入口：在随机端口启动本地服务，用 pywebview 打开原生窗口 |
| `server.py` | 本地 HTTP 服务：书架、页面图片、进度、旋转、Kindle 导入接口 |
| `kindle.py` | 查找 Kindle 内容目录、读取书名、把 KFX 转成 CBZ |
| `index.html` | 前端（书架和阅读器） |
| `icon.ico` | 图标 |
