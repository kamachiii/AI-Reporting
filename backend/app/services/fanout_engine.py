"""fanout_engine.py — Mesin Dekomposisi Kueri Multi-Domain & Multi-Tab (3S).

Komponen ini mendeteksi pertanyaan umum/makro dealer otomotif dan memecahnya
secara proaktif menjadi pilar operasional 3S (Sales, Service, Sparepart) tanpa
memaksa pengguna memilih tombol klarifikasi kaku.
"""

from typing import Optional, Dict, Any, List
import re
import json
import logging

logger = logging.getLogger(__name__)

# Aturan deteksi kueri makro dealer yang membutuhkan multi-tab 3S
FANOUT_RULES: List[Dict[str, Any]] = [
    {
        "category": "penjualan",
        "trigger_patterns": [
            r"\b(?:penjualan|omzet|omset|pendapatan|revenue|performa|transaksi)\b",
            r"\b(?:berapa|total|data|rekap|ringkasan)\s+(?:penjualan|omzet|omset|pendapatan)\b",
        ],
        # Jika salah satu qualifier ini ada, pertanyaan SUDAH SPESIFIK -> Jalankan single query normal!
        "qualifiers": [
            "unit", "mobil", "motor", "kendaraan", "chassis", "norangka", "tipe mobil", "model mobil",
            "part", "sparepart", "suku cadang", "aksesoris", "oli", "ban",
            "servis", "service", "bengkel", "jasa", "mekanik", "wo", "pkb"
        ],
        "mode": "3s",
        "domains": [
            {
                "id": "unit",
                "title": "Unit Kendaraan",
                "icon": "Car",
                "focus": "Penjualan unit kendaraan (mobil baru/bekas)",
                "hint": "Gunakan tabel 'untt_penjualan' (filter untt_penjualan.batal = false AND untt_penjualan.retur = false). Nilai omzet = SUM(hjakhir), jumlah unit = COUNT(*).",
            },
            {
                "id": "service",
                "title": "Jasa Servis Bengkel",
                "icon": "Wrench",
                "focus": "Pendapatan jasa servis & perawatan bengkel",
                "hint": "Gunakan tabel 'womt_wo' atau 'womt_wojasa' (filter womt_wo.batal = false). Total pendapatan jasa = SUM(total_biaya) atau SUM(total_harga), jumlah PKB = COUNT(*).",
            },
            {
                "id": "part",
                "title": "Suku Cadang & Sparepart",
                "icon": "Package",
                "focus": "Penjualan suku cadang, pelumas, dan aksesoris",
                "hint": "Gunakan tabel 'womt_wopart' atau 'invt_item' terkait transaksi sparepart (filter batal = false). Total nilai = SUM(total_harga), kuantiti = SUM(qty).",
            },
        ]
    },
    {
        "category": "stok",
        "trigger_patterns": [
            r"\b(?:stok|stock|persediaan|sisa|gudang|inventory)\b",
            r"\b(?:berapa|total|data|sisa)\s+(?:stok|persediaan)\b",
        ],
        "qualifiers": [
            "mobil", "motor", "kendaraan", "chassis", "norangka", "vin",
            "part", "sparepart", "suku cadang", "oli", "filter", "ban"
        ],
        "mode": "2s",
        "domains": [
            {
                "id": "stok_unit",
                "title": "Stok Unit Kendaraan",
                "icon": "Car",
                "focus": "Persediaan fisik unit mobil siap jual di dealer",
                "hint": "Gunakan tabel 'unit_stock' atau 'untt_stok' untuk menghitung jumlah unit mobil siap jual. COUNT(*) AS total_stok_unit.",
            },
            {
                "id": "stok_part",
                "title": "Stok Sparepart Gudang",
                "icon": "Package",
                "focus": "Persediaan komponen dan suku cadang di gudang",
                "hint": "Gunakan tabel 'invt_stok' atau 'part_stock' untuk menghitung saldo stok sparepart gudang. SUM(qty) AS total_stok_part.",
            },
        ]
    },
    {
        "category": "pembelian",
        "trigger_patterns": [
            r"\b(?:pembelian|pengadaan|kulakan|beli)\b",
            r"\b(?:berapa|total|data)\s+(?:pembelian|pengadaan)\b",
        ],
        "qualifiers": [
            "unit", "mobil", "motor", "kendaraan", "atpm", "distributor",
            "part", "sparepart", "suku cadang", "vendor"
        ],
        "mode": "2s",
        "domains": [
            {
                "id": "beli_unit",
                "title": "Pembelian Unit Kendaraan",
                "icon": "Car",
                "focus": "Pengadaan unit mobil dari distributor/ATPM",
                "hint": "Gunakan tabel pembelian unit kendaraan (filter batal = false).",
            },
            {
                "id": "beli_part",
                "title": "Pembelian Sparepart",
                "icon": "Package",
                "focus": "Pengadaan suku cadang & oli dari supplier",
                "hint": "Gunakan tabel 'invt_pembelian' (filter invt_pembelian.batal = false).",
            },
        ]
    },
]


