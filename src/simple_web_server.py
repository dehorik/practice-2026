#!/usr/bin/env python3
"""A small educational HTTP server built with Python sockets.

Run:
    python3 src/simple_web_server.py --host 127.0.0.1 --port 8080 --root src/public
"""

from __future__ import annotations

import argparse
import html
import json
import mimetypes
import posixpath
import socket
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit


CRLF = "\r\n"
MAX_REQUEST_SIZE = 16 * 1024
SERVER_NAME = "PracticeSimpleServer/1.0"


@dataclass(frozen=True)
class HttpRequest:
    method: str
    target: str
    version: str
    headers: dict[str, str]
    body: bytes

    @property
    def path(self) -> str:
        return urlsplit(self.target).path or "/"

    @property
    def query(self) -> dict[str, list[str]]:
        return parse_qs(urlsplit(self.target).query)


@dataclass(frozen=True)
class HttpResponse:
    status: int
    reason: str
    headers: dict[str, str]
    body: bytes

    def to_bytes(self, include_body: bool = True) -> bytes:
        header_lines = [f"HTTP/1.1 {self.status} {self.reason}"]
        for key, value in self.headers.items():
            header_lines.append(f"{key}: {value}")
        response_head = (CRLF.join(header_lines) + CRLF * 2).encode("iso-8859-1")
        return response_head + (self.body if include_body else b"")


class BadRequest(Exception):
    """Raised when the incoming HTTP message cannot be parsed."""


