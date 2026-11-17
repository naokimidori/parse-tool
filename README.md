# 视频解析下载 (parse-tool)

粘贴视频分享链接，解析出无水印直链下载。前端负责输入链接，后端负责解析。

- 前端：单个静态页 `index.html`（输入框 + 解析按钮 + 结果列表），手机优先
- 后端：单个 Python 文件 `server.py`（标准库 HTTP 服务 + yt-dlp），无额外 Web 框架
- 解析：yt-dlp 提取标题、封面、各清晰度直链；下载直接从平台 CDN 取，不经过本站服务器

支持抖音、快手、小红书、B站、TikTok、Instagram、微博等 yt-dlp 覆盖的平台。

## 运行

```bash
python3 -m venv .venv
.venv/bin/pip install yt-dlp
.venv/bin/python server.py --port 8080
```

打开 http://127.0.0.1:8080 ，粘贴视频链接解析。

## 接口

- `GET /` 静态页
- `GET /health` 健康检查
- `POST /api/parse` `{"url": "https://..."}` → `{"title","uploader","duration","thumbnail","webpage_url","extractor","formats":[...]}`

每个 format：`{"format_id","ext","height","width","filesize","vcodec","acodec","note","url"}`。

## 部署

systemd 服务示例见 `parse-tool.service`。默认监听 `0.0.0.0:8080`。

## 说明

- 仅供个人学习使用；请遵守各平台服务条款与当地法律，勿用于盗版与侵权内容。
- 个别平台可能限制机房 IP 或需要登录，解析失败时会返回具体原因。
