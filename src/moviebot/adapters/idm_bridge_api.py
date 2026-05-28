import json
import os
import subprocess
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from moviebot.config import settings

DEFAULT_IDM_EXE = r"C:\Program Files (x86)\Internet Download Manager\IDMan.exe"


class IdmBridgeHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Override to log cleanly to stdout
        sys.stdout.write(f"[IDM Bridge] {format % args}\n")

    def do_POST(self):
        if self.path != "/downloads":
            self.send_error(404, "Not Found")
            return

        # Authenticate token
        secret = settings.idm_bridge_secret
        header_secret = self.headers.get("X-Bridge-Secret")
        
        if not secret or header_secret != secret:
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Unauthorized"}).encode("utf-8"))
            return

        # Parse request body
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        
        try:
            data = json.loads(body.decode("utf-8"))
        except Exception:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Invalid JSON"}).encode("utf-8"))
            return

        download_url = data.get("url")
        output_dir = data.get("output_dir", r"F:\_temp\movies")
        filename = data.get("filename")
        dry_run = data.get("dry_run", False)

        if not download_url or not filename:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "url and filename parameters are required"}).encode("utf-8"))
            return

        # Validate OS is Windows
        if sys.platform != "win32":
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Bridge host must run on Windows"}).encode("utf-8"))
            return

        # Locate IDM
        if not Path(DEFAULT_IDM_EXE).exists():
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": f"IDMan.exe not found at {DEFAULT_IDM_EXE}"}).encode("utf-8"))
            return

        # Construct IDM execution args
        args = [
            DEFAULT_IDM_EXE,
            "/d", download_url,
            "/p", output_dir,
            "/f", filename,
            "/n",
            "/a"
        ]

        if dry_run:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "dry_run",
                "message": f"[Dry-Run] Would run command: {' '.join(args)}"
            }).encode("utf-8"))
            return

        try:
            subprocess.Popen(args)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "success",
                "message": f"Successfully queued download: {filename}"
            }).encode("utf-8"))
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": f"Subprocess launch failed: {str(e)}"}).encode("utf-8"))


def run_bridge(port: int = 8765):
    server_address = ("127.0.0.1", port)
    httpd = HTTPServer(server_address, IdmBridgeHandler)
    print(f"[IDM Bridge] Listening on http://127.0.0.1:{port}...")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[IDM Bridge] Shutting down...")
        httpd.server_close()


if __name__ == "__main__":
    run_bridge()
