"""Records webhook calls for the end-to-end tests: POST anything, GET /calls returns them as JSON."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CALLS: list[dict[str, object]] = []


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get('Content-Length', '0'))
        CALLS.append(
            {
                'path': self.path,
                'authorization': self.headers.get('Authorization'),
                'user_agent': self.headers.get('User-Agent'),
                'json': json.loads(self.rfile.read(length) or b'null'),
            }
        )
        self._reply(200, {'success': True})

    def do_GET(self) -> None:
        if self.path == '/calls':
            self._reply(200, CALLS)
        else:
            self._reply(404, {'error': 'not found'})

    def do_DELETE(self) -> None:
        CALLS.clear()
        self._reply(200, {'success': True})

    def _reply(self, status: int, body: object) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0', 8080), Handler).serve_forever()  # noqa: S104 (inside the test container)
