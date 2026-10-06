"""Локальный HTTP-сервер вместо appleid.apple.com, RevenueCat и других внешних сервисов.

Записывает каждый запрос (метод, путь, заголовки, тело) и отвечает по таблице маршрутов.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs


class MockServer:
    def __init__(self):
        self.requests: list[dict] = []
        # (метод, префикс пути) -> (код, тело-словарь) или функция(request) -> (код, тело)
        self.routes: dict[tuple[str, str], object] = {}
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def _handle(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length).decode() if length else ""
                content_type = self.headers.get("Content-Type", "")
                if "application/x-www-form-urlencoded" in content_type:
                    body = {key: values[0] for key, values in parse_qs(raw).items()}
                elif raw:
                    try:
                        body = json.loads(raw)
                    except ValueError:
                        body = raw
                else:
                    body = None
                request = {"method": self.command, "path": self.path, "headers": dict(self.headers), "body": body}
                owner.requests.append(request)
                status, payload = 404, {"error": "no route"}
                for (method, prefix), answer in owner.routes.items():
                    if method == self.command and self.path.startswith(prefix):
                        status, payload = answer(request) if callable(answer) else answer
                        break
                data = b"" if payload is None else json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_DELETE = do_PUT = _handle

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def calls(self, method: str, prefix: str) -> list[dict]:
        return [item for item in self.requests if item["method"] == method and item["path"].startswith(prefix)]

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
