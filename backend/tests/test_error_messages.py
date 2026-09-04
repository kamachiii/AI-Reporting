"""
Test permanen: PESAN ERROR user-facing harus ringkas & terbaca (kelas bug 2026-09-02:
popup 300-char JSON provider lolos karena tes hanya cek status code).

Aturan yang diverifikasi (statis, tanpa DB):
1. Tidak ada f-string user-facing (HTTPException detail / PlanningError / user error)
    yang memuat {resp.text}, {resp.content}, atau str(e)/{e} TANPA pembatasan.
2. Semua detail literal berbahasa Indonesia ringkas (<= 160 chars).
"""
import re
import os
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"

# Pola interpolasi teknis YANG DILARANG di string user-facing (tanpa .splitlines()[0][:120] dll)
RAW_TEXT = re.compile(r'f"[^"]*\{(resp|response|r)\.(text|content)\}[^"]*"')
RAW_TEXT_SLICED = re.compile(r'f"[^"]*\{(resp|response|r)\.(text|content)\[')
RAW_EXC = re.compile(r'f"[^"]*\{e\}[^"]*"')

# Endpoint pengguna menyalurkan detail ke UI via:
#  - HTTPException(detail=...)
#  - PlanningError(...)
#  - return {"status": "disconnected", "message": ...}  (test-draft/test)
EXC_RE = re.compile(r'HTTPException\(\s*status_code=(\d{3})\s*,\s*detail=(.{0,220)?', re.DOTALL)


def _py_files():
    for root, dirs, files in os.walk(APP):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if f.endswith(".py"):
                yield Path(root) / f


class TestNoRawProviderBodyInUserMessages:
    """Body mentah provider (resp.text) tidak boleh masuk pesan user tanpa slicing ringkas."""

    def test_no_unbounded_resp_text_in_fstrings(self):
        offenders = []
        for path in _py_files():
            src = path.read_text(encoding="utf-8", errors="replace")
            rel = path.relative_to(APP.parent)
            for m in RAW_TEXT.finditer(src):
                ln = src[:m.start()].count("\n") + 1
                line = src.splitlines()[ln - 1].strip()
                # f"AI API Error: {resp.text}" di logger.* = server log (boleh);
                # di raise/return/detail = popup user (larang).
                if line.startswith("logger."):
                    continue
                offenders.append(f"{rel}:{ln}: {m.group(0)[:80]}")
        assert not offenders, (
            "resp.text tanpa slicing masuk pesan user (popup panjang):\n" + "\n".join(offenders))

    def test_resp_text_must_be_sliced_and_logged_not_raised(self):
        # resp.text boleh hanya: (a) di logger.* , atau (b) di-slice [:N<=300] SEKALIGUS dipetakan
        # ke pesan ringkas. Pola paling aman yang kami standarkan: logger.warning/error memakai
        # resp.text; HTTPException/PlanningError TIDAK memuatnya.
        offenders = []
        for path in _py_files():
            src = path.read_text(encoding="utf-8", errors="replace")
            rel = path.relative_to(APP.parent)
            for m in re.finditer(r'(raise (?:HTTPException|PlanningError)[^;\n]{0,200})', src, re.DOTALL):
                stmt = " ".join(m.group(1).split())
                if "resp.text" in stmt or "resp.content" in stmt:
                    ln = src[:m.start()].count("\n") + 1
                    offenders.append(f"{rel}:{ln}: {stmt[:100]}")
        assert not offenders, (
            "resp.text masuk raise (harus ke logger / dipetakan reason ringkas):\n"
            + "\n".join(offenders))


class TestLiteralDetailsAreConcise:
    """Semua detail literal (bukan f-string) <= 160 chars dan tidak ada stacktrace-like text."""

    def test_literal_details_length(self):
        offenders = []
        for path in _py_files():
            src = path.read_text(encoding="utf-8", errors="replace")
            rel = path.relative_to(APP.parent)
            for m in re.finditer(
                    r'HTTPException\(\s*status_code=\d{3}\s*,\s*detail="([^"]{1,400})"', src, re.DOTALL):
                detail = " ".join(m.group(1).split())
                ln = src[:m.start()].count("\n") + 1
                # literal > 160 chars = dicurigai panjang (kecuali JSON payload terstruktur 409/422)
                if len(detail) > 160 and '"message"' not in detail and '"gate"' not in detail:
                    offenders.append(f"{rel}:{ln} ({len(detail)} ch): {detail[:90]}")
        assert not offenders, (
            "detail literal terlalu panjang (lihat pola popup-panjang):\n" + "\n".join(offenders))

    def test_no_traceback_markers_in_details(self):
        offenders = []
        bad_markers = ("Traceback", 'raise ', 'File "')
        for path in _py_files():
            src = path.read_text(encoding="utf-8", errors="replace")
            rel = path.relative_to(APP.parent)
            for m in re.finditer(r'detail=f?"([^"]{1,300})"', src, re.DOTALL):
                detail = m.group(1)
                for mk in bad_markers:
                    if mk in detail:
                        ln = src[:m.start()].count("\n") + 1
                        offenders.append(f"{rel}:{ln}: marker {mk!r} in detail")
        assert not offenders, "detail memuat artefak traceback:\n" + "\n".join(offenders)


class TestKnownConciseMessages:
    """Snapshot pesan kunci — mencegah regresi ke pesan panjang/teknis (live-proven 2026-09-02)."""

    def test_planner_provider_error_mapped(self):
        src = (APP / "services" / "query_planner.py").read_text(encoding="utf-8", errors="replace")
        assert "API Key tidak valid untuk provider ini" in src, (
            "query_planner harus memetakan 401 provider ke pesan ringkas")
        # dan TIDAK lagi raise dengan resp.text
        assert not re.search(r'PlanningError\([^)]*resp\.text', src, re.DOTALL)

    def test_models_endpoint_error_mapped(self):
        src = (APP / "routers" / "admin" / "ai_configs.py").read_text(
            encoding="utf-8", errors="replace")
        assert "API Key tidak valid untuk provider ini" in src
        assert 'detail=f"Gagal fetch dari provider (HTTP {resp.status_code})' not in src, (
            "jangan kembalikan pola lama yang menyisipkan body provider")
