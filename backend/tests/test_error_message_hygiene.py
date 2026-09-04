"""Guard permanen: pesan error user-facing wajib RINGKAS & TERBACA.

Latar: 2026-09-02 dua keluhan user — (1) popup logout palsu (provider 401 diteruskan),
(2) popup 300+ chars berisi JSON provider. Audit 143 HTTPException menemukan pola sama
di query_planner. Test ini mencegah kelas bug itu terulang:

  A. Statis: tidak ada detail user-facing yang memuat resp.text / body JSON mentah
  B. Statis: semua HTTPException detail = string pendek ATAU dict terstruktur
  C. Live: endpoint error mengembalikan detail <= 120 chars (dilakukan di test live, bukan di sini)
"""
import re
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"

# Pola yang DILARANG muncul di detail user-facing:
FORBIDDEN = [
    r'resp\.text',      # body mentah provider (JSON blob)
    r'response\.text',
    r'\.text\[:\d+\]',  # variant slice
]

# detail dianggap "ekspresi panjang berisiko" jika interpolasi exception mentah {e} / {str(e)}
# TANPA pembatasan — kecuali di whitelist (keputusan desain: verifier reason diberikan apa adanya,
# TenantTidakAda/SkemaTidakTersedia pesannya memang singkat & dikontrol pipeline).
ALLOW_E_INTERPOLATION_FILES = {
    # chat.py memunculkan str(e) utk exception domain yang dikontrol (pesan singkat, diuji unit)
    "routers/chat.py",
    # tenants.py: str(e)[:200] sudah dibatasi
    "routers/admin/tenants.py",
}

def _py_files():
    return [p for p in APP.rglob("*.py") if "__pycache__" not in str(p)]


def _http_exception_details(src: str):
    """Yield (line_no, detail_expr) utk tiap HTTPException(..., detail=X).

    Parse balanced-parentheses agar f-string pendek di raise multi-baris tidak
    ikut menelan baris kode berikutnya (false positive).
    """
    for m in re.finditer(r'HTTPException\(', src):
        # cari kurung tutup yang seimbang
        depth = 1
        i = m.end()
        while i < len(src) and depth > 0:
            if src[i] == '(':
                depth += 1
            elif src[i] == ')':
                depth -= 1
            i += 1
        seg = src[m.start():i]
        line = src[:m.start()].count("\n") + 1
        dm = re.search(r'detail\s*=\s*(.+?)(?:,\s*\)|\)$)', seg, re.DOTALL)
        if dm:
            yield line, " ".join(dm.group(1).split())[:300]


class TestErrorMessageHygiene:
    """Kelas bug popup panjang / logout palsu tidak boleh terulang."""

    def test_no_raw_provider_body_in_details(self):
        """A. resp.text tidak boleh masuk detail user-facing (hanya boleh di logger)."""
        bad = []
        for p in _py_files():
            src = p.read_text(encoding="utf-8", errors="replace")
            rel = p.relative_to(APP).as_posix()
            for line_no, line in enumerate(src.splitlines(), 1):
                # hanya peduli baris yang ada hubungannya dgn detail/raise/pesan user
                if "detail" in line or "PlanningError" in line or "message" in line.lower():
                    for pat in FORBIDDEN:
                        if re.search(pat, line) and "logger" not in line:
                            bad.append(f"{rel}:{line_no}: {line.strip()[:100]}")
        assert not bad, f"Body provider mentah bocor ke detail user-facing:\n" + "\n".join(bad)

    def test_exception_details_are_short_or_structured(self):
        """B. detail string literal > 160 chars = mencurigakan (popup panjang)."""
        bad = []
        for p in _py_files():
            src = p.read_text(encoding="utf-8", errors="replace")
            rel = p.relative_to(APP).as_posix()
            for line_no, expr in _http_exception_details(src):
                m = re.match(r'^f?"(.+)"$', expr)
                if m:  # string literal statis — harus ringkas
                    if len(m.group(1)) > 160:
                        bad.append(f"{rel}:{line_no}: literal {len(m.group(1))} chars")
        assert not bad, "Detail literal terlalu panjang (popup user):\n" + "\n".join(bad)

    def test_planner_messages_are_mapped_not_raw(self):
        """C. query_planner memetakan status provider ke pesan ringkas (regresi 69c18ca)."""
        src = (APP / "services" / "query_planner.py").read_text(encoding="utf-8", errors="replace")
        assert "API Key tidak valid untuk provider ini" in src, "mapping pesan planner hilang"
        # dan tidak ada lagi pola lama
        assert 'merespons {resp.status_code}: {resp.text' not in src

    def test_ai_configs_models_endpoint_mapped(self):
        """D. endpoint models memetakan status provider (regresi 81f5acd)."""
        src = (APP / "routers" / "admin" / "ai_configs.py").read_text(encoding="utf-8", errors="replace")
        assert 'status_code=502' in src, "provider error harus 502, bukan diteruskan"
        assert "API Key tidak valid untuk provider ini" in src
