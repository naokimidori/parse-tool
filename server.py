#!/usr/bin/env python3
"""Parse tool: frontend takes a video link, backend extracts direct media URLs with yt-dlp.

Single file, stdlib HTTP server + yt-dlp library. No web framework.
- GET  /            -> index.html
- POST /api/parse   -> {"url": "..."} -> {"title","thumbnail","webpage_url","formats":[...]}
  Each format: {"format_id","ext","height","width","filesize","url","note"}
  Only video formats with a direct URL are returned, best first.
- GET  /health      -> {"ok": true}

Run: python3 server.py [--port 8080] [--host 0.0.0.0]
Requires: pip install yt-dlp
"""
import argparse
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp

HERE = Path(__file__).resolve().parent
INDEX = HERE / "index.html"
MAX_URL_LEN = 2048
PARSE_TIMEOUT = 60  # seconds, yt-dlp socket timeout

# Formats we keep: video with a direct URL. Audio-only is kept too (for audio download).
def _pick_formats(info):
    out = []
    seen = set()
    for f in info.get("formats") or []:
        url = f.get("url")
        if not url or not url.startswith(("http://", "https://")):
            continue
        key = (f.get("format_id"), f.get("height"), f.get("ext"))
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "format_id": f.get("format_id") or "",
            "ext": f.get("ext") or "",
            "height": f.get("height"),
            "width": f.get("width"),
            "filesize": f.get("filesize") or f.get("filesize_approx"),
            "vcodec": (f.get("vcodec") or "").split(".")[0] if f.get("vcodec") else "",
            "acodec": (f.get("acodec") or "").split(".")[0] if f.get("acodec") else "",
            "note": f.get("format_note") or "",
            "url": url,
        })
    # Best first: video with height, then audio-only, then the rest.
    def rank(f):
        h = f["height"] or 0
        if h:
            return (0, -h)
        return (1, 0)
    out.sort(key=rank)
    return out


def parse_url(url):
    """Extract info with yt-dlp without downloading. Raises on failure."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "socket_timeout": PARSE_TIMEOUT,
        "retries": 1,
        # Prefer the plain mp4 / best video so the returned URLs are directly playable.
        "format": "bestvideo+bestaudio/best",
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        raise RuntimeError("no info returned")
    # If it resolved to a playlist entry, take the first entry.
    if info.get("_type") == "playlist" and info.get("entries"):
        info = info["entries"][0]
    return {
        "title": info.get("title") or "",
        "uploader": info.get("uploader") or info.get("channel") or "",
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail") or "",
        "webpage_url": info.get("webpage_url") or url,
        "extractor": info.get("extractor") or "",
        "formats": _pick_formats(info),
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # keep the log quiet
        pass

    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, ctype):
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        p = urlparse(self.path)
        if p.path in ("/", "/index.html"):
            if INDEX.exists():
                return self._send_file(INDEX, "text/html; charset=utf-8")
            return self._send_json({"error": "index.html missing"}, 500)
        if p.path == "/health":
            return self._send_json({"ok": True})
        return self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        p = urlparse(self.path)
        if p.path != "/api/parse":
            return self._send_json({"error": "not found"}, 404)
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > 4096:
            return self._send_json({"error": "bad request"}, 400)
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return self._send_json({"error": "bad json"}, 400)
        url = (body.get("url") or "").strip()
        if not url or len(url) > MAX_URL_LEN:
            return self._send_json({"error": "missing url"}, 400)
        if not re.match(r"^https?://", url, re.IGNORECASE):
            return self._send_json({"error": "url must start with http:// or https://"}, 400)
        # Parse in a thread with a hard timeout so a slow site cannot hang the server.
        result = {}
        done = threading.Event()

        def work():
            try:
                result["data"] = parse_url(url)
            except Exception as e:  # noqa: BLE001 - surface yt-dlp errors to the client
                result["error"] = str(e)[:500]
            finally:
                done.set()

        t = threading.Thread(target=work, daemon=True)
        t.start()
        if not done.wait(timeout=PARSE_TIMEOUT + 15):
            return self._send_json({"error": "parse timed out, try again"}, 504)
        if "error" in result:
            return self._send_json({"error": result["error"]}, 502)
        return self._send_json(result["data"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"parse-tool on http://{args.host}:{args.port}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
