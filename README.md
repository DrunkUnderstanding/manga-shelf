# MangaShelf 漫画书架

本地 Kindle 风格的漫画阅读器（Windows），读取本地目录中的 `.cbz` / `.zip` 漫画，记录阅读进度。

## 功能

- 书架浏览、封面缩略图、阅读进度记忆
- 自动识别跨页
- 从 Kindle 电脑版导入通过 Send to Kindle 发送的个人文档（`*_PDOC.azw`，KFX、未加密）并转成 CBZ（`kindle.py`）

## 运行

```bash
pip install pywebview pillow
pythonw app.py          # 独立窗口版（pywebview）
pythonw server.py       # 浏览器版（Edge 应用模式打开）
```

在程序目录下创建 `config.json` 指定漫画目录：

```json
{"library": "D:\Manga"}
```

## Kindle 导入

```bash
python kindle.py            # 列出找到的书
python kindle.py <输出目录>  # 全部导入为 CBZ
```
