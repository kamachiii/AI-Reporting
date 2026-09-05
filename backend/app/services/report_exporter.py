"""Layanan Pembuat Laporan Excel (.xlsx) Eksekutif Berformat + Native Chart.

Menghasilkan file spreadsheet profesional berbasis openpyxl yang dilengkapi:
1. Header metadata eksekutif (Judul, Pertanyaan, Cabang, Tanggal Cetak).
2. Tabel data dengan format akuntansi Indonesia (Rupiah Rp #,##0, pemisah ribuan).
3. Grafik Native Excel Asli (BarChart / LineChart) yang disematkan langsung di samping tabel,
   sesuai dengan pola spesifikasi '20260327 - Design Dashboard.xlsx'.
"""
import io
import re
from datetime import datetime
from typing import Any, Optional

import openpyxl
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


TIME_SERIES_PATTERNS = [
    r'\btahun\b', r'\byear\b', r'\bbulan\b', r'\bmonth\b',
    r'\bkuartal\b', r'\bquarter\b', r'\bq[1-4]\b', r'\bsemester\b',
    r'\btgl\b', r'\btanggal\b', r'\bdate\b', r'\bperiode\b'
]

CURRENCY_PATTERNS = [
    r'omzet', r'penjualan', r'harga', r'revenue', r'profit', r'nominal',
    r'pembelian', r'diskon', r'discount', r'nilai', r'bayar', r'total_uang',
    r'ar_', r'ap_', r'piutang', r'hutang', r'biaya', r'tarif', r'uang'
]


def _is_currency_column(col_name: str) -> bool:
    """Deteksi apakah kolom merepresentasikan nominal mata uang."""
    c_lower = col_name.lower()
    return any(re.search(pat, c_lower) for pat in CURRENCY_PATTERNS)


def _is_time_series_column(col_name: str) -> bool:
    """Deteksi apakah kolom merupakan dimensi deret waktu."""
    c_lower = col_name.lower()
    return any(re.search(pat, c_lower) for pat in TIME_SERIES_PATTERNS)


def _parse_numeric(val: Any) -> tuple[bool, Optional[float]]:
    """Konversi nilai mentah atau string berformat ke float."""
    if val is None:
        return False, None
    if isinstance(val, (int, float)):
        return True, float(val)
    if isinstance(val, str):
        # Bersihkan format Rp dan titik/koma ribuan
        clean = val.replace('Rp', '').replace('rp', '').replace(' ', '')
        # Jika format Indonesia: 14.563.500 atau 14.563.500,00
        if re.match(r'^-?\d{1,3}(\.\d{3})+(,\d+)?$', clean):
            clean = clean.replace('.', '').replace(',', '.')
        elif re.match(r'^-?\d+(\.\d+)?$', clean):
            pass
        else:
            return False, None
        try:
            return True, float(clean)
        except ValueError:
            return False, None
    return False, None