def cek_apakah_perlu_fanout(question: str) -> Optional[Dict[str, Any]]:
    """Cek apakah pertanyaan bersifat umum sehingga perlu didekomposisi (Fan-Out).
    
    Returns:
        Dict konfigurasi Fan-Out jika cocok, atau None jika pertanyaan spesifik.
    """
    q_lower = (question or "").strip().lower()
    if not q_lower or len(q_lower) < 4:
        return None

    for rule in FANOUT_RULES:
        # 1. Apakah memicu pola kueri umum?
        is_triggered = any(re.search(p, q_lower) for p in rule["trigger_patterns"])
        if not is_triggered:
            continue

        # 2. Apakah user sudah menyertakan kata penjelas spesifik?
        has_qualifier = any(re.search(rf"\b{re.escape(q)}\b", q_lower) for q in rule["qualifiers"])
        if has_qualifier:
            # Sudah spesifik, jalankan query tunggal biasa
            continue

        # Cocok untuk Fan-Out Multi-Tab!
        return {
            "category": rule["category"],
            "mode": rule["mode"],
            "domains": rule["domains"]
        }

    return None


def susun_multi_sql_prompt(question: str, fanout_info: Dict[str, Any], context_text: str) -> str:
    """Menyusun 1 prompt tunggal ke LLM untuk menghasilkan SQL semua sub-domain dalam bentuk JSON."""
    domains = fanout_info["domains"]
    domain_instructions = []
    json_keys = []
    
    for d in domains:
        d_id = d["id"]
        json_keys.append(f'"{d_id}": "SELECT ..."')
        domain_instructions.append(
            f"- Sub-Domain '{d_id}' ({d['title']}):\n"
            f"  Fokus: {d['focus']}\n"
            f"  Petunjuk: {d['hint']}"
        )
        
    domain_text = "\n".join(domain_instructions)
    json_sample = "{\n  " + ",\n  ".join(json_keys) + "\n}"

    prompt = f"""You are a PostgreSQL expert for an automotive dealership DMS (Dealer Management System).
The user asked a multi-domain dealership question: "{question}"

To provide a comprehensive 360-degree overview, generate a separate, valid PostgreSQL SELECT query for each of the following sub-domains:
{domain_text}

Relevant Database Context & Rules:
{context_text}

CRITICAL REQUIREMENTS:
1. Respond ONLY with a valid JSON object where the keys correspond to the sub-domain IDs ({", ".join(d["id"] for d in domains)}).
2. Each value must be a valid, executable PostgreSQL SELECT query string.
3. Apply correct status filters (e.g. batal = false, retur = false where applicable).
4. Do NOT combine these queries using UNION or CROSS JOIN. Each query must be independent.
5. Wrap the JSON in a markdown codeblock ```json ... ```.

Format:
```json
{json_sample}
```
"""
    return prompt


