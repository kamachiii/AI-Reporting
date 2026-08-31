"""
Test normalisasi base_url (F2 — fix 403 "HTTP node only allows access to
inference API paths" pada gateway dengan route-matching ketat seperti B.AI).

Akar masalah: base_url dengan trailing slash ("https://api.b.ai/v1/") +
template f"{base}/models" menghasilkan double-slash ("/v1//models") yang
ditolak gateway ketat. Solusi: satukan normalisasi di helper _normalize_base()
dan pakai di SEMUA titik yang menghitung URL provider.
"""
import pytest

from app.routers.admin.ai_configs import _normalize_base, build_models_url
from app.services import ai_orchestrator


class TestNormalizeBase:
    @pytest.mark.parametrize("raw,expected", [
        ("https://api.b.ai/v1", "https://api.b.ai/v1"),
        ("https://api.b.ai/v1/", "https://api.b.ai/v1"),
        ("https://api.b.ai/v1//", "https://api.b.ai/v1"),
        ("  https://api.b.ai/v1/  ", "https://api.b.ai/v1"),
        ("https://api.b.ai", "https://api.b.ai"),
        ("", ""),
        ("   ", ""),
        (None, ""),
    ])
    def test_variations(self, raw, expected):
        assert _normalize_base(raw) == expected

    def test_does_not_strip_meaningful_path(self):
        # path non-root yang kebetulan berakhir slash tetap dirapikan satu slash,
        # tapi segmen path tidak boleh hilang
        assert _normalize_base("https://gw.example.com/openai/v1/") == "https://gw.example.com/openai/v1"


class TestBuildModelsUrl:
    def test_openai_default_when_empty(self):
        assert build_models_url("", api_type="openai") == "https://api.openai.com/v1/models"

    def test_trailing_slash_removed(self):
        assert build_models_url("https://api.b.ai/v1/", api_type="openai") == "https://api.b.ai/v1/models"

    def test_plain_base(self):
        assert build_models_url("https://api.b.ai/v1", api_type="openai") == "https://api.b.ai/v1/models"


class TestOrchestratorUrls:
    """ai_orchestrator menghitung URL chat — trailing slash tidak boleh merusak."""

    def test_openai_chat_url_no_double_slash(self):
        cfg = {"api_type": "openai", "base_url": "https://api.b.ai/v1/",
               "api_key": "k", "model": "m", "temperature": 0}
        # panggil dengan gateway mock mati — yang penting URL yang dicapai benar;
        # kita intip lewat helper publik yang dipakai orchestrator
        assert ai_orchestrator.build_chat_url(cfg) == "https://api.b.ai/v1/chat/completions"

    def test_openai_chat_url_fallback_default(self):
        cfg = {"api_type": "openai", "base_url": "", "api_key": "k", "model": "m"}
        assert ai_orchestrator.build_chat_url(cfg) == "https://api.openai.com/v1/chat/completions"

    def test_anthropic_messages_url_no_double_slash(self):
        cfg = {"api_type": "anthropic", "base_url": "https://gw.example.com/v1/",
               "api_key": "k", "model": "m"}
        assert ai_orchestrator.build_chat_url(cfg) == "https://gw.example.com/v1/messages"

    def test_anthropic_default(self):
        cfg = {"api_type": "anthropic", "base_url": "", "api_key": "k", "model": "m"}
        assert ai_orchestrator.build_chat_url(cfg) == "https://api.anthropic.com/v1/messages"