def generate_excel_report(
    question: str,
    branch_code: str,
    tab_name: Optional[str],
    rows: list[dict[str, Any]],
    columns: list[str]
) -> bytes:
    """Buat file spreadsheet Excel .xlsx dengan tabel berformat dan grafik native.

    Args:
        question: Pertanyaan teks kueri pengguna
        branch_code: Kode cabang dealer
        tab_name: Nama tab/divisi (misal: 'Unit Kendaraan', 'Jasa Servis')
        rows: Daftar dictionary baris hasil kueri
        columns: Daftar nama kolom
    Returns:
        Bytes data berkas .xlsx
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Laporan Eksekutif"
    ws.views.sheetView[0].showGridLines = True

    # 1. Header Metadata Eksekutif
    ws['A1'] = "DMS AI PLATFORM — LAPORAN EKSEKUTIF"
    ws['A1'].font = Font(name="Segoe UI", size=14, bold=True, color="1E3A8A")

    ws['A2'] = f"Kueri: {question}"
    ws['A2'].font = Font(name="Segoe UI", size=10, italic=True, color="475569")

    divisi_text = f" · Divisi: {tab_name}" if tab_name else ""
    tgl_cetak = datetime.now().strftime("%d %B %Y, %H:%M WIB")
    ws['A3'] = f"Cabang: {branch_code}{divisi_text} · Dicetak: {tgl_cetak}"
    ws['A3'].font = Font(name="Segoe UI", size=9, color="64748B")

    # Batasi bila kolom kosong
    if not columns and rows:
        if isinstance(rows[0], dict):
            columns = list(rows[0].keys())
        elif isinstance(rows[0], (list, tuple)):
            columns = [f"Kolom_{i+1}" for i in range(len(rows[0]))]

    # Normalisasi rows: jika list of list/tuple, konversi ke list of dict
    normalized_rows = []
    for r in rows:
        if isinstance(r, dict):
            normalized_rows.append(r)
        elif isinstance(r, (list, tuple)):
            normalized_rows.append({col: (r[i] if i < len(r) else None) for i, col in enumerate(columns)})
        else:
            normalized_rows.append({})
    rows = normalized_rows

    start_row = 5
    if not columns:
        ws.cell(row=start_row, column=1, value="(Tidak ada data)")
        bio = io.BytesIO()
        wb.save(bio)
        return bio.getvalue()

    # 2. Styling Palet
    header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    header_font = Font(name="Segoe UI", size=10, bold=True, color="FFFFFF")
    zebra_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
    white_fill = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")

    thin_border = Border(
        left=Side(style='thin', color='CBD5E1'),
        right=Side(style='thin', color='CBD5E1'),
        top=Side(style='thin', color='CBD5E1'),
        bottom=Side(style='thin', color='CBD5E1')
    )

    currency_fmt = '_("Rp "* #,##0_);_("Rp "* (#,##0);_("Rp "* "-"_);_(@_)'
    integer_fmt = '#,##0'

    # 3. Tulis Header Tabel
    for col_idx, col_name in enumerate(columns, 1):
        cell = ws.cell(row=start_row, column=col_idx, value=col_name.replace('_', ' ').title())
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = thin_border
    ws.row_dimensions[start_row].height = 24

    # 4. Tulis Baris Data
    numeric_cols: dict[int, bool] = {}  # col_idx -> is_currency
    category_col_idx: Optional[int] = None

    # Tentukan kolom kategori (kolom non-numerik pertama atau time series)
    for c_idx, c_name in enumerate(columns, 1):
        is_curr = _is_currency_column(c_name)
        # Cek apakah dominan numerik
        num_count = sum(1 for r in rows if _parse_numeric(r.get(c_name))[0])
        if num_count >= max(1, len(rows) * 0.7):
            numeric_cols[c_idx] = is_curr
        elif category_col_idx is None:
            category_col_idx = c_idx

    if category_col_idx is None:
        category_col_idx = 1

    for r_offset, row_data in enumerate(rows):
        current_r = start_row + 1 + r_offset
        ws.row_dimensions[current_r].height = 20
        row_fill = zebra_fill if r_offset % 2 == 1 else white_fill

        for c_idx, col_name in enumerate(columns, 1):
            raw_val = row_data.get(col_name)
            cell = ws.cell(row=current_r, column=c_idx)
            cell.font = Font(name="Segoe UI", size=9.5)
            cell.border = thin_border
            cell.fill = row_fill

            is_num, num_val = _parse_numeric(raw_val)
            if is_num and c_idx in numeric_cols:
                cell.value = num_val
                cell.alignment = Alignment(horizontal="right", vertical="center")
                if numeric_cols[c_idx]:
                    cell.number_format = currency_fmt
                else:
                    cell.number_format = integer_fmt
            else:
                cell.value = str(raw_val) if raw_val is not None else "-"
                cell.alignment = Alignment(
                    horizontal="center" if c_idx == category_col_idx and len(str(raw_val)) <= 6 else "left",
                    vertical="center"
                )

    # Auto-adjust lebar kolom
    for col in ws.iter_cols(min_row=start_row, max_row=start_row + len(rows), min_col=1, max_col=len(columns)):
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = max(max_len + 4, 13)

    # 5. Native Excel Chart Generation (Bila data memenuhi syarat)
    if rows and numeric_cols and len(rows) <= 100:
        val_col_indices = [idx for idx in numeric_cols.keys() if idx != category_col_idx]
        if val_col_indices:
            cat_col_name = columns[category_col_idx - 1]
            is_time_series = _is_time_series_column(cat_col_name) or any(
                re.search(pat, question.lower()) for pat in TIME_SERIES_PATTERNS
            )

            # Buat chart sesuai karakteristik data
            if is_time_series and len(rows) >= 3:
                chart = LineChart()
                chart.style = 13
                chart.y_axis.title = "Nilai"
                chart.x_axis.title = cat_col_name.replace('_', ' ').title()
            else:
                chart = BarChart()
                chart.type = "col"
                chart.style = 10
                chart.y_axis.title = "Nilai"
                chart.x_axis.title = cat_col_name.replace('_', ' ').title()

            chart_title = f"Grafik {tab_name or 'Perbandingan'}"
            chart.title = chart_title
            chart.width = 16
            chart.height = 11

            # Referensi Kategori (X-Axis)
            cats_ref = Reference(
                ws,
                min_col=category_col_idx,
                min_row=start_row + 1,
                max_row=start_row + len(rows)
            )
            chart.set_categories(cats_ref)

            # Referensi Data (Hanya metrik numerik terpilih)
            for v_col in val_col_indices[:3]:  # Maksimal 3 metrik agar chart tidak sesak
                data_ref = Reference(
                    ws,
                    min_col=v_col,
                    min_row=start_row,
                    max_row=start_row + len(rows)
                )
                chart.add_data(data_ref, titles_from_data=True)

            if len(val_col_indices) == 1:
                chart.legend = None

            # Letakkan grafik di samping tabel data
            chart_col_letter = get_column_letter(len(columns) + 2)
            chart_anchor = f"{chart_col_letter}5"
            ws.add_chart(chart, chart_anchor)

    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()
