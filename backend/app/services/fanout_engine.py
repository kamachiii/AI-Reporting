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
            r"\b(?:penjualan|omzet|omset|pendapatan|revenue|transaksi)\b",
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
                "hint": "Gunakan tabel 'srvt_wo' (filter srvt_wo.batal = false). Total pendapatan jasa = COALESCE(SUM(totalestimasibiaya), 0), jumlah PKB/WO = COUNT(nomor). Jika membutuhkan detail pekerjaan jasa, dapat menghubungkan ke tabel 'srvt_wodetail' (filter batal = false).",
            },
            {
                "id": "part",
                "title": "Suku Cadang & Sparepart",
                "icon": "Package",
                "focus": "Penjualan suku cadang, pelumas, dan aksesoris melalui bengkel",
                "hint": "Gunakan tabel 'srvt_wodetail' (filter srvt_wodetail.part > 0; catatan penting: srvt_wodetail TIDAK memiliki kolom batal, kolom batal ada di srvt_wo). Total nilai penjualan part = COALESCE(SUM(part), 0), kuantiti = COUNT(*).",
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
                "focus": "Persediaan fisik unit mobil di dealer",
                "hint": "Gunakan tabel 'untt_datakendaraan' untuk menghitung total unit kendaraan. COUNT(norangka) AS total_stok_unit.",
            },
            {
                "id": "stok_part",
                "title": "Stok Sparepart Gudang",
                "icon": "Package",
                "focus": "Persediaan komponen dan suku cadang di gudang/bengkel",
                "hint": "Gunakan tabel 'srvt_stockparts' untuk persediaan sparepart. COUNT(DISTINCT kode_parts) AS total_item_part, SUM(stockawal + masuk - keluar) AS total_qty_part.",
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
                "hint": "Gunakan tabel 'untt_pembelian' (filter untt_pembelian.batal = false). Total nominal pembelian = SUM(hpunit), total unit = COUNT(nomor).",
            },
            {
                "id": "beli_part",
                "title": "Pembelian Sparepart",
                "icon": "Package",
                "focus": "Pengadaan suku cadang & bahan bengkel",
                "hint": "Gunakan tabel 'srvt_stockparts' (kolom masuk > 0) atau tabel pengadaan part terkait.",
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
        focus_text = d.get('focus', d.get('title', ''))
        hint_text = d.get('hint', '')
        domain_instructions.append(
            f"- Sub-Domain '{d_id}' ({d['title']}):\n"
            f"  Fokus: {focus_text}\n"
            f"  Petunjuk: {hint_text}"
        )
        
    domain_text = "\n".join(domain_instructions)
    json_sample = "{\n  " + ",\n  ".join(json_keys) + "\n}"

    if fanout_info.get("category") == "rincian_terpisah":
        intro = (
            f'The user requested detailed transaction breakdowns separated by period: "{question}"\n\n'
            "Generate an independent, valid PostgreSQL SELECT query for each requested period:\n"
        )
    else:
        intro = (
            f'The user asked a multi-domain dealership question: "{question}"\n\n'
            "To provide a comprehensive 360-degree overview, generate a separate, valid PostgreSQL SELECT query for each of the following sub-domains:\n"
        )

    prompt = f"""You are a PostgreSQL expert for an automotive dealership DMS (Dealer Management System).
{intro}{domain_text}

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


def _ekstrak_dua_periode(question: str) -> Optional[tuple[str, str]]:
    """Mengekstrak 2 tahun atau 2 periode waktu dari kueri."""
    q_lower = (question or "").lower()
    years = re.findall(r"\b(20[1-3][0-9])\b", q_lower)
    seen_years: List[str] = []
    for y in years:
        if y not in seen_years:
            seen_years.append(y)
    if len(seen_years) >= 2:
        return seen_years[0], seen_years[1]

    quarters = re.findall(r"\b(q[1-4]|kuartal\s*[1-4]|triwulan\s*[1-4]|semester\s*[1-2]|s[1-2])\b", q_lower)
    seen_q: List[str] = []
    for q in quarters:
        if q not in seen_q:
            seen_q.append(q)
    if len(seen_q) >= 2:
        return seen_q[0], seen_q[1]

    return None


def cek_apakah_minta_rincian_terpisah(question: str) -> Optional[Dict[str, Any]]:
    """
    Deteksi apakah user meminta rincian transaksi ditampilkan dalam tabel terpisah per periode (Gaya 2).
    Contoh: 'Tampilkan rincian transaksi penjualan tahun 2024 dan 2025 secara terpisah',
            'Pisahkan tabel pembelian 2025 dan 2026', 'Detail transaksi 2024 dan 2025 terpisah'.
    """
    q_lower = (question or "").lower()
    has_terpisah = bool(re.search(r"\b(?:terpisah|pisahkan|dipisah|pisah|pecah|masing-masing\s+tabel|tiap\s+tabel|per\s+tabel|sendiri-sendiri)\b", q_lower))
    has_rincian = bool(re.search(r"\b(?:rincian|detail|detil|breakdown)\b", q_lower))

    if not (has_terpisah or (has_rincian and bool(re.search(r"\b(?:dan|vs|versus|serta)\b", q_lower)))):
        return None

    periode = _ekstrak_dua_periode(question)
    if not periode:
        return None

    p1, p2 = periode

    topic = "penjualan"
    table_hint = "untt_penjualan"
    date_col = "tgl_penjualan"
    if any(w in q_lower for w in ["beli", "pembelian", "kulakan", "pengadaan"]):
        topic = "pembelian"
        table_hint = "untt_pembelian"
        date_col = "tgl_pembelian"
    elif any(w in q_lower for w in ["servis", "service", "bengkel", "pkb"]):
        topic = "servis"
        table_hint = "srvt_pkb"
        date_col = "tgl_pkb"
    elif any(w in q_lower for w in ["part", "sparepart", "suku cadang"]):
        topic = "sparepart"
        table_hint = "prtt_penjualan"
        date_col = "tgl_transaksi"
    elif any(w in q_lower for w in ["unit", "mobil", "motor", "kendaraan"]):
        topic = "unit kendaraan"
        table_hint = "untt_penjualan"
        date_col = "tgl_penjualan"

    return {
        "category": "rincian_terpisah",
        "p1": p1,
        "p2": p2,
        "topic": topic,
        "domains": [
            {
                "id": f"periode_{p1}",
                "title": f"Rincian Tahun {p1}",
                "icon": "Calendar",
                "focus": f"Daftar detail transaksi {topic} tahun {p1}",
                "hint": f"Tampilkan data baris transaksi dari '{table_hint}' pada tahun {p1} (filter {date_col} tahun {p1}). Batasi LIMIT 50.",
            },
            {
                "id": f"periode_{p2}",
                "title": f"Rincian Tahun {p2}",
                "icon": "Calendar",
                "focus": f"Daftar detail transaksi {topic} tahun {p2}",
                "hint": f"Tampilkan data baris transaksi dari '{table_hint}' pada tahun {p2} (filter {date_col} tahun {p2}). Batasi LIMIT 50.",
            },
        ]
    }


def _deteksi_kueri_komparasi_periode(question: str) -> Optional[Dict[str, Any]]:
    """
    Deteksi apakah pertanyaan adalah komparasi antar periode waktu (Gaya 1).
    Contoh: 'bandingkan penjualan tahun 2024 vs 2025', 'pembelian 2025 versus 2026'.
    """
    q_lower = (question or "").lower()
    # Jika sudah minta rincian terpisah, serahkan ke cek_apakah_minta_rincian_terpisah
    if bool(re.search(r"\b(?:terpisah|pisahkan|dipisah|pisah|pecah)\b", q_lower)):
        return None

    has_comp_kw = bool(re.search(r"\b(?:bandingkan|komparasi|perbandingan|versus|vs|growth|pertumbuhan|tren\s+antar|selisih|dibandingkan|dibanding|banding)\b", q_lower))
    periode = _ekstrak_dua_periode(question)
    if not periode:
        return None

    has_connector = bool(re.search(r"\b(?:vs|versus|dan|ke|dengan|serta|dibanding)\b", q_lower))
    if not (has_comp_kw or has_connector):
        return None

    p1, p2 = periode
    topic = "penjualan"
    if any(w in q_lower for w in ["beli", "pembelian", "kulakan", "pengadaan"]):
        topic = "pembelian"
    elif any(w in q_lower for w in ["servis", "service", "bengkel", "pkb"]):
        topic = "servis"
    elif any(w in q_lower for w in ["part", "sparepart", "suku cadang"]):
        topic = "sparepart"
    elif any(w in q_lower for w in ["unit", "mobil", "motor", "kendaraan"]):
        topic = "unit kendaraan"

    return {
        "is_comparison": True,
        "p1": p1,
        "p2": p2,
        "topic": topic,
    }


def cek_apakah_perlu_komparasi(question: str) -> bool:
    """Deteksi apakah pertanyaan menuntut komparasi/perbandingan antar divisi."""
    q_lower = (question or "").lower()
    patterns = [
        r"\b(?:bandingkan|komparasi|perbandingan|kontribusi|versus|vs)\b",
        r"\b(?:antar|lintas|tiap|per|semua)\s+divisi\b",
        r"\b(?:performa|peforma)\s+(?:antar|tiap|per|semua)?\s*divisi\b",
    ]
    return any(re.search(p, q_lower) for p in patterns)


def susun_tab_komparasi_divisi(domain_results: List[Dict[str, Any]], question: str) -> Optional[Dict[str, Any]]:
    """Menyusun tab tabel komparasi sejajar antar divisi (Sales, Service, Sparepart)."""
    valid_items = [d for d in domain_results if (d.get("row_count", 0) > 0 or d.get("rows")) and not d.get("error")]
    if not valid_items:
        return None

    # Hitung total volume dan total omzet per divisi
    summary_rows = []
    total_all_omzet = 0.0

    for item in valid_items:
        title = item.get("title", "Divisi")
        rows = item.get("rows", [])
        columns = [str(c).lower() for c in item.get("columns", [])]
        raw_records = item.get("raw_records", [])

        # Cari index kolom omzet dan volume
        omzet_idx = -1
        volume_idx = -1
        for idx, col in enumerate(columns):
            if any(u in col for u in ["omzet", "omset", "harga", "nilai", "rupiah", "biaya", "pendapatan", "total_uang", "total_penjualan", "jasa", "part"]):
                omzet_idx = idx
            elif any(c in col for c in ["total", "count", "jumlah", "qty", "unit", "item", "pkb"]):
                volume_idx = idx

        div_omzet = 0.0
        div_volume = 0

        # Jika raw_records ada, agregasi dari raw_records
        records_to_sum = raw_records if raw_records else rows
        for r in records_to_sum:
            if isinstance(r, dict):
                for k, v in r.items():
                    k_l = str(k).lower()
                    try:
                        num = float(v or 0)
                        if any(u in k_l for u in ["omzet", "omset", "harga", "nilai", "biaya", "pendapatan", "jasa", "part"]):
                            div_omzet += num
                        elif any(c in k_l for c in ["total", "count", "jumlah", "qty", "unit", "item", "pkb"]):
                            div_volume += int(num)
                    except (ValueError, TypeError):
                        pass
            elif isinstance(r, (list, tuple)):
                if omzet_idx != -1 and omzet_idx < len(r):
                    try:
                        div_omzet += float(r[omzet_idx] or 0)
                    except (ValueError, TypeError):
                        pass
                if volume_idx != -1 and volume_idx < len(r):
                    try:
                        div_volume += int(float(r[volume_idx] or 0))
                    except (ValueError, TypeError):
                        pass

        # Fallback jika volume belum terhitung tapi rows ada
        if div_volume == 0 and len(rows) > 0:
            div_volume = len(rows)

        total_all_omzet += div_omzet
        summary_rows.append({
            "divisi": title,
            "total_transaksi": div_volume,
            "total_omzet": div_omzet,
        })

    # Hitung persentase kontribusi omzet
    table_rows = []
    raw_recs = []
    for s in summary_rows:
        pct = (s["total_omzet"] / total_all_omzet * 100.0) if total_all_omzet > 0 else 0.0
        table_rows.append([
            s["divisi"],
            s["total_transaksi"],
            s["total_omzet"],
            f"{pct:.1f}%".replace(".", ",")
        ])
        raw_recs.append({
            "divisi": s["divisi"],
            "total_transaksi": s["total_transaksi"],
            "total_omzet": s["total_omzet"],
            "kontribusi_omzet": f"{pct:.1f}%".replace(".", ",")
        })

    combined_sql = "-- Ringkasan Komparasi Multi-Divisi\n" + "\n\n".join(
        f"-- Divisi {t['title']}:\n{t.get('sql', '')}" for t in valid_items if t.get("sql")
    )

    return {
        "id": "komparasi",
        "title": "Komparasi Antar Divisi",
        "icon": "BarChart3",
        "sql": combined_sql,
        "columns": ["divisi", "total_transaksi", "total_omzet", "kontribusi_omzet"],
        "rows": table_rows,
        "row_count": len(table_rows),
        "raw_records": raw_recs,
        "error": None
    }


def susun_ringkasan_eksekutif_multi(domain_results: List[Dict[str, Any]], question: str) -> str:
    """Menyusun narasi eksekutif terpadu dari hasil eksekusi multi-tab secara deterministik (0 token)."""
    parts = []
    
    # Hanya sertakan domain operasional divisi riil (kecualikan tab komparasi konsolidasi)
    valid_items = [d for d in domain_results if (d.get("row_count", 0) > 0 or d.get("rows")) and d.get("id") != "komparasi"]
    target_items = valid_items if valid_items else [d for d in domain_results if d.get("id") != "komparasi"]
    if not target_items:
        target_items = domain_results
    
    for item in target_items:
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
                    if num_v > 0 or not stat_items:
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
    is_rincian = any("Rincian" in str(d.get("title", "")) for d in valid_items)
    if is_rincian:
        base_narasi = f"Rincian transaksi per periode: {ringkasan_teks}."
    elif len(valid_items) > 1:
        base_narasi = f"Ringkasan performa mencakup seluruh data operasional: {ringkasan_teks}."
    elif len(valid_items) == 1:
        base_narasi = f"Hasil analitik {valid_items[0].get('title', 'data')}: {ringkasan_teks}."
    else:
        base_narasi = f"Ringkasan performa: {ringkasan_teks}."

    # Smart Context Note untuk Data Tahun Berjalan (2026 vs 2025/2024)
    q_lower = (question or "").lower()
    is_current_year_query = any(w in q_lower for w in ["tahun ini", "2026", "saat ini", "berjalan"])
    context_note = ""
    if is_current_year_query:
        total_records_count = sum(d.get("row_count", 0) for d in valid_items)
        if total_records_count <= 10:
            context_note = (
                "\n\nCatatan Analitik: Data transaksi tahun berjalan (2026) di sistem baru tercatat "
                "hingga pertengahan tahun (Juni 2026). Untuk analisis tahunan komprehensif, Anda juga "
                "dapat meninjau performa tahun penuh terakhir (2025 atau 2024)."
            )

    return base_narasi + context_note
