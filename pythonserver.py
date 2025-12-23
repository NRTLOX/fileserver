#!/usr/bin/env python3
import http.server
import socketserver
import os
import json
import urllib.parse
from pathlib import Path
import argparse

ROOT = Path.home() / "serv"
ROOT = ROOT.resolve()
UPLOAD_DIR = ROOT / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

PORT = int(input("port?\n") or "8080")


def listdir(path: Path, baseurl: str, root_for_size: Path, extra_to_skip=None):
    files = []
    extra_to_skip = extra_to_skip or set()
    for entry in sorted(path.iterdir()):
        if entry.is_file():
            if entry.name in extra_to_skip:
                continue
            rel = entry.relative_to(root_for_size)
            url = baseurl + urllib.parse.quote(str(rel).replace("\\", "/"))
            size = entry.stat().st_size
            files.append({"name": entry.name, "url": url, "size": size})
    return files


def unique_name(targetdir: Path, name: str) -> str:
    from pathlib import Path as _P
    stem = _P(name).stem
    suffix = _P(name).suffix
    candidate = name
    i = 1
    while (targetdir / candidate).exists():
        candidate = f"{stem}({i}){suffix}"
        i += 1
    return candidate


def parse_multipart_body(body: bytes, boundary: bytes):
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
            if h.lower().startswith(b"content-disposition"):
                disposition = h.decode("utf-8", errors="ignore")
                break
        if not disposition:
            continue
        fieldname = None
        filename = None
        for p in disposition.split(";"):
            p = p.strip()
            if p.startswith("name="):
                fieldname = p.split("=", 1)[1].strip().strip('"')
            elif p.startswith("filename="):
                filename = p.split("=", 1)[1].strip().strip('"')
        if not fieldname or not filename:
            continue
        files.append((fieldname, filename, content))
    return files


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, root: Path, uploaddir: Path, extradirectory: Path | None = None, **kwargs):
        self.root = root
        self.uploaddir = uploaddir
        self.extra_dir = extradirectory
        super().__init__(*args, directory=str(root), **kwargs)

    def do_GET(self):
        # API: /list
        if self.path == "/list":
            rootfiles = listdir(self.root, "/", self.root,
                                extra_to_skip={"index.html", "style.css", "pythonserver.py"})
            uploadfiles = listdir(self.uploaddir, "/uploads/", self.root)

            extrafiles = []
            extrapathstr = None
            if self.extra_dir is not None and self.extra_dir.exists() and self.extra_dir.is_dir():
                extrafiles = listdir(self.extra_dir, "/extra/", self.extra_dir)
                extrapathstr = str(self.extra_dir)

            data = {
                "root": rootfiles,
                "uploads": uploadfiles,
                "extra": extrafiles,
                "extrapath": extrapathstr,
            }
            body = json.dumps(data).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path.startswith("/extra/") and self.extra_dir is not None:
            rel = self.path[len("/extra/"):]
            rel = urllib.parse.unquote(rel)
            target = (self.extra_dir / rel).resolve()
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
            parts = parse_multipart_body(body, boundary)
        except Exception:
            self.send_error(400, "Bad multipart data")
            return

        saved = []
        for fieldname, filename, content in parts:
            if fieldname != "files" or not filename:
                continue
            safename = os.path.basename(filename)
            finalname = unique_name(self.uploaddir, safename)
            with open(self.uploaddir / finalname, "wb") as f:
                f.write(content)
            saved.append(finalname)

        resp = {"message": f"Загружено файлов: {len(saved)}", "files": saved}
        bodyresp = json.dumps(resp).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(bodyresp)))
        self.end_headers()
        self.wfile.write(bodyresp)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", default=None, help="extra directory")
    args = parser.parse_args()

    extradir = None
    if args.path is not None and args.path.strip() and args.path != "None":
        extradir = Path(args.path).expanduser().resolve()

    os.chdir(ROOT)

    def handler_factory(*h_args, **h_kwargs):
        return Handler(*h_args, root=ROOT, uploaddir=UPLOAD_DIR, extradirectory=extradir, **h_kwargs)

    with socketserver.TCPServer(("", PORT), handler_factory) as httpd:
        print(f"Serving ROOT={ROOT} on http://127.0.0.1:{PORT}")
        if extradir:
            print(f"Extra dir: {extradir}")
        httpd.serve_forever()


if __name__ == "__main__":
    main()

