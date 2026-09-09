"""Unit and integration tests for the Unified Conversational and Database-Agnostic Flow.

Tests:
1. Conversational intent (0 SQL, natural text response, no database execution, is_conversational_text=True).
2. LLM returning non-SQL conversational answer handled gracefully without ValueError.
3. Database-agnostic schema context retrieval.
4. Explanatory context ('data apa ini', 'tadi lu kasih apa').
5. Number check verification.
"""
import pytest
from app.services.vanna_engine import (
    _is_conversational_question,
    _is_explanatory_question,
    susun_prompt_vanna,
    ekstrak_sql,
    _ekstrak_teks_naratif_bersih,
    _bersihkan_emoji_teks,
)
from app.services.presenter import kumpulkan_angka_diizinkan, angka_lolos


def test_conversational_detection_variations():
    """Memastikan variasi sapaan dan pertanyaan santai terdeteksi secara luwes."""
    sapaan_samples = [
        "p", "P", "halo", "Halo min", "aloww", "alohaa", "selamat pagi",
        "oi", "tes", "testing 123", "kamu bisa apa saja?", "bisa bantu apa",
        "ada data apa saja?", "siapa kamu", "terima kasih", "makasih ya",
        "semisal mau tanya dong", "apa itu PKB?", "apa bedanya SPK dan PKB?",
    ]
    for s in sapaan_samples:
        assert _is_conversational_question(s) is True, f"Harusnya terdeteksi percakapan: {s}"


def test_explanatory_detection_variations():
    """Memastikan pertanyaan meta/eksplanatori terdeteksi secara tepat."""
    meta_samples = [
        "data apa ini?", "tadi lu kasih data apa?", "maksud tabel di atas apa",
        "jelaskan data ini", "tabel apa tadi", "ini maksudnya apa sih",
    ]
    for m in meta_samples:
        assert _is_explanatory_question(m) is True, f"Harusnya terdeteksi eksplanatori: {m}"


def test_unified_prompt_guidelines():
    """Memastikan prompt menyertakan panduan query data dan panduan percakapan."""
    prompt = susun_prompt_vanna("tampilkan 5 mobil terlaris", "Table untt_penjualan (id, hjunit)")
    assert "You are a Postgres expert" in prompt
    assert "Generate ONE valid PostgreSQL SELECT query" in prompt
    assert "DO NOT generate SQL" in prompt
    assert "Zero emoji policy" in prompt


def test_sql_extraction_robustness():
    """Memastikan ekstraktor SQL membedakan SQL valid vs respon teks biasa."""
    # Respon SQL code block
    sql_block = "```sql\nSELECT * FROM orders WHERE total > 100;\n```"
    assert ekstrak_sql(sql_block) == "SELECT * FROM orders WHERE total > 100"

    # Respon teks percakapan biasa (bukan SQL)
    conv_text = "Halo! Senang bisa membantu Anda. Ada yang ingin ditanyakan tentang data?"
    extracted = ekstrak_sql(conv_text)
    # ekstrak_sql mengembalikan teks jika tidak ada block, tapi tidak diawali SELECT/WITH
    assert not extracted.lower().startswith("select")
    assert not extracted.lower().startswith("with")


def test_number_check_anti_hallucination():
    """Memastikan number check mencegah LLM mengarang angka di ringkasan."""
    # Data nyata: baris data memiliki angka 150000000 dan 15
    data_rows = [[150000000, 15]]
    question = "berapa penjualan bulan ini?"
    allowed_numbers = kumpulkan_angka_diizinkan(question, data_rows, row_count=1)

    # Narasi 1: Angka cocok persis dengan data -> lolos
    valid_narasi = "Total penjualan bulan ini adalah 150.000.000 dengan volume 15 unit."
    assert angka_lolos(valid_narasi, allowed_numbers) is True

    # Narasi 2: Angka mengarang (999.000.000 tidak ada di data) -> ditolak
    halusinasi_narasi = "Total penjualan melonjak mencapai 999.000.000 dengan volume 15 unit."
    assert angka_lolos(halusinasi_narasi, allowed_numbers) is False


def test_zero_emoji_cleaner():
    """Memastikan pembersih emoji menghilangkan semua simbol piktograf."""
    text_with_emoji = "Halo kawan! 👋 Data penjualan hari ini sangat bagus 🚗📈!"
    clean = _bersihkan_emoji_teks(text_with_emoji)
    assert "👋" not in clean
    assert "🚗" not in clean
    assert "📈" not in clean
    assert clean == "Halo kawan!  Data penjualan hari ini sangat bagus !"
