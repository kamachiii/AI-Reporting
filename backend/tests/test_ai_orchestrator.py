"""
Test ai_orchestrator: exception passthrough (H3).

Memastikan HTTPException yang di-raise sendiri TIDAK ditelan handler
generik — detail asli ("quota habis", "timeout") harus sampai ke client.
Gateway AI di-mock dengan HTTP server lokal.
"""
import asyncio
import json
import threading
import pytest
from http.server import BaseHTTPRequestHandler, HTTPServer

from fastapi import HTTPException
from app.services.ai_orchestrator import generate_json_filter


class _MockHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.send_response(500)
        self.end_headers()
        self.wfile.write(b'{"error":"mock down"}')

    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def mock_gateway():
    server = HTTPServer(("127.0.0.1", 18099), _MockHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield {"base_url": "http://127.0.0.1:18099/v1"}
    server.shutdown()


def _cfg(base_url):
    return {
        "api_type": "openai",
        "base_url": base_url,
        "api_key": "test-key",
        "model": "test-model",
        "temperature": 0,
    }


def test_gateway_500_keeps_original_detail(mock_gateway):
    """Gateway balas 500 -> client harus menerima pesan 'quota habis', bukan generik."""
    with pytest.raises(HTTPException) as exc:
        asyncio.run(generate_json_filter("test", {}, _cfg(mock_gateway["base_url"])))
    assert exc.value.status_code == 503
    assert "quota" in str(exc.value.detail).lower() or "tidak tersedia" in str(exc.value.detail).lower()


def test_gateway_unreachable_specific_message():
    """Gateway tidak bisa dihubungi -> pesan spesifik timeout/koneksi."""
    with pytest.raises(HTTPException) as exc:
        asyncio.run(generate_json_filter("test", {}, _cfg("http://127.0.0.1:18999/v1")))
    assert exc.value.status_code == 503
    assert "dihubungi" in str(exc.value.detail) or "timeout" in str(exc.value.detail).lower()


def test_unknown_api_type_rejected():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(generate_json_filter("test", {}, {**_cfg("http://x/v1"), "api_type": "beda"}))
    assert exc.value.status_code == 400
