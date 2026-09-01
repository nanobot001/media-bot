"""Serve one local media fixture with bounded HTTP byte-range support."""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class FixtureHandler(BaseHTTPRequestHandler):
    fixture_path: Path

    def log_message(self, format: str, *args: object) -> None:
        return

    def _requested_range(self, size: int) -> tuple[int, int] | None:
        value = self.headers.get("Range", "").strip()
        if not value:
            return None
        if not value.startswith("bytes=") or "," in value:
            raise ValueError("Unsupported range")
        start_text, end_text = value[6:].split("-", 1)
        if not start_text:
            length = int(end_text)
            if length <= 0:
                raise ValueError("Invalid suffix range")
            return max(0, size - length), size - 1
        start = int(start_text)
        end = int(end_text) if end_text else size - 1
        if start < 0 or start >= size or end < start:
            raise ValueError("Unsatisfiable range")
        return start, min(end, size - 1)

    def _prepare(self) -> tuple[int, int, int] | None:
        if self.path.split("?", 1)[0] != f"/{self.fixture_path.name}":
            self.send_error(404)
            return None
        size = self.fixture_path.stat().st_size
        try:
            requested = self._requested_range(size)
        except (TypeError, ValueError):
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers()
            return None
        start, end = requested if requested is not None else (0, size - 1)
        self.send_response(206 if requested is not None else 200)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Type", "video/x-matroska")
        self.send_header("Content-Length", str(end - start + 1))
        if requested is not None:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        return start, end, size

    def do_HEAD(self) -> None:
        self._prepare()

    def do_GET(self) -> None:
        prepared = self._prepare()
        if prepared is None:
            return
        start, end, _ = prepared
        remaining = end - start + 1
        with self.fixture_path.open("rb") as stream:
            stream.seek(start)
            while remaining > 0:
                chunk = stream.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=18765)
    args = parser.parse_args()
    fixture_path = args.fixture.resolve(strict=True)
    FixtureHandler.fixture_path = fixture_path
    server = ThreadingHTTPServer((args.host, args.port), FixtureHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
