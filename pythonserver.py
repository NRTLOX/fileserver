#!/usr/bin/env python3
import http.server
import socketserver
import os
import json
import urllib.parse
from pathlib import Path
import argparse

# фиксированный корень и папка загрузок
ROOT = Path("/home/rasulox/serv").resolve()
UPLOAD_DIR = ROOT / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

PORT=int(input("port? \n\n"))

#PORT = 8080


def list_dir(path: Path, base_url: str, root_for_size: Path, extras_to_skip=None):
    """
    Возвращает список файлов в каталоге path в формате:
    [{"name": ..., "url": ..., "size": ...}, ...]
    base_url — что подставлять в href.
    root_for_size — относительно чего считать путь к файлу в FS.
    """
    extras_to_skip = extras_to_skip or set()
    files = []
    for entry in sorted(path.iterdir()):
        if entry.is_file():
            if entry.name in extras_to_skip:
                continue
            rel = entry.relative_to(root_for_size)
            url = base_url + urllib.parse.quote(str(rel).replace("\\", "/"))
            size = entry.stat().st_size
            files.append({"name": entry.name, "url": url, "size": size})
    return files


def unique_name(target_dir: Path, name: str) -> str:
    stem = Path(name).stem
    suffix = Path(name).suffix
    candidate = name
    i = 1
    while (target_dir / candidate).exists():
        candidate = f"{stem}({i}){suffix}"
        i += 1
    return candidate


def parse_multipart(body: bytes, boundary: bytes):
    """
    Минималистичный парсер multipart/form-data.
    Возвращает список (field_name, filename, content_bytes).
    """
    boundary_full = b"--" + boundary
    parts = body.split(boundary_full)
    files = []

    for part in parts:
        part = part.strip()
        if not part or part == b"--":
            continue
        if b"\r\n\r\n" not in part:
            continue
        header_block, content = part.split(b"\r\n\r\n", 1)
        if content.endswith(b"\r\n"):
            content = content[:-2]
        if content.endswith(b"--"):
            content = content[:-2]

        headers = header_block.split(b"\r\n")
        disposition = None
        for h in headers:
            if h.lower().startswith(b"content-disposition:"):
                disposition = h.decode("utf-8", errors="ignore")
                break
        if not disposition:
            continue

        field_name = None
        filename = None
        for p in disposition.split(";"):
            p = p.strip()
            if p.startswith("name="):
                field_name = p.split("=", 1)[1].strip().strip('"')
            elif p.startswith("filename="):
                filename = p.split("=", 1)[1].strip().strip('"')

        if not field_name or not filename:
            continue

        files.append((field_name, filename, content))

    return files


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, root: Path, upload_dir: Path, extra_dir: Path | None, **kwargs):
        self.root = root
        self.upload_dir = upload_dir
        self.extra_dir = extra_dir
        super().__init__(*args, directory=str(root), **kwargs)

    def do_GET(self):
        # API: список файлов
        if self.path == "/list":
            root_files = list_dir(
                self.root,
                "/",
                self.root,
                extras_to_skip={"index.html", "style.css", "pythonserver.py"},
            )
            upload_files = list_dir(self.upload_dir, "/uploads/", self.root)

            extra_files = []
            extra_path_str = None
            if (self.extra_dir is not None and 
                self.extra_dir.exists() and 
                self.extra_dir.is_dir()):
                extra_files = list_dir(self.extra_dir, "/extra/", self.extra_dir)
                extra_path_str = str(self.extra_dir)
            data = {
                "root": root_files,        # /home/rasulox/serv
                "uploads": upload_files,   # /home/rasulox/serv/uploads
                "extra": extra_files,      # указанная папка (если есть)
                "extra_path": extra_path_str,
            }
            body = json.dumps(data).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # файлы из extra: /extra/...
        if self.path.startswith("/extra/") and self.extra_dir is not None:
            rel = self.path[len("/extra/"):]
            rel = urllib.parse.unquote(rel)
            target = (self.extra_dir / rel).resolve()
            # защита от выхода за пределы extra_dir
            if not str(target).startswith(str(self.extra_dir)) or not target.is_file():
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(target.stat().st_size))
            self.end_headers()
            with open(target, "rb") as f:
                self.wfile.write(f.read())
            return

        # статика из ROOT (index.html, style.css, uploads и т.д.)
        return http.server.SimpleHTTPRequestHandler.do_GET(self)

    def do_POST(self):
        if self.path != "/upload":
            self.send_error(404)
            return

        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self.send_error(400, "Expected multipart/form-data")
            return

        token = "boundary="
        if token not in content_type:
            self.send_error(400, "No boundary in Content-Type")
            return
        boundary = content_type.split(token, 1)[1].strip().encode("utf-8")

        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)

        try:
            parts = parse_multipart(body, boundary)
        except Exception:
            self.send_error(400, "Bad multipart data")
            return

        saved = []
        for field_name, filename, content in parts:
            if field_name != "files" or not filename:
                continue
            safe_name = os.path.basename(filename)
            final_name = unique_name(self.upload_dir, safe_name)
            with open(self.upload_dir / final_name, "wb") as f:
                f.write(content)
            saved.append(final_name)

        resp = {"message": f"Загружено файлов: {len(saved)}", "files": saved}
        body_resp = json.dumps(resp).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body_resp)))
        self.end_headers()
        self.wfile.write(body_resp)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "path",
        nargs="?",
        default=None,
        help="дополнительная папка, которую нужно показать (опционально)",
    )
    args = parser.parse_args()

    extra_dir = None
    if args.path is not None and args.path.strip() and args.path != "None":
        extra_dir = Path(args.path).expanduser().resolve()
    # всегда сервим /home/rasulox/serv
    os.chdir(ROOT)

    def handler_factory(*h_args, **h_kwargs):
        return Handler(
            *h_args,
            root=ROOT,
            upload_dir=UPLOAD_DIR,
            extra_dir=extra_dir,
            **h_kwargs
        )

    with socketserver.TCPServer(("", PORT), handler_factory) as httpd:
        print(f"Serving ROOT={ROOT} on http://127.0.0.1:{PORT}")
        if extra_dir:
            print(f"Extra dir: {extra_dir}")
        httpd.serve_forever()


if __name__ == "__main__":
    main()