def ekstrak_multi_sql(raw_llm_output: str, domain_ids: List[str]) -> Dict[str, str]:
    """Mengekstrak kueri SQL masing-masing domain dari respons JSON LLM."""
    if not raw_llm_output:
        return {}

    cleaned = raw_llm_output.strip()
    
    # Ekstrak dari json codeblock jika ada
    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
    if json_match:
        json_str = json_match.group(1).strip()
    else:
        # Coba cari kurung kurawal pertama dan terakhir
        brace_match = re.search(r"(\{[\s\S]*\})", cleaned)
        json_str = brace_match.group(1).strip() if brace_match else cleaned

    result: Dict[str, str] = {}
    try:
        parsed = json.loads(json_str)
        if isinstance(parsed, dict):
            for d_id in domain_ids:
                val = parsed.get(d_id)
                if isinstance(val, str) and val.strip():
                    sql = val.strip().rstrip(";")
                    result[d_id] = sql
                elif isinstance(val, dict) and "sql" in val:
                    sql = str(val["sql"]).strip().rstrip(";")
                    result[d_id] = sql
    except Exception as e:
        logger.warning("Gagal mem-parsing JSON multi-SQL (%s), mencoba ekstraksi regex...", e)
        # Fallback regex untuk masing-masing key
        for d_id in domain_ids:
            pat = rf'"{re.escape(d_id)}"\s*:\s*"((?:[^"\\]|\\.)*)"'
            m = re.search(pat, cleaned)
            if m:
                sql = m.group(1).encode().decode('unicode_escape').strip().rstrip(";")
                result[d_id] = sql

    return result


def _format_rupiah_singkat(val: float) -> str:
    """Format angka besar ke format Rupiah singkat (Miliar / Juta)."""
    abs_val = abs(val)
    if abs_val >= 1_000_000_000:
        return f"Rp {val / 1_000_000_000:.1f} M".replace(".", ",")
    elif abs_val >= 1_000_000:
        return f"Rp {val / 1_000_000:.1f} Jt".replace(".", ",")
    elif abs_val >= 1_000:
        return f"Rp {val:,.0f}".replace(",", ".")
    return f"Rp {val:,.0f}"


def susun_ringkasan_eksekutif_multi(domain_results: List[Dict[str, Any]], question: str) -> str:
    """Menyusun narasi eksekutif terpadu dari hasil eksekusi multi-tab secara deterministik (0 token)."""
    parts = []
    
    for item in domain_results:
        title = item.get("title", "Divisi")
        rows = item.get("raw_records", []) or item.get("rows", [])
        columns = item.get("columns", [])
        if not rows:
            parts.append(f"{title}: (Data tidak tercatat pada periode ini)")
            continue
            
        first_row = rows[0]
        stat_items = []
        if isinstance(first_row, dict):
            row_dict = first_row
        elif isinstance(first_row, (list, tuple)) and columns:
            row_dict = dict(zip(columns, first_row))
        else:
            row_dict = {}

        for k, v in row_dict.items():
            k_lower = str(k).lower()
            if v is None:
                continue
            try:
                num_v = float(v)
                if any(u in k_lower for u in ["omzet", "omset", "harga", "nilai", "rupiah", "biaya", "pendapatan", "total_uang", "total_penjualan"]):
                    stat_items.append(f"{_format_rupiah_singkat(num_v)}")
                elif any(c in k_lower for c in ["total", "count", "jumlah", "qty", "unit", "item", "pkb"]):
                    stat_items.append(f"{int(num_v):,} {k_lower.replace('total_', '').replace('_', ' ')}".replace(",", "."))
            except (ValueError, TypeError):
                pass
                
        if stat_items:
            parts.append(f"{title}: {', '.join(stat_items[:2])}")
        else:
            parts.append(f"{title}: {len(rows)} baris data")

    ringkasan_teks = " • ".join(parts)
    return f"Ringkasan performa dealer mencakup seluruh divisi operasional: {ringkasan_teks}."
