import urllib.request

from app.main import start_health_server


def test_health_returns_ok():
    server = start_health_server(0)
    try:
        port = server.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as resp:
            assert resp.status == 200 and resp.read() == b"ok"
    finally:
        server.shutdown()
