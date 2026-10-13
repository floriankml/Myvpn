"""HTTP-Server im "Internet", der die Quell-IP des Aufrufers zurückgibt (wie ifconfig.me)."""

import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class H(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = self.client_address[0].encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class V6(ThreadingHTTPServer):
    address_family = socket.AF_INET6


servers = [ThreadingHTTPServer((sys.argv[1], 80), H)]
if sys.argv[2] != "-":
    servers.append(V6((sys.argv[2], 80), H))
for s in servers[1:]:
    threading.Thread(target=s.serve_forever, daemon=True).start()
servers[0].serve_forever()