class SimpleWebServer:
    """Minimal HTTP/1.1 server for GET and HEAD requests."""

    def __init__(self, host: str, port: int, root: Path) -> None:
        self.host = host
        self.port = port
        self.root = root.resolve()
        self._should_stop = threading.Event()

    def serve_forever(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.bind((self.host, self.port))
            server_socket.listen(20)
            server_socket.settimeout(0.5)
            print(f"Serving {self.root} on http://{self.host}:{self.port}")

            while not self._should_stop.is_set():
                try:
                    client_socket, client_address = server_socket.accept()
                except socket.timeout:
                    continue

                worker = threading.Thread(
                    target=self.handle_client,
                    args=(client_socket, client_address),
                    daemon=True,
                )
                worker.start()

    def stop(self) -> None:
        self._should_stop.set()

    def handle_client(self, client_socket: socket.socket, client_address: tuple[str, int]) -> None:
        with client_socket:
            try:
                raw_request = self._read_request(client_socket)
                request = parse_http_request(raw_request)
                response = self.route(request)
            except BadRequest as error:
                response = self.error_response(400, "Bad Request", str(error))
                request = None
            except Exception as error:
                response = self.error_response(500, "Internal Server Error", str(error))
                request = None

            include_body = not (request and request.method == "HEAD")
            client_socket.sendall(response.to_bytes(include_body=include_body))
            method = request.method if request else "-"
            target = request.target if request else "-"
            print(f"{client_address[0]}:{client_address[1]} {method} {target} -> {response.status}")

    def route(self, request: HttpRequest) -> HttpResponse:
        if request.method not in {"GET", "HEAD"}:
            return self.error_response(405, "Method Not Allowed", "Only GET and HEAD are supported.")

        if request.path == "/api/time":
            return self.handle_time_api()

        if request.path == "/api/echo":
            return self.handle_echo_api(request)

        return self.handle_static(request.path)

    def handle_static(self, raw_path: str) -> HttpResponse:
        file_path = self.resolve_static_path(raw_path)
        if file_path is None:
            return self.error_response(403, "Forbidden", "Path traversal is not allowed.")

        if file_path.is_dir():
            index_path = file_path / "index.html"
            if index_path.is_file():
                file_path = index_path
            else:
                return self.directory_listing(file_path, raw_path)

        if not file_path.exists() or not file_path.is_file():
            return self.error_response(404, "Not Found", f"Resource {html.escape(raw_path)} was not found.")

        content = file_path.read_bytes()
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        return build_response(200, "OK", content, content_type)

    def handle_time_api(self) -> HttpResponse:
        payload = {
            "server": SERVER_NAME,
            "time_utc": datetime.now(timezone.utc).isoformat(),
            "message": "This endpoint is a creative extension of the basic static web server.",
        }
        return json_response(payload)

    def handle_echo_api(self, request: HttpRequest) -> HttpResponse:
        payload = {
            "method": request.method,
            "path": request.path,
            "query": request.query,
            "headers": request.headers,
        }
        return json_response(payload)

    def directory_listing(self, directory: Path, raw_path: str) -> HttpResponse:
        rows = []
        for child in sorted(directory.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
            suffix = "/" if child.is_dir() else ""
            href = posixpath.join(raw_path.rstrip("/"), child.name) + suffix
            rows.append(
                f"<li><a href=\"{html.escape(href)}\">"
                f"{html.escape(child.name)}{suffix}</a></li>"
            )

        page = f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>Directory listing: {html.escape(raw_path)}</title>
  <link rel="stylesheet" href="/styles.css">
</head>
<body>
  <main>
    <h1>Directory listing</h1>
    <p><code>{html.escape(raw_path)}</code></p>
    <ul>
      {''.join(rows) or '<li>Directory is empty</li>'}
    </ul>
  </main>
</body>
</html>
"""
        return build_response(200, "OK", page.encode("utf-8"), "text/html; charset=utf-8")

    def error_response(self, status: int, reason: str, message: str) -> HttpResponse:
        body = f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>{status} {reason}</title>
  <link rel="stylesheet" href="/styles.css">
</head>
<body>
  <main>
    <h1>{status} {reason}</h1>
    <p>{html.escape(message)}</p>
  </main>
</body>
</html>
""".encode("utf-8")
        return build_response(status, reason, body, "text/html; charset=utf-8")

    def resolve_static_path(self, raw_path: str) -> Path | None:
        decoded = unquote(raw_path)
        path_parts = [part for part in decoded.split("/") if part not in {"", "."}]
        if any(part == ".." for part in path_parts):
            return None
        normalized = posixpath.normpath(decoded).lstrip("/")
        candidate = (self.root / normalized).resolve()
        if candidate == self.root or self.root in candidate.parents:
            return candidate
        return None

    def _read_request(self, client_socket: socket.socket) -> bytes:
        client_socket.settimeout(2)
        chunks = []
        total_size = 0

        while True:
            chunk = client_socket.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
            total_size += len(chunk)
            if total_size > MAX_REQUEST_SIZE:
                raise BadRequest("Request is too large.")
            data = b"".join(chunks)
            if b"\r\n\r\n" in data:
                return data

        data = b"".join(chunks)
        if not data:
            raise BadRequest("Empty request.")
        return data


def parse_http_request(raw_request: bytes) -> HttpRequest:
    try:
        head, _, body = raw_request.partition(b"\r\n\r\n")
        lines = head.decode("iso-8859-1").split(CRLF)
    except UnicodeDecodeError as error:
        raise BadRequest("Request headers must be ISO-8859-1 compatible.") from error

    if not lines or not lines[0]:
        raise BadRequest("Request line is missing.")

    request_line = lines[0].split()
    if len(request_line) != 3:
        raise BadRequest("Request line must contain method, target and HTTP version.")

    method, target, version = request_line
    if not version.startswith("HTTP/"):
        raise BadRequest("Unsupported request version format.")

    headers: dict[str, str] = {}
    for line in lines[1:]:
        if not line:
            continue
        if ":" not in line:
            raise BadRequest(f"Malformed header: {line}")
        name, value = line.split(":", 1)
        headers[name.strip().lower()] = value.strip()

    return HttpRequest(method=method.upper(), target=target, version=version, headers=headers, body=body)


def build_response(status: int, reason: str, body: bytes, content_type: str) -> HttpResponse:
    headers = {
        "Date": format_http_date(datetime.now(timezone.utc)),
        "Server": SERVER_NAME,
        "Content-Type": content_type,
        "Content-Length": str(len(body)),
        "Connection": "close",
    }
    return HttpResponse(status=status, reason=reason, headers=headers, body=body)


def json_response(payload: dict[str, object]) -> HttpResponse:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    return build_response(200, "OK", body, "application/json; charset=utf-8")


def format_http_date(value: datetime) -> str:
    return value.strftime("%a, %d %b %Y %H:%M:%S GMT")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Educational HTTP server built from Python sockets.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind.")
    parser.add_argument("--port", default=8080, type=int, help="TCP port to listen on.")
    parser.add_argument("--root", default=str(Path(__file__).with_name("public")), help="Static files root.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(args.root)
    if not root.exists():
        raise SystemExit(f"Static root does not exist: {root}")
    SimpleWebServer(args.host, args.port, root).serve_forever()


if __name__ == "__main__":
    main()
