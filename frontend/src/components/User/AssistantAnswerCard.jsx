import { Component, useMemo, useState } from 'react';
import {
  AlertTriangle, Check, ChevronRight, ChevronLeft, Database, Layers, X,
  Loader2, TrendingUp, TrendingDown, Lightbulb, Compass, Award,
  Car, Wrench, Package, FileSpreadsheet, ArrowUpDown, ArrowUp, ArrowDown, Copy, Search,
  SplitSquareVertical, Calendar, ArrowRight, Table2,
  BarChart2, LineChart as LineChartIcon, Table as TableIcon,
} from 'lucide-react';
import {
  ResponsiveContainer, BarChart, Bar, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, Legend,
} from 'recharts';
import { api } from '../../services/api';
import { hitungSmartInsights, buatRekomendasiPertanyaan } from '../../utils/smartInsights';
import toast from 'react-hot-toast';

/** Durasi ms -> teks ringkas ("320 ms" / "1,4 dtk"). */
function formatDurasi(ms) {
  if (ms === null || ms === undefined) return null;
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} dtk`;
}

const COLUMN_LABEL_DICT = {
  tglinvoice: 'Tgl Invoice',
  tgl_invoice: 'Tgl Invoice',
  nomor: 'No. Transaksi',
  hpunit: 'Harga Pokok Unit',
  hpdpp: 'DPP Pembelian',
  hpppn: 'PPN Pembelian',
  hppbm: 'PPnBM Pembelian',
  hjunit: 'Harga Jual Unit',
  hargajual: 'Harga Jual',
  hargabeli: 'Harga Beli',
  cogs: 'COGS / HPP',
  hjakhir: 'Total Penjualan Akhir',
  totalestimasibiaya: 'Total Estimasi Biaya',
  nomor_customer: 'No. Customer',
  nopolisi: 'No. Polisi',
  penerima: 'Penerima / SA',
  nama_foreman: 'Nama Foreman',
  batal: 'Batal',
  retur: 'Retur',
  tahun: 'Tahun',
  bulan: 'Bulan',
  kategori: 'Kategori',
  divisi: 'Kategori',
  total_transaksi: 'Total Transaksi',
  total_omzet: 'Total Omzet',
  total_pembelian: 'Total Pembelian',
  total_penjualan: 'Total Penjualan',
  total_unit: 'Total Unit',
  total_unit_terjual: 'Unit Terjual',
  total_unit_dibeli: 'Unit Dibeli',
  kontribusi_omzet: 'Kontribusi Omzet',
  kode_parts: 'Kode Part',
  nama_parts: 'Nama Part',
  stockawal: 'Stok Awal',
  masuk: 'Stok Masuk',
  keluar: 'Stok Keluar',
  norangka: 'No. Rangka (VIN)',
  nochassis: 'No. Chassis',
  tipe: 'Tipe Kendaraan',
  warna: 'Warna',
};

function formatHeaderKolom(colName) {
  if (!colName) return '';
  const clean = String(colName).trim().toLowerCase();
  if (COLUMN_LABEL_DICT[clean]) return COLUMN_LABEL_DICT[clean];
  return clean
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

const UANG_KEYWORDS = [
  'harga', 'omzet', 'omset', 'beli', 'jual', 'biaya', 'uang', 'dpp', 'ppn',
  'nominal', 'saldo', 'total_pembelian', 'total_penjualan', 'total_nilai',
  'pembelian', 'penjualan', 'hpunit', 'hpdpp', 'hpppn', 'hppbm', 'tarif', 'subtotal', 'diskon',
  'selisih', 'laba', 'rugi', 'profit', 'margin', 'pendapatan', 'piutang', 'hutang',
  'nilai_transaksi', 'hjakhir', 'hjunit',
];

// Kolom yang pasti kuantitas / hitungan unit — BUKAN uang
const KUANTITAS_KEYWORDS = [
  'jumlah', 'qty', 'count', 'cnt', 'banyak', 'total_unit', 'unit_terjual',
  'frekuensi', 'freq', 'banyaknya', 'nomor', 'kode',
  'kuantiti', 'kuantitas', 'quantity', 'transaksi', 'total_transaksi',
  'jumlah_transaksi', 'pkb', 'total_pkb', 'unit', 'total_item',
  'item_terjual', 'part_terjual', 'terjual_unit', 'pcs', 'lembar',
  'orang', 'pelanggan', 'customer', 'antrean',
];

// Pengecualian: kolom yang mengandung kata 'jumlah' / 'total' tapi eksplisit uang
const EKSPLISIT_UANG = [
  'jumlah_nominal', 'jumlah_uang', 'jumlah_biaya', 'jumlah_rupiah', 'jumlah_rp',
  'total_nominal', 'total_biaya', 'total_rupiah', 'total_rp', 'total_nilai',
  'nilai_transaksi', 'hpunit', 'hpdpp', 'hpppn', 'hppbm', 'hp_unit', 'harga_unit', 'harga_per_unit',
  'total_pembelian', 'total_penjualan', 'total_omzet', 'nominal_pembelian', 'nominal_penjualan',
];

function isKolomUang(colName) {
  if (!colName) return false;
  const col = String(colName).toLowerCase();
  if (EKSPLISIT_UANG.some((k) => col.includes(k))) return true;
  if (KUANTITAS_KEYWORDS.some((k) => col.includes(k))) return false;
  return UANG_KEYWORDS.some((k) => col.includes(k));
}

/** Format angka besar ke format Rupiah standar eksekutif (Triliun, Miliar, Juta). */
function formatNominalSingkat(num) {
  if (num === null || num === undefined || Number.isNaN(Number(num))) return 'Rp 0';
  const val = Number(num);
  const abs = Math.abs(val);
  const prefix = val < 0 ? '-Rp ' : 'Rp ';

  if (abs >= 1_000_000_000_000) {
    const valStr = (abs / 1_000_000_000_000).toFixed(2).replace(/\.?0+$/, '').replace('.', ',');
    return `${prefix}${valStr} Triliun`;
  }
  if (abs >= 1_000_000_000) {
    const valStr = (abs / 1_000_000_000).toFixed(2).replace(/\.?0+$/, '').replace('.', ',');
    return `${prefix}${valStr} Miliar`;
  }
  if (abs >= 1_000_000) {
    const valStr = (abs / 1_000_000).toFixed(2).replace(/\.?0+$/, '').replace('.', ',');
    return `${prefix}${valStr} Juta`;
  }
  return `${prefix}${new Intl.NumberFormat('id-ID').format(Math.round(abs))}`;
}

/** Bersihkan notasi ilmiah dan angka di teks ringkasan agar rapi dengan format Rupiah human-readable (Juta, Miliar, Triliun). */
function bersihkanRingkasan(teks) {
  if (!teks) return '';

  let hasil = teks;

  // 1. Tangani format prefix key: value (mis. total_penjualan: 189924000000 atau omzet: 4.5e8)
  hasil = hasil.replace(/([a-zA-Z0-9_]+:\s*)([+-]?\d+(?:\.\d+)?[eE][+-]?\d+|[+-]?\d+)/g, (match, prefix, numStr) => {
    const num = Number(numStr);
    if (Number.isNaN(num)) return match;
    const isUang = isKolomUang(prefix);
    const isPersen = prefix.toLowerCase().includes('persen') || prefix.toLowerCase().includes('pct');
    if (isUang) {
      return `${prefix}${formatNominalSingkat(num)}`;
    }
    if (isPersen) {
      const formatted = new Intl.NumberFormat('id-ID', { maximumFractionDigits: 2 }).format(Math.abs(num));
      return `${prefix}${num < 0 ? '-' : ''}${formatted}%`;
    }
    const formatted = new Intl.NumberFormat('id-ID', { maximumFractionDigits: 2 }).format(Math.abs(Math.round(num)));
    return `${prefix}${num < 0 ? '-' : ''}${formatted}`;
  });

  // 2. Tangani angka nominal besar yang didahului 'Rp' atau 'total Rp' (mis. "total Rp 189.924.000.000" -> "total Rp 189,92 Miliar")
  hasil = hasil.replace(/(\b(?:total\s+)?Rp\s*)([0-9]{1,3}(?:\.[0-9]{3})+(?:,\d+)?|[0-9]{7,})/gi, (match, prefix, numStr) => {
    const rawDigits = numStr.replace(/\./g, '').replace(',', '.');
    const num = Number(rawDigits);
    if (Number.isNaN(num) || Math.abs(num) < 1_000_000) return match;
    const isTotal = /total/i.test(prefix);
    return `${isTotal ? 'total ' : ''}${formatNominalSingkat(num)}`;
  });

  // 3. Tangani kolom biaya otomotif atau nominal yang tertempel suffix (mis. "225.713.358.000 nominal pembelian" -> "Rp 225,71 Miliar" atau "310.578.000 hpunit" -> "Rp 310,58 Juta")
  hasil = hasil.replace(/([0-9]{1,3}(?:\.[0-9]{3})+(?:,\d+)?|[0-9]{7,})\s*(?:nominal\s+pembelian|nominal\s+penjualan|nominal|pembelian|penjualan|hpunit|hpdpp|hpppn|hppbm|hjunit|hjakhir)\b/gi, (match, numStr) => {
    const rawDigits = numStr.replace(/\./g, '').replace(',', '.');
    const num = Number(rawDigits);
    if (Number.isNaN(num) || Math.abs(num) < 1_000_000) return match;
    return formatNominalSingkat(num);
  });

  // 4. Ekspansi singkatan lama 'M' / 'Jt' / 'T' jika masih ada di ringkasan (mis. "Rp 452,8 M" -> "Rp 452,8 Miliar")
  hasil = hasil.replace(/Rp\s*([0-9]+(?:,[0-9]+)?)\s*M\b/g, 'Rp $1 Miliar');
  hasil = hasil.replace(/Rp\s*([0-9]+(?:,[0-9]+)?)\s*Jt\b/g, 'Rp $1 Juta');
  hasil = hasil.replace(/Rp\s*([0-9]+(?:,[0-9]+)?)\s*T\b/g, 'Rp $1 Triliun');

  return hasil;
}

/**
 * Format cerdas tanggal dan waktu Indonesia (tanpa pergeseran zona waktu):
 * 1. Hanya tanggal: jika nilai berupa tanggal murni atau waktu jam 00:00:00 (cth: "11 Nov 2025")
 * 2. Hanya waktu: jika nilai berupa waktu saja (cth: "14:30")
 * 3. Keduanya: jika terdapat tanggal dan waktu nyata bukan jam 00:00:00 (cth: "11 Nov 2025, 14:35")
 */
function formatTanggalWaktu(nilai) {
  if (nilai === null || nilai === undefined) return null;
  if (typeof nilai !== 'string' && !(nilai instanceof Date)) return null;
  const str = typeof nilai === 'string' ? nilai.trim() : nilai.toISOString();
  if (!str) return null;

  // 1. Waktu saja: HH:mm:ss atau HH:mm
  const timeOnly = str.match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?$/);
  if (timeOnly) {
    const hh = parseInt(timeOnly[1], 10);
    const mm = parseInt(timeOnly[2], 10);
    const ss = timeOnly[3] !== undefined ? parseInt(timeOnly[3], 10) : 0;
    if (hh >= 0 && hh <= 23 && mm >= 0 && mm <= 59 && ss >= 0 && ss <= 59) {
      const hhStr = String(hh).padStart(2, '0');
      const mmStr = String(mm).padStart(2, '0');
      return ss > 0 ? `${hhStr}:${mmStr}:${String(ss).padStart(2, '0')}` : `${hhStr}:${mmStr}`;
    }
  }

  // 2. Format ISO: YYYY-MM-DD atau YYYY/MM/DD
  const isoMatch = str.match(/^(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:[T\s](\d{1,2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?(?:Z|[+-]\d{2}(?::?\d{2})?)?)?$/);
  if (isoMatch) {
    const year = parseInt(isoMatch[1], 10);
    const month = parseInt(isoMatch[2], 10);
    const day = parseInt(isoMatch[3], 10);
    if (year >= 1900 && year <= 2100 && month >= 1 && month <= 12 && day >= 1 && day <= 31) {
      // Gunakan local constructor (year, month - 1, day) untuk mencegah pergeseran zona waktu
      const d = new Date(year, month - 1, day);
      const dateFormatted = d.toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric' });
      const hasTime = isoMatch[4] !== undefined && (
        parseInt(isoMatch[4], 10) !== 0
        || parseInt(isoMatch[5], 10) !== 0
        || (isoMatch[6] !== undefined && parseInt(isoMatch[6], 10) !== 0)
      );
      if (hasTime) {
        const hh = String(parseInt(isoMatch[4], 10)).padStart(2, '0');
        const mm = String(parseInt(isoMatch[5], 10)).padStart(2, '0');
        const ss = isoMatch[6] !== undefined ? parseInt(isoMatch[6], 10) : 0;
        const timeStr = ss > 0 ? `${hh}:${mm}:${String(ss).padStart(2, '0')}` : `${hh}:${mm}`;
        return `${dateFormatted}, ${timeStr}`;
      }
      return dateFormatted;
    }
  }

  // 3. Format DD/MM/YYYY atau DD-MM-YYYY
  const dmyMatch = str.match(/^(\d{1,2})[-/](\d{1,2})[-/](\d{4})(?:[T\s](\d{1,2}):(\d{2})(?::(\d{2}))?)?$/);
  if (dmyMatch) {
    const day = parseInt(dmyMatch[1], 10);
    const month = parseInt(dmyMatch[2], 10);
    const year = parseInt(dmyMatch[3], 10);
    if (year >= 1900 && year <= 2100 && month >= 1 && month <= 12 && day >= 1 && day <= 31) {
      const d = new Date(year, month - 1, day);
      const dateFormatted = d.toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric' });
      const hasTime = dmyMatch[4] !== undefined && (
        parseInt(dmyMatch[4], 10) !== 0
        || parseInt(dmyMatch[5], 10) !== 0
        || (dmyMatch[6] !== undefined && parseInt(dmyMatch[6], 10) !== 0)
      );
      if (hasTime) {
        const hh = String(parseInt(dmyMatch[4], 10)).padStart(2, '0');
        const mm = String(parseInt(dmyMatch[5], 10)).padStart(2, '0');
        const ss = dmyMatch[6] !== undefined ? parseInt(dmyMatch[6], 10) : 0;
        const timeStr = ss > 0 ? `${hh}:${mm}:${String(ss).padStart(2, '0')}` : `${hh}:${mm}`;
        return `${dateFormatted}, ${timeStr}`;
      }
      return dateFormatted;
    }
  }

  return null;
}

/** Sel tabel: null/undefined tampil sebagai garis, tanggal/waktu, angka dan uang diformat id-ID rapi. */
function formatSel(nilai, colName = '') {
  if (nilai === null || nilai === undefined) return '—';

  // Format otomatis tanggal dan waktu (cerdas: tanggal saja, waktu saja, atau keduanya)
  const tglWaktu = formatTanggalWaktu(nilai);
  if (tglWaktu !== null) return tglWaktu;

  const isAngka = typeof nilai === 'number'
    || (typeof nilai === 'string' && nilai.trim() !== '' && !Number.isNaN(Number(nilai)));

  if (isAngka) {
    const num = Number(nilai);
    const colStr = String(colName || '').toLowerCase();
    // Kolom tahun (mis. 2025 atau 2026): tampilkan apa adanya tanpa Rp dan tanpa pemisah ribuan
    if (Number.isInteger(num) && num >= 1900 && num <= 2100 && (colStr.includes('tahun') || colStr.includes('thn') || colStr === '')) {
      return String(num);
    }
    // Deteksi musiman / periode finansial: semester_..., kuartal_..., q1_..., q2_...
    const isPeriodeMusiman = /^(semester|kuartal|triwulan|q[1-4]|s[1-2])(_|\b)/i.test(colStr);
    const isNominalBesar = Math.abs(num) >= 100000;
    const isKuantitas = KUANTITAS_KEYWORDS.some((k) => colStr.includes(k));
    const isUang = !isKuantitas && (isKolomUang(colName) || (isPeriodeMusiman && isNominalBesar));

    const formatted = new Intl.NumberFormat('id-ID', { maximumFractionDigits: 2 }).format(Math.abs(num));
    if (isUang) {
      return num < 0 ? `-Rp ${formatted}` : `Rp ${formatted}`;
    }
    const isPersen = colStr.includes('persen') || colStr.includes('percent') || colStr.includes('pct');
    if (isPersen) {
      return `${num < 0 ? '-' : ''}${formatted}%`;
    }
    return `${num < 0 ? '-' : ''}${formatted}`;
  }
  return String(nilai);
}

/** Formatter sumbu Y ringkas standar eksekutif (cth: 500 rb, 1,2 jt, 69,8 M, 10 T). */
function formatCompactAxis(val, isUang = false) {
  if (val === null || val === undefined || Number.isNaN(Number(val))) return '0';
  const num = Math.abs(Number(val));
  const prefix = val < 0 ? '-' : '';
  const currency = isUang ? 'Rp ' : '';

  if (num >= 1_000_000_000_000) {
    return `${currency}${prefix}${(num / 1_000_000_000_000).toLocaleString('id-ID', { maximumFractionDigits: 1 })} T`;
  }
  if (num >= 1_000_000_000) {
    return `${currency}${prefix}${(num / 1_000_000_000).toLocaleString('id-ID', { maximumFractionDigits: 1 })} M`;
  }
  if (num >= 1_000_000) {
    return `${currency}${prefix}${(num / 1_000_000).toLocaleString('id-ID', { maximumFractionDigits: 1 })} jt`;
  }
  if (num >= 1_000) {
    return `${currency}${prefix}${(num / 1_000).toLocaleString('id-ID', { maximumFractionDigits: 1 })} rb`;
  }
  return `${currency}${prefix}${num.toLocaleString('id-ID')}`;
}

/** Deteksi apakah hasil data kueri cocok untuk ditampilkan sebagai grafik (0 token). */
function deteksiKecocokanGrafik(columns, rows) {
  if (!columns || !rows || rows.length === 0) return { cocok: false, shouldDefaultChart: false };

  let categoryIdx = -1;
  const numericIndices = [];

  for (let i = 0; i < columns.length; i += 1) {
    const colName = String(columns[i]).toLowerCase();
    const sampleVal = rows[0]?.[i] !== undefined ? rows[0][i] : rows[0]?.[columns[i]];
    const isNum = typeof sampleVal === 'number' || (!Number.isNaN(Number(sampleVal)) && String(sampleVal).trim() !== '');

    const isPriorityCategory = /tahun|thn|year|bulan|bln|month|periode|cabang|nama|kategori|tipe|model|jenis|tanggal|tgl|date/i.test(colName);

    if (isPriorityCategory && categoryIdx === -1) {
      categoryIdx = i;
    } else if (isNum && !isPriorityCategory) {
      numericIndices.push(i);
    } else if (!isNum && categoryIdx === -1) {
      categoryIdx = i;
    }
  }

  if (categoryIdx === -1 && columns.length > 1) {
    categoryIdx = 0;
  }

  if (numericIndices.length === 0) {
    for (let i = 0; i < columns.length; i += 1) {
      if (i !== categoryIdx) {
        const sampleVal = rows[0]?.[i] !== undefined ? rows[0][i] : rows[0]?.[columns[i]];
        if (typeof sampleVal === 'number' || (!Number.isNaN(Number(sampleVal)) && String(sampleVal).trim() !== '')) {
          numericIndices.push(i);
        }
      }
    }
  }

  if (categoryIdx === -1 || numericIndices.length === 0) {
    return { cocok: false, shouldDefaultChart: false };
  }

  const categoryCol = columns[categoryIdx];
  const valueCols = numericIndices.map((idx) => columns[idx]);
  const isTimeSeries = /tahun|thn|year|bulan|bln|month|periode|quarter|semester|tanggal|tgl|date/i.test(categoryCol);
  const hasCurrencyCol = valueCols.some((c) => isKolomUang(c));

  const chartData = rows.slice(0, 50).map((r) => {
    const cells = Array.isArray(r) ? r : Object.values(r || {});
    let catVal = cells[categoryIdx] ?? '';
    // Ringkas format tanggal ISO menjadi YYYY-MM-DD
    if (typeof catVal === 'string' && catVal.length > 10 && catVal.includes('T')) {
      catVal = catVal.substring(0, 10);
    }
    const obj = { [categoryCol]: String(catVal) };
    numericIndices.forEach((numIdx) => {
      const colName = columns[numIdx];
      const val = Number(cells[numIdx]);
      obj[colName] = Number.isNaN(val) ? 0 : val;
    });
    return obj;
  });

  // Otomatis buka grafik jika time-series atau komparasi kategori (2 - 50 data points)
  const shouldDefaultChart = Boolean(
    rows.length > 1 &&
    rows.length <= 50 &&
    numericIndices.length > 0 &&
    (isTimeSeries || rows.length >= 3)
  );

  const title = isTimeSeries
    ? `Dinamika Tren Berdasarkan ${categoryCol.replace(/_/g, ' ')}`
    : `Grafik Perbandingan ${valueCols[0]?.replace(/_/g, ' ') || 'Data'}`;

  return {
    cocok: true,
    shouldDefaultChart,
    isTimeSeries,
    hasCurrencyCol,
    categoryCol,
    valueCols,
    chartData,
    title,
  };
}

const BAR_COLORS = ['#cc785c', '#2e6f77', '#d97706', '#475569', '#059669', '#7c3aed'];

/** Silent Error Boundary: Cegah error runtime chart agar tidak merusak UI user. */
class SilentChartErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error, info) {
    console.warn('AutoChart visualizer silent fallback to table:', error, info);
  }

  render() {
    if (this.state.hasError) {
      return this.props.fallback;
    }
    return this.props.children;
  }
}

function CustomChartTooltip({ active, payload, label }) {
  if (active && payload && payload.length) {
    return (
      <div className="bg-canvas border border-hairline rounded-md p-2.5 shadow-sm text-xs space-y-1 z-50">
        <p className="font-semibold text-ink border-b border-hairline pb-1 mb-1.5">{label}</p>
        {payload.map((entry, index) => (
          <div key={index} className="flex items-center justify-between gap-4">
            <span className="flex items-center gap-1.5 text-muted">
              <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: entry.color }} />
              <span>{entry.name}:</span>
            </span>
            <span className="font-semibold text-ink font-mono">
              {formatSel(entry.value, entry.name)}
            </span>
          </div>
        ))}
      </div>
    );
  }
  return null;
}

/**
 * Render inline markdown (**teks tebal**, *teks miring*, `kode`) secara aman dan elegan
 * untuk menghasilkan tipografi berstandar editorial layaknya Claude/Gemini/GPT.
 */
function renderMarkdownInline(str) {
  if (!str || typeof str !== 'string') return str;
  const parts = [];
  const regex = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g;
  let lastIndex = 0;
  let match;

  while ((match = regex.exec(str)) !== null) {
    if (match.index > lastIndex) {
      parts.push(str.substring(lastIndex, match.index));
    }
    const token = match[0];
    if (token.startsWith('**') && token.endsWith('**') && token.length >= 4) {
      parts.push(
        <strong key={match.index} className="font-semibold text-ink">
          {token.slice(2, -2)}
        </strong>
      );
    } else if (token.startsWith('*') && token.endsWith('*') && token.length >= 2) {
      parts.push(
        <em key={match.index} className="italic text-ink/90">
          {token.slice(1, -1)}
        </em>
      );
    } else if (token.startsWith('`') && token.endsWith('`') && token.length >= 2) {
      parts.push(
        <code key={match.index} className="font-mono text-xs bg-surface-card border border-hairline px-1.5 py-0.5 rounded text-primary">
          {token.slice(1, -1)}
        </code>
      );
    }
    lastIndex = regex.lastIndex;
  }

  if (lastIndex < str.length) {
    parts.push(str.substring(lastIndex));
  }

  return parts.length > 0 ? parts : str;
}

/**
 * Parse teks markdown menjadi blok-blok terstruktur (paragraf, judul, tabel, daftar, rekomendasi).
 */
function parseMarkdownBlocks(text) {
  if (!text || typeof text !== 'string') return [];

  // Jika teks padat berbaris tanpa baris baru, pecah berdasarkan kalimat transisi
  let normalized = text;
  if (!normalized.includes('\n') && normalized.length > 160) {
    const splitRegex = /(?=\b(?:Namun,|Jika angka nol|Jika hanya masalah|Jika benar tidak|Langkah pertama|Rekomendasi:)\b)/g;
    const parts = normalized.split(splitRegex).map((p) => p.trim()).filter(Boolean);
    if (parts.length > 1) {
      normalized = parts.join('\n\n');
    }
  }

  const rawLines = normalized.replace(/\r\n/g, '\n').split('\n');
  const blocks = [];
  let i = 0;

  while (i < rawLines.length) {
    const line = rawLines[i];
    const trimmed = line.trim();

    // 1. Lewati baris kosong
    if (!trimmed) {
      i++;
      continue;
    }

    // 2. Blok Rekomendasi Strategis
    if (/^Rekomendasi:/i.test(trimmed)) {
      let rawContent = trimmed.replace(/^Rekomendasi:\s*/i, '');
      i++;
      const bulletItems = [];
      if (rawContent && (rawContent.startsWith('•') || rawContent.startsWith('-') || rawContent.startsWith('*'))) {
        bulletItems.push(rawContent.replace(/^[•\-*]\s*/, '').trim());
        rawContent = '';
      }
      while (i < rawLines.length) {
        const rLine = rawLines[i].trim();
        if (!rLine) break;
        if (/^[•\-*]|\d+\.\s/.test(rLine)) {
          bulletItems.push(rLine.replace(/^[•\-*]\s*|\d+\.\s*/, '').trim());
          i++;
        } else if (!rawContent && bulletItems.length === 0) {
          rawContent = rLine;
          i++;
        } else {
          break;
        }
      }
      blocks.push({
        type: 'rekomendasi',
        rawContent,
        bulletItems,
      });
      continue;
    }

    // 3. Heading Markdown: #, ##, ###
    const headingMatch = trimmed.match(/^(#{1,6})\s+(.*)$/);
    if (headingMatch) {
      blocks.push({
        type: 'heading',
        level: headingMatch[1].length,
        text: headingMatch[2].trim(),
      });
      i++;
      continue;
    }

    // 4. Tabel Markdown: baris awal dengan pipa '|' dan baris kedua pemisah '| --- |'
    if (trimmed.startsWith('|') && trimmed.endsWith('|') && i + 1 < rawLines.length) {
      const nextTrimmed = rawLines[i + 1].trim();
      const isSeparator = /^\|?(\s*:?-{2,}:?\s*\|)+\s*:?-{2,}:?\s*\|?$/.test(nextTrimmed);
      if (isSeparator) {
        const parseRow = (rowStr) => {
          const clean = rowStr.trim().replace(/^\|/, '').replace(/\|$/, '');
          return clean.split('|').map((c) => c.trim());
        };

        const headers = parseRow(trimmed);
        const sepCols = parseRow(nextTrimmed);
        const alignments = sepCols.map((c) => {
          const left = c.startsWith(':');
          const right = c.endsWith(':');
          if (left && right) return 'center';
          if (right) return 'right';
          return 'left';
        });

        i += 2;
        const rows = [];
        while (i < rawLines.length && rawLines[i].trim().startsWith('|')) {
          rows.push(parseRow(rawLines[i].trim()));
          i++;
        }

        blocks.push({
          type: 'table',
          headers,
          alignments,
          rows,
        });
        continue;
      }
    }

    // 5. Daftar Berbutir / Bernomor: •, -, *, atau 1.
    const isList = /^[•\-*]\s+|^\d+\.\s+/.test(trimmed);
    if (isList) {
      const items = [];
      while (i < rawLines.length) {
        const itemLine = rawLines[i].trim();
        if (!itemLine) break;
        if (/^[•\-*]\s+|^\d+\.\s+/.test(itemLine)) {
          const isNumbered = /^\d+\.\s+/.test(itemLine);
          const cleanText = itemLine.replace(/^[•\-*]\s+|^\d+\.\s+/, '');
          items.push({ isNumbered, text: cleanText });
          i++;
        } else if (items.length > 0 && !itemLine.startsWith('#') && !itemLine.startsWith('|')) {
          items[items.length - 1].text += ` ${itemLine}`;
          i++;
        } else {
          break;
        }
      }
      blocks.push({
        type: 'list',
        items,
      });
      continue;
    }

    // 6. Paragraf Biasa: kumpulkan baris hingga baris kosong atau blok baru
    const paraLines = [];
    while (i < rawLines.length) {
      const pLine = rawLines[i].trim();
      if (!pLine) break;
      if (/^Rekomendasi:/i.test(pLine)) break;
      if (pLine.startsWith('#')) break;
      if (
        pLine.startsWith('|') &&
        pLine.endsWith('|') &&
        i + 1 < rawLines.length &&
        /^\|?(\s*:?-{2,}:?\s*\|)+\s*:?-{2,}:?\s*\|?$/.test(rawLines[i + 1].trim())
      ) {
        break;
      }
      if (/^[•\-*]\s+|^\d+\.\s+/.test(pLine)) break;

      paraLines.push(pLine);
      i++;
    }

    if (paraLines.length > 0) {
      blocks.push({
        type: 'paragraph',
        text: paraLines.join(' '),
      });
    }
  }

  return blocks;
}

/**
 * Komponen Markdown Content dengan hierarki tipografi editorial,
 * mendukung paragraf mengalir, heading, tabel Markdown berstandar tinggi, dan daftar.
 */
function MarkdownNarrativeContent({ content }) {
  if (!content) return null;
  const blocks = parseMarkdownBlocks(content);

  return (
    <div className="space-y-3 font-sans text-sm sm:text-[14.5px] leading-relaxed text-ink">
      {blocks.map((block, idx) => {
        if (block.type === 'heading') {
          if (block.level <= 2) {
            return (
              <h2 key={idx} className="font-semibold text-ink text-base sm:text-[16px] mt-4 mb-1.5 tracking-tight flex items-center gap-2">
                <span className="w-1 h-4 bg-primary rounded-full inline-block shrink-0" />
                <span>{renderMarkdownInline(block.text)}</span>
              </h2>
            );
          }
          return (
            <h3 key={idx} className="font-semibold text-ink text-xs sm:text-[13.5px] uppercase tracking-wider mt-3 mb-1.5 flex items-center gap-2 text-muted">
              <span className="w-1 h-3 bg-primary/80 rounded-full inline-block shrink-0" />
              <span className="text-ink font-medium">{renderMarkdownInline(block.text)}</span>
            </h3>
          );
        }

        if (block.type === 'table') {
          return (
            <div key={idx} className="overflow-x-auto rounded-lg border border-hairline my-3.5 bg-canvas shadow-2xs">
              <table className="w-full text-left text-xs sm:text-[13px] border-collapse">
                <thead className="bg-surface-card border-b border-hairline text-ink font-semibold">
                  <tr>
                    {block.headers.map((h, i) => {
                      const isRight = block.alignments[i] === 'right';
                      const isCenter = block.alignments[i] === 'center';
                      return (
                        <th
                          key={i}
                          className={`py-2.5 px-3.5 text-xs font-semibold uppercase tracking-wider text-muted ${
                            isRight ? 'text-right' : isCenter ? 'text-center' : 'text-left'
                          }`}
                        >
                          {renderMarkdownInline(h)}
                        </th>
                      );
                    })}
                  </tr>
                </thead>
                <tbody className="divide-y divide-hairline/60 text-body">
                  {block.rows.map((row, rIdx) => (
                    <tr key={rIdx} className="hover:bg-surface-soft/40 transition-colors">
                      {row.map((cell, cIdx) => {
                        const isNumeric = /^-?\d[\d.,]*%?$/.test(cell.trim());
                        const isRight = block.alignments[cIdx] === 'right' || isNumeric;
                        const isCenter = block.alignments[cIdx] === 'center';
                        return (
                          <td
                            key={cIdx}
                            className={`py-2.5 px-3.5 ${
                              isRight
                                ? 'text-right font-mono tabular-nums text-ink font-medium'
                                : isCenter
                                ? 'text-center'
                                : 'text-left'
                            }`}
                          >
                            {renderMarkdownInline(cell)}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }

        if (block.type === 'rekomendasi') {
          return (
            <div
              key={idx}
              className="p-4 rounded-md bg-primary/5 border-l-2 border-primary border-y border-r border-hairline/60 space-y-2.5 my-2.5"
            >
              <div className="text-xs font-semibold text-primary uppercase tracking-wider flex items-center gap-1.5">
                <Compass size={13} />
                <span>Rekomendasi Tindakan Strategis</span>
              </div>
              {block.bulletItems.length > 0 ? (
                <ul className="space-y-1.5 pl-0.5">
                  {block.bulletItems.map((item, bIdx) => (
                    <li key={bIdx} className="flex items-start gap-2 text-sm text-ink">
                      <span className="w-1.5 h-1.5 rounded-full bg-primary shrink-0 mt-2" />
                      <span className="leading-relaxed">{renderMarkdownInline(item)}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-ink text-sm leading-relaxed">{renderMarkdownInline(block.rawContent)}</p>
              )}
            </div>
          );
        }

        if (block.type === 'list') {
          return (
            <ul key={idx} className="space-y-1.5 pl-1 text-body text-xs sm:text-[13.5px] my-2">
              {block.items.map((item, lIdx) => (
                <li key={lIdx} className="flex items-start gap-2 leading-relaxed">
                  <span className="text-primary/70 shrink-0 select-none mt-0.5 font-mono text-[11px]">
                    {item.isNumbered ? `${lIdx + 1}.` : '•'}
                  </span>
                  <span className="text-body flex-1">
                    {renderMarkdownInline(item.text)}
                  </span>
                </li>
              ))}
            </ul>
          );
        }

        return (
          <p key={idx} className="text-body leading-relaxed">
            {renderMarkdownInline(block.text)}
          </p>
        );
      })}
    </div>
  );
}

/** Format narasi analisis eksekutif agar terstruktur rapi menggunakan parser editorial terpadu. */
function FormattedExecutiveAnalysis({ text }) {
  if (!text) return null;
  return <MarkdownNarrativeContent content={text} />;
}

/**
 * Executive KPI Metric Banner (Zero-Token).
 * Menyajikan kartu ringkasan eksekutif 3-kolom: Total Akumulasi, Dinamika Tren / Rata-Rata, dan Rekor Puncak.
 */
function KpiMetricBanner({ smartInsights }) {
  if (!smartInsights || !smartInsights.hasInsights) return null;

  const {
    metricName,
    totalFormatted,
    rataRataFormatted,
    tertinggi,
    deltaPersen,
    arahTren,
    jumlahData,
  } = smartInsights;

  const hasTren = deltaPersen !== null;
  const hasMultiple = jumlahData > 1;

  return (
    <div className="bg-surface-card/60 border border-hairline rounded-lg p-3.5 space-y-2.5 shadow-2xs">
      <div className="flex items-center justify-between text-muted text-[11px] border-b border-hairline/60 pb-2">
        <span className="inline-flex items-center gap-1.5 font-medium text-ink tracking-wide">
          <Award size={13} className="text-primary" />
          <span>Indikator Kinerja Utama (KPI)</span>
        </span>
        <span className="font-mono tabular-nums text-muted">{jumlahData} baris data</span>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5 pt-0.5">
        {/* Card 1: Total Akumulasi */}
        <div className="bg-canvas border border-hairline rounded-md p-3 flex flex-col justify-between">
          <div className="text-[10px] font-mono text-muted uppercase tracking-wider">
            Total {metricName || 'Nilai'}
          </div>
          <div className="text-lg sm:text-xl font-medium font-sans text-ink tabular-nums mt-1">
            {totalFormatted}
          </div>
          <div className="text-[11px] text-muted truncate mt-1">
            {hasMultiple ? `Akumulasi dari ${jumlahData} baris data` : 'Total keseluruhan tercatat'}
          </div>
        </div>

        {/* Card 2: Rata-Rata atau Dinamika Tren */}
        <div className="bg-canvas border border-hairline rounded-md p-3 flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-mono text-muted uppercase tracking-wider">
              {hasTren ? 'Dinamika Tren' : 'Rata-Rata'}
            </span>
            {hasTren && (
              <span
                className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium font-mono tabular-nums ${
                  arahTren === 'naik'
                    ? 'bg-emerald-50/90 text-emerald-800 border border-emerald-200/80'
                    : arahTren === 'turun'
                      ? 'bg-rose-50/90 text-rose-800 border border-rose-200/80'
                      : 'bg-surface-soft text-body border border-hairline'
                }`}
              >
                {arahTren === 'naik' ? <TrendingUp size={10} /> : arahTren === 'turun' ? <TrendingDown size={10} /> : null}
                <span>{Number(deltaPersen) > 0 ? `+${deltaPersen}%` : `${deltaPersen}%`}</span>
              </span>
            )}
          </div>
          <div className="text-lg sm:text-xl font-medium font-sans text-ink tabular-nums mt-1">
            {rataRataFormatted || (hasTren ? `${deltaPersen}%` : totalFormatted)}
          </div>
          <div className="text-[11px] text-muted truncate mt-1">
            {hasTren && rataRataFormatted ? `Rata-rata: ${rataRataFormatted}` : hasMultiple ? 'Rata-rata per periode' : 'Nilai tercatat'}
          </div>
        </div>

        {/* Card 3: Puncak Tertinggi / Rekor */}
        <div className="bg-canvas border border-hairline rounded-md p-3 flex flex-col justify-between">
          <div className="text-[10px] font-mono text-muted uppercase tracking-wider">
            {tertinggi ? 'Puncak Tertinggi' : 'Status Performa'}
          </div>
          <div className="text-lg sm:text-xl font-medium font-sans text-ink tabular-nums mt-1 truncate">
            {tertinggi ? tertinggi.nilaiFormatted : 'Optimal'}
          </div>
          <div className="text-[11px] text-muted truncate mt-1" title={tertinggi ? tertinggi.label : ''}>
            {tertinggi ? `Periode: ${tertinggi.label}` : 'Sesuai data operasional'}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function AssistantAnswerCard({
  answer,
  question,
  branchCode,
  createdAt,
  memoryStatus,
  feedbackBusy,
  onAsk,
  onConfirm,
  onReject,
}) {
  const [userTabPreference, setUserTabPreference] = useState(null); // 'hybrid' | 'table' | 'chart' | null
  const [chartType, setChartType] = useState('bar'); // 'bar' | 'line'
  const [penjelasan, setPenjelasan] = useState(null);
  const [loadingExplain, setLoadingExplain] = useState(false);
  const [activeDomainTab, setActiveDomainTab] = useState(0);
  const [isExporting, setIsExporting] = useState(false);
  const [tableSearch, setTableSearch] = useState('');
  const [sortCol, setSortCol] = useState(null);
  const [sortDir, setSortDir] = useState('asc');
  const [tablePage, setTablePage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [isCopied, setIsCopied] = useState(false);
  const [showExportExcel] = useState(false); // Fitur ekspor Excel di-hold sementara sesuai arahan user

  // Filter hanya tab yang memiliki data nyata (>0 baris)
  const validTabs = useMemo(() => {
    if (!answer.is_multi_tab || !Array.isArray(answer.tabs)) return [];
    return answer.tabs.filter((tab) => {
      const rowCount = tab.row_count ?? tab.rows?.length ?? 0;
      return rowCount > 0;
    });
  }, [answer.is_multi_tab, answer.tabs]);

  // Bar tab HANYA aktif jika ada minimal 2 tabel/domain yang memiliki data
  const isMultiTab = validTabs.length > 1;

  // Jika hanya ada 1 tab berisi data, langsung pakai tab tersebut; jika >= 2 pakai tab yang diklik user
  const currentTab = useMemo(() => {
    if (isMultiTab) {
      return validTabs[activeDomainTab] || validTabs[0];
    }
    if (validTabs.length === 1) {
      return validTabs[0];
    }
    return (answer.tabs && answer.tabs[0]) || answer;
  }, [isMultiTab, validTabs, activeDomainTab, answer]);

  const activeRows = useMemo(() => currentTab.rows || [], [currentTab.rows]);
  const activeColumns = useMemo(() => currentTab.columns || [], [currentTab.columns]);
  const activeSql = currentTab.sql || answer.sql || '';

  const durasi = formatDurasi(answer.duration_ms);
  const terverifikasi = answer.source === 'memory' || memoryStatus === 'confirmed';
  const ditolak = memoryStatus === 'rejected';

  // Mode Buku Rincian Transaksi (Ledger): Tiap baris adalah faktur/transaksi perorangan
  // Pada mode ini, KPI Metric Banner disembunyikan agar tidak memicu ilusi optik "total mengecil"
  const isRincianTransaksi = useMemo(() => {
    const title = String(currentTab.title || currentTab.label || '').toLowerCase();
    if (title.includes('rincian') || title.includes('detail')) {
      return true;
    }
    if (currentTab.total_full_count && currentTab.total_full_count > activeRows.length) {
      return true;
    }
    const colStr = activeColumns.map((c) => String(c).toLowerCase()).join(' ');
    const hasTxIdentifier = /nomor|norangka|nopolisi|invoice|nomor_pesanan|nomor_wo/.test(colStr);
    const hasNoAggregateCol = !activeColumns.some((c) => /total_|jumlah_|rata_|kontribusi/.test(String(c).toLowerCase()));
    return hasTxIdentifier && hasNoAggregateCol;
  }, [currentTab.title, currentTab.label, currentTab.total_full_count, activeRows.length, activeColumns]);

  const smartInsights = useMemo(
    () => (isRincianTransaksi ? null : hitungSmartInsights(activeColumns, activeRows)),
    [isRincianTransaksi, activeColumns, activeRows]
  );

  const smartSaran = useMemo(() => {
    if (ditolak || !onAsk) return [];
    const rawSaran = (Array.isArray(answer.saran) && answer.saran.length > 0)
      ? answer.saran
      : buatRekomendasiPertanyaan(
          question || answer.question || '',
          activeColumns,
          activeRows,
          activeSql
        );
    const curQ = (question || answer.question || '').toLowerCase().trim();
    const seen = new Set();
    const result = [];
    for (const s of rawSaran || []) {
      if (!s || typeof s !== 'string') continue;
      const sClean = s.trim();
      const sLower = sClean.toLowerCase();
      if (!sLower || sLower === curQ || sLower.includes(curQ) || curQ.includes(sLower)) continue;
      if (seen.has(sLower)) continue;
      seen.add(sLower);
      result.push(sClean);
      if (result.length >= 3) break;
    }
    return result;
  }, [ditolak, onAsk, answer.saran, question, answer.question, activeColumns, activeRows, activeSql]);

  const breakdownSaran = useMemo(() => {
    if (!onAsk || ditolak) return [];
    if (!answer.is_comparison && !smartSaran.some((s) => s.toLowerCase().includes('terpisah'))) {
      return [];
    }
    return smartSaran.filter((s) => s.toLowerCase().includes('terpisah') || s.toLowerCase().includes('detail') || s.toLowerCase().includes('rincian'));
  }, [answer.is_comparison, smartSaran, onAsk, ditolak]);

  const regularSaran = useMemo(() => {
    if (breakdownSaran.length > 0) {
      return smartSaran.filter((s) => !breakdownSaran.includes(s));
    }
    return smartSaran;
  }, [smartSaran, breakdownSaran]);

  const grafikConfig = useMemo(
    () => (isRincianTransaksi ? { cocok: false, shouldDefaultChart: false } : deteksiKecocokanGrafik(activeColumns, activeRows)),
    [isRincianTransaksi, activeColumns, activeRows]
  );

  const activeTab = useMemo(() => {
    if (!grafikConfig.cocok) return 'table';
    if (userTabPreference !== null) {
      if ((userTabPreference === 'chart' || userTabPreference === 'hybrid') && !grafikConfig.cocok) {
        return 'table';
      }
      return userTabPreference;
    }
    return grafikConfig.shouldDefaultChart ? 'hybrid' : 'table';
  }, [grafikConfig, userTabPreference]);

  const handleExplain = async () => {
    if (loadingExplain || !branchCode) return;
    setLoadingExplain(true);
    try {
      const baseQ = (question || answer.question || 'Analisis data transaksi').trim() || 'Analisis data transaksi';
      const tabLabel = isMultiTab && currentTab ? (currentTab.label || currentTab.tab || '') : '';
      const qText = tabLabel && !baseQ.toLowerCase().includes(tabLabel.toLowerCase())
        ? `${baseQ} (${tabLabel})`
        : baseQ;
      const res = await api.explainChat({
        branchCode,
        question: qText,
        sql: activeSql || '-- query',
        rows: activeRows || [],
      });
      setPenjelasan(res.narasi);
    } catch (err) {
      const detail = err.response?.data?.detail;
      toast.error(typeof detail === 'string' ? detail : 'Gagal memuat penjelasan naratif.');
    } finally {
      setLoadingExplain(false);
    }
  };

  const handleExportExcel = async () => {
    if (activeRows.length === 0) {
      toast.error('Tidak ada data untuk diekspor');
      return;
    }
    setIsExporting(true);
    try {
      const tabLabel = isMultiTab && currentTab ? currentTab.label : null;
      const res = await api.exportExcel({
        branchCode,
        question: question || answer.question || 'Laporan Data Dealer',
        tabName: tabLabel,
        rows: activeRows,
        columns: activeColumns,
      });

      const disposition = res.headers ? res.headers['content-disposition'] : null;
      let filename = `Laporan_${branchCode}.xlsx`;
      if (disposition && disposition.includes('filename=')) {
        const matches = /filename="?([^"]+)"?/.exec(disposition);
        if (matches && matches[1]) {
          filename = matches[1];
        }
      }

      const url = window.URL.createObjectURL(new Blob([res.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', filename);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
      toast.success('Laporan Excel berhasil diunduh!');
    } catch (err) {
      console.error('Gagal mengekspor Excel:', err);
      toast.error('Gagal mengekspor file Excel');
    } finally {
      setIsExporting(false);
    }
  };

  const handleSort = (col) => {
    if (sortCol === col) {
      if (sortDir === 'asc') {
        setSortDir('desc');
      } else {
        setSortCol(null);
        setSortDir('asc');
      }
    } else {
      setSortCol(col);
      setSortDir('asc');
    }
    setTablePage(1);
  };

  const filteredRows = useMemo(() => {
    if (!tableSearch.trim()) return activeRows;
    const q = tableSearch.toLowerCase().trim();
    return activeRows.filter((row) => {
      const values = Array.isArray(row) ? row : Object.values(row || {});
      return values.some((val) => {
        if (val === null || val === undefined) return false;
        return String(val).toLowerCase().includes(q);
      });
    });
  }, [activeRows, tableSearch]);

  const sortedRows = useMemo(() => {
    if (!sortCol) return filteredRows;
    const colIdx = activeColumns.indexOf(sortCol);
    return [...filteredRows].sort((a, b) => {
      const valA = Array.isArray(a) ? a[colIdx] : a[sortCol];
      const valB = Array.isArray(b) ? b[colIdx] : b[sortCol];

      if (valA === null || valA === undefined) return 1;
      if (valB === null || valB === undefined) return -1;

      const numA = Number(valA);
      const numB = Number(valB);
      if (!Number.isNaN(numA) && !Number.isNaN(numB)) {
        return sortDir === 'asc' ? numA - numB : numB - numA;
      }

      const strA = String(valA).toLowerCase();
      const strB = String(valB).toLowerCase();
      return sortDir === 'asc' ? strA.localeCompare(strB) : strB.localeCompare(strA);
    });
  }, [filteredRows, sortCol, sortDir, activeColumns]);

  const totalPages = pageSize === 'all' ? 1 : Math.max(1, Math.ceil(sortedRows.length / pageSize));
  const paginatedRows = useMemo(() => {
    if (pageSize === 'all') return sortedRows;
    const start = (tablePage - 1) * pageSize;
    return sortedRows.slice(start, start + pageSize);
  }, [sortedRows, tablePage, pageSize]);

  const handleCopyTable = () => {
    if (activeRows.length === 0) return;
    const headerLine = activeColumns.join('\t');
    const rowLines = activeRows.map((row) => {
      const cells = Array.isArray(row) ? row : activeColumns.map((c) => row[c]);
      return cells.map((c) => {
        if (c === null || c === undefined) return '';
        const tglWaktu = formatTanggalWaktu(c);
        if (tglWaktu !== null) return tglWaktu;
        return String(c);
      }).join('\t');
    });
    const tsv = [headerLine, ...rowLines].join('\n');
    navigator.clipboard.writeText(tsv).then(() => {
      setIsCopied(true);
      toast.success('Data tabel disalin ke clipboard!');
      setTimeout(() => setIsCopied(false), 2000);
    }).catch(() => {
      toast.error('Gagal menyalin tabel.');
    });
  };

  const isDummySqlResponse = Boolean(
    activeColumns.length === 1 &&
    (String(activeColumns[0]).toLowerCase() === 'pesan' || String(activeColumns[0]).toLowerCase() === 'message' || String(activeColumns[0]).toLowerCase() === 'greeting')
  );

  const isConversational = Boolean(
    answer?.is_conversational_text ||
    answer?.source === 'conversational' ||
    answer?.metode === 'conversational' ||
    answer?.metode === 'conversational_explanation' ||
    answer?.metode === 'conversational_guide' ||
    isDummySqlResponse
  );

  if (isConversational) {
    const isGuide = answer?.metode === 'conversational_guide' || isDummySqlResponse;
    let rawText = answer.ringkasan || '';
    const dummyMatch = rawText.match(/Ditemukan \d+ baris hasil \(pesan:\s*(.*?)\)\.?$/i);
    if (dummyMatch && dummyMatch[1]) {
      rawText = dummyMatch[1];
    } else if (isDummySqlResponse && activeRows?.[0]) {
      const firstVal = Array.isArray(activeRows[0]) ? activeRows[0][0] : Object.values(activeRows[0])[0];
      if (firstVal && typeof firstVal === 'string') {
        rawText = firstVal;
      }
    }
    // Bersihkan karakter emoji
    rawText = rawText.replace(/[\u{1F300}-\u{1F9FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/gu, '').trim();
    const textContent = bersihkanRingkasan(rawText);

    const conversationalSaran = (Array.isArray(answer.saran) && answer.saran.length > 0)
      ? answer.saran
      : [
          'Tampilkan 5 model mobil dengan penjualan tertinggi',
          'Berapa total pendapatan servis bengkel tahun 2025?',
          'Daftar 10 customer dengan transaksi pembelian unit terbesar',
          'Tren volume transaksi servis bulanan sepanjang tahun 2024',
        ];

    return (
      <div className="bg-canvas border border-hairline rounded-lg shadow-2xs p-4 sm:p-5 space-y-4">
        {/* Header Badge */}
        <div className="flex items-center justify-between gap-3 border-b border-hairline pb-2.5 flex-wrap">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-surface-card border border-hairline text-ink text-xs font-medium">
              <Compass size={13} className="text-primary" />
              <span>Asisten Dealer AI</span>
            </span>
            <span className="text-[11px] text-muted font-mono bg-surface-card px-2 py-0.5 rounded-md border border-hairline">
              {answer?.metode === 'conversational_explanation' ? 'Penjelasan Konteks' : 'Percakapan'}
            </span>
          </div>

          <div className="flex items-center gap-2.5 text-xs text-muted font-mono">
            {durasi && !answer.sql && <span className="tabular-nums font-mono">{durasi}</span>}
          </div>
        </div>

        {/* Narrative Text */}
        <MarkdownNarrativeContent content={textContent} />

        {/* Suggestion Chips */}
        {conversationalSaran.length > 0 && onAsk && (
          <div className="pt-3 border-t border-hairline space-y-2">
            <p className="text-[11px] text-muted flex items-center gap-1.5 font-medium">
              <Compass size={12} className="text-primary" />
              <span>{isGuide ? 'Rekomendasi pertanyaan siap klik:' : 'Pertanyaan eksplorasi lanjutan:'}</span>
            </p>
            <div className="flex items-center gap-2 flex-wrap">
              {conversationalSaran.map((s, idx) => (
                <button
                  key={`${s}-${idx}`}
                  type="button"
                  onClick={() => onAsk(s)}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium border border-hairline rounded-md bg-canvas hover:bg-surface-soft hover:border-primary/40 hover:text-ink text-body transition-colors cursor-pointer text-left shadow-2xs group"
                >
                  <ArrowRight size={11} className="text-primary group-hover:translate-x-0.5 transition-transform shrink-0" />
                  <span>{s}</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    );
  }

  return (
    <>
      <div className="bg-canvas border border-hairline rounded-lg shadow-2xs p-4 sm:p-5 space-y-4">
        {/* Executive Dossier Header */}
        <div className="flex items-center justify-between gap-3 border-b border-hairline pb-3 flex-wrap">
          <div className="flex items-center gap-2 flex-wrap">
            {terverifikasi ? (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-emerald-50/80 border border-emerald-200/80 text-emerald-800 text-xs font-medium">
                <Check size={12} className="text-emerald-700" />
                <span>Memori Terverifikasi</span>
              </span>
            ) : ditolak ? (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-rose-50/80 border border-rose-200 text-rose-800 text-xs font-medium">
                <X size={12} />
                <span>Kueri Ditolak</span>
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-surface-card border border-hairline text-ink text-xs font-medium">
                <Database size={12} className="text-primary" />
                <span>Hasil Basis Data Terverifikasi</span>
              </span>
            )}
          </div>

          <div className="flex items-center gap-2.5 text-xs text-muted font-mono">
            {durasi && (
              <span className="tabular-nums font-mono">{durasi}</span>
            )}
            {activeRows.length > 0 && (
              <>
                <span className="text-muted/40">•</span>
                <span className="tabular-nums font-mono">{activeRows.length} baris</span>
              </>
            )}
          </div>
        </div>

        {/* Ringkasan Eksekutif Callout */}
        {answer.ringkasan && (
          <div className="border-l-2 border-primary pl-3.5 py-2 bg-surface-card/60 rounded-r-md">
            <div className="text-[10px] font-mono text-muted uppercase tracking-wider mb-1">
              Ringkasan Eksekutif
            </div>
            <div className="font-sans text-sm sm:text-[15px] leading-relaxed text-ink font-medium">
              {renderMarkdownInline(bersihkanRingkasan(answer.ringkasan))}
            </div>
          </div>
        )}

        {/* Tombol On-Demand Explain (Mode Operasional) */}
        {answer.allow_explain && !penjelasan && (
          <div className="pt-0.5">
            <button
              type="button"
              onClick={handleExplain}
              disabled={loadingExplain}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium border border-hairline rounded-md text-ink bg-canvas hover:bg-surface-soft transition-colors disabled:opacity-50 cursor-pointer shadow-2xs"
            >
              {loadingExplain ? <Loader2 size={12} className="animate-spin text-primary" /> : <Lightbulb size={12} className="text-primary" />}
              <span>{loadingExplain ? 'Menyusun analisis mendalam…' : 'Analisis Naratif Eksekutif'}</span>
            </button>
          </div>
        )}

        {/* Hasil Narasi Analisis Eksekutif On-Demand (Terformat rapi tanpa semut berbaris) */}
        {penjelasan && (
          <div className="bg-surface-card/70 border border-hairline rounded-lg p-4 space-y-3 animate-fadeIn">
            <div className="flex items-center gap-1.5 text-ink font-medium text-xs uppercase tracking-wider border-b border-hairline/60 pb-2">
              <Lightbulb size={13} className="text-primary" />
              <span>Analisis Eksekutif Data</span>
            </div>
            <FormattedExecutiveAnalysis text={penjelasan} />
          </div>
        )}

        {/* Multi-Domain Tab Bar - HANYA tampil jika minimal 2 tabel memiliki data */}
        {isMultiTab && (
          <div className="pt-1">
            <div className="flex items-center gap-1.5 p-1 bg-surface-card rounded-md border border-hairline overflow-x-auto">
              {validTabs.map((tab, idx) => {
                const isActive = (activeDomainTab >= validTabs.length ? 0 : activeDomainTab) === idx;
                return (
                  <button
                    key={tab.id || idx}
                    type="button"
                    onClick={() => {
                      setActiveDomainTab(idx);
                    }}
                    className={`flex items-center gap-2 px-3 py-1.5 rounded-md text-xs font-medium transition-all cursor-pointer whitespace-nowrap ${
                      isActive
                        ? 'bg-canvas shadow-xs text-primary font-medium border border-hairline'
                        : 'text-muted hover:text-ink hover:bg-surface-soft/60'
                    }`}
                  >
                    {tab.icon === 'Car' ? <Car size={13} /> :
                     tab.icon === 'Wrench' ? <Wrench size={13} /> :
                     tab.icon === 'Package' ? <Package size={13} /> :
                     tab.icon === 'Calendar' ? <Calendar size={13} /> :
                     tab.icon === 'Table2' ? <Table2 size={13} /> :
                     <Layers size={13} />}
                    <span>{tab.title}</span>
                    <span className={`px-1.5 py-0.2 rounded-full text-[10px] ${
                      isActive ? 'bg-primary/10 text-primary' : 'bg-surface-card text-muted'
                    }`}>
                      {tab.total_full_count && tab.total_full_count > (tab.row_count ?? tab.rows?.length ?? 0)
                        ? `${tab.row_count ?? tab.rows?.length ?? 0} / ${tab.total_full_count.toLocaleString('id-ID')}`
                        : (tab.row_count ?? tab.rows?.length ?? 0)}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* Executive KPI Metric Banner — Eksklusif untuk mode ringkasan/komparasi data agregat */}
        {!isRincianTransaksi && <KpiMetricBanner smartInsights={smartInsights} />}

        {/* Transaction Ledger Header — Untuk tabel rincian transaksi mentah */}
        {isRincianTransaksi && currentTab.total_full_count && (
          <div className="flex items-center justify-between text-xs px-3 py-2 bg-surface-card/60 border border-hairline rounded-md text-muted shadow-2xs">
            <span className="flex items-center gap-1.5 font-medium text-ink">
              <Table2 size={13} className="text-primary" />
              <span>Buku Transaksi ({currentTab.title || 'Rincian Transaksi'})</span>
            </span>
            <span className="font-mono text-[11px] text-muted">
              Menampilkan {activeRows.length} faktur sampel dari total {currentTab.total_full_count.toLocaleString('id-ID')} transaksi
            </span>
          </div>
        )}

        {/* Switcher Tab & Toolbar Aksi: Kombinasi vs Grafik vs Tabel Data */}
        {activeRows.length > 0 && (
          <div className="flex items-center justify-between pt-1 flex-wrap gap-2">
            <div className="flex items-center gap-2 flex-wrap">
              {grafikConfig.cocok && (
                <div className="flex items-center gap-1 bg-surface-card p-0.5 rounded-md border border-hairline">
                  <button
                    type="button"
                    onClick={() => setUserTabPreference('hybrid')}
                    title="Tampilkan grafik visual dan tabel data secara bertingkat"
                    className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium transition-colors cursor-pointer ${
                      activeTab === 'hybrid' ? 'bg-canvas shadow-xs text-primary font-medium border border-hairline' : 'text-muted hover:text-ink'
                    }`}
                  >
                    <Layers size={12} />
                    <span>Kombinasi</span>
                    {grafikConfig.shouldDefaultChart && userTabPreference === null && (
                      <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
                    )}
                  </button>
                  <button
                    type="button"
                    onClick={() => setUserTabPreference('chart')}
                    title="Hanya tampilkan grafik visual"
                    className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium transition-colors cursor-pointer ${
                      activeTab === 'chart' ? 'bg-canvas shadow-xs text-primary font-medium border border-hairline' : 'text-muted hover:text-ink'
                    }`}
                  >
                    <BarChart2 size={12} />
                    <span>Grafik</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setUserTabPreference('table')}
                    title="Hanya tampilkan tabel data"
                    className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium transition-colors cursor-pointer ${
                      activeTab === 'table' ? 'bg-canvas shadow-xs text-ink font-medium border border-hairline' : 'text-muted hover:text-ink'
                    }`}
                  >
                    <TableIcon size={12} />
                    <span>Tabel</span>
                  </button>
                </div>
              )}

              {/* Sub-toggle tipe chart jika di tab chart atau hybrid */}
              {grafikConfig.cocok && (activeTab === 'chart' || activeTab === 'hybrid') && (
                <div className="flex items-center gap-0.5 bg-surface-card p-0.5 rounded-md border border-hairline">
                  <button
                    type="button"
                    title="Grafik Batang (Bar)"
                    onClick={() => setChartType('bar')}
                    className={`p-1 rounded-md text-xs transition-colors cursor-pointer ${
                      chartType === 'bar' ? 'bg-canvas shadow-xs text-primary font-medium' : 'text-muted hover:text-ink'
                    }`}
                  >
                    <BarChart2 size={13} />
                  </button>
                  <button
                    type="button"
                    title="Grafik Garis Tren (Line)"
                    onClick={() => setChartType('line')}
                    className={`p-1 rounded-md text-xs transition-colors cursor-pointer ${
                      chartType === 'line' ? 'bg-canvas shadow-xs text-primary font-medium' : 'text-muted hover:text-ink'
                    }`}
                  >
                    <LineChartIcon size={13} />
                  </button>
                </div>
              )}

              {/* Tombol Unduh Excel Format Akuntansi (Fitur di-hold sementara sesuai arahan user) */}
              {showExportExcel && (
                <button
                  type="button"
                  onClick={handleExportExcel}
                  disabled={isExporting}
                  title="Unduh Spreadsheet Excel (.xlsx) Lengkap dengan Format Akuntansi & Grafik Asli"
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium bg-canvas hover:bg-surface-soft text-ink border border-hairline transition-colors shadow-2xs hover:shadow-xs cursor-pointer disabled:opacity-50"
                >
                  {isExporting ? (
                    <Loader2 size={12} className="animate-spin text-primary" />
                  ) : (
                    <FileSpreadsheet size={13} className="text-primary" />
                  )}
                  <span>{isExporting ? 'Mengekspor...' : 'Unduh Excel'}</span>
                </button>
              )}

              {/* Tombol Salin Tabel ke Clipboard */}
              <button
                type="button"
                onClick={handleCopyTable}
                title="Salin seluruh data tabel ke clipboard (format TSV/Excel)"
                className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium bg-canvas hover:bg-surface-soft text-ink border border-hairline transition-colors shadow-2xs hover:shadow-xs cursor-pointer"
              >
                {isCopied ? (
                  <Check size={13} className="text-emerald-700" />
                ) : (
                  <Copy size={13} className="text-muted" />
                )}
                <span>{isCopied ? 'Tersalin!' : 'Salin Tabel'}</span>
              </button>
            </div>
          </div>
        )}

        {/* Tampilan Konten: Grafik vs Tabel */}
        {activeRows.length === 0 ? (
          <div className="border border-dashed border-hairline rounded-lg px-4 py-6 text-center">
            <Database size={18} className="mx-auto text-muted/60 mb-1" aria-hidden="true" />
            <p className="text-sm text-body font-medium">Tidak ada data</p>
            <p className="text-xs text-muted mt-0.5">
              Query berjalan tanpa kesalahan tetapi tidak mengembalikan baris —
              coba ubah rentang waktu atau filter pertanyaan.
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {/* Visualisasi Grafik (Tampil jika mode 'hybrid' atau 'chart') */}
            {grafikConfig.cocok && (activeTab === 'hybrid' || activeTab === 'chart') && (
              <SilentChartErrorBoundary
                fallback={(
                  <p className="text-xs text-muted text-center py-4">
                    Grafik tidak dapat ditampilkan. Beralih ke tabel data.
                  </p>
                )}
              >
                <div className="border border-hairline rounded-lg p-3.5 bg-surface-card/30 shadow-2xs space-y-2">
                  <div className="flex items-center justify-between text-xs pb-1 border-b border-hairline">
                    <span className="font-medium text-ink flex items-center gap-1.5 font-sans">
                      <TrendingUp size={13} className="text-primary" />
                      {grafikConfig.title}
                    </span>
                    <span className="text-[10px] text-muted font-mono bg-canvas px-1.5 py-0.5 rounded-md border border-hairline">
                      {grafikConfig.chartData.length} data point
                    </span>
                  </div>
                  <div className="h-64 w-full pt-1">
                    <ResponsiveContainer width="100%" height="100%">
                      {chartType === 'line' ? (
                        <LineChart data={grafikConfig.chartData} margin={{ top: 10, right: 15, left: 10, bottom: 5 }}>
                          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e6dfd8" />
                          <XAxis
                            dataKey={grafikConfig.categoryCol}
                            tick={{ fontSize: 11, fill: '#6c6a64' }}
                            tickLine={{ stroke: '#e6dfd8' }}
                          />
                          <YAxis
                            width={85}
                            tickMargin={6}
                            tick={{ fontSize: 11, fill: '#6c6a64' }}
                            tickLine={{ stroke: '#e6dfd8' }}
                            tickFormatter={(val) => formatCompactAxis(val, grafikConfig.hasCurrencyCol)}
                          />
                          <Tooltip content={<CustomChartTooltip />} />
                          <Legend wrapperStyle={{ fontSize: '11px', paddingTop: '10px' }} />
                          {grafikConfig.valueCols.map((col, idx) => (
                            <Line
                              key={col}
                              type="monotone"
                              dataKey={col}
                              stroke={BAR_COLORS[idx % BAR_COLORS.length]}
                              strokeWidth={2.5}
                              dot={{ r: 3.5, strokeWidth: 1.5, fill: '#faf9f5' }}
                              activeDot={{ r: 6 }}
                            />
                          ))}
                        </LineChart>
                      ) : (
                        <BarChart data={grafikConfig.chartData} margin={{ top: 10, right: 15, left: 10, bottom: 5 }}>
                          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e6dfd8" />
                          <XAxis
                            dataKey={grafikConfig.categoryCol}
                            tick={{ fontSize: 11, fill: '#6c6a64' }}
                            tickLine={{ stroke: '#e6dfd8' }}
                          />
                          <YAxis
                            width={85}
                            tickMargin={6}
                            tick={{ fontSize: 11, fill: '#6c6a64' }}
                            tickLine={{ stroke: '#e6dfd8' }}
                            tickFormatter={(val) => formatCompactAxis(val, grafikConfig.hasCurrencyCol)}
                          />
                          <Tooltip content={<CustomChartTooltip />} />
                          <Legend wrapperStyle={{ fontSize: '11px', paddingTop: '10px' }} />
                          {grafikConfig.valueCols.map((col, idx) => (
                            <Bar
                              key={col}
                              dataKey={col}
                              fill={BAR_COLORS[idx % BAR_COLORS.length]}
                              radius={[3, 3, 0, 0]}
                              maxBarSize={44}
                            />
                          ))}
                        </BarChart>
                      )}
                    </ResponsiveContainer>
                  </div>
                </div>
              </SilentChartErrorBoundary>
            )}

            {/* Tabel Data (Tampil jika mode 'hybrid' atau 'table') */}
            {(activeTab === 'hybrid' || activeTab === 'table') && (
              <div className="space-y-2">
            {/* Filter pencarian cepat & pemilih limit per halaman jika data > 5 baris */}
            {activeRows.length > 5 && (
              <div className="flex items-center justify-between gap-2 pb-0.5 text-xs flex-wrap">
                <div className="relative flex-1 min-w-[180px] max-w-xs">
                  <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted" />
                  <input
                    type="text"
                    id="table-filter"
                    name="table-filter"
                    aria-label="Saring baris tabel"
                    placeholder="Saring baris tabel..."
                    value={tableSearch}
                    onChange={(e) => {
                      setTableSearch(e.target.value);
                      setTablePage(1);
                    }}
                    className="w-full pl-8 pr-3 py-1.5 text-xs bg-canvas border border-hairline rounded-md focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary text-ink placeholder:text-muted"
                  />
                  {tableSearch && (
                    <button
                      type="button"
                      onClick={() => setTableSearch('')}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-muted hover:text-ink cursor-pointer"
                    >
                      <X size={12} />
                    </button>
                  )}
                </div>
                <div className="flex items-center gap-1.5 text-muted ml-auto">
                  <span>Baris per halaman:</span>
                  <select
                    id="table-pagesize"
                    name="table-pagesize"
                    aria-label="Jumlah baris per halaman"
                    value={pageSize}
                    onChange={(e) => {
                      setPageSize(e.target.value === 'all' ? 'all' : Number(e.target.value));
                      setTablePage(1);
                    }}
                    className="bg-canvas border border-hairline rounded-md px-2 py-1 text-xs text-ink focus:outline-none cursor-pointer"
                  >
                    <option value={10}>10</option>
                    <option value={25}>25</option>
                    <option value={50}>50</option>
                    <option value="all">Semua ({activeRows.length})</option>
                  </select>
                </div>
              </div>
            )}

            <div className="border border-hairline rounded-lg overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-surface-card text-[11px] text-muted font-medium border-b border-hairline">
                  <tr>
                    {activeColumns.map((col, j) => {
                      const isSorted = sortCol === col;
                      const sampleCell = activeRows?.[0] ? (Array.isArray(activeRows[0]) ? activeRows[0][j] : activeRows[0][col]) : null;
                      const isNum = typeof sampleCell === 'number' || (!Number.isNaN(Number(sampleCell)) && sampleCell !== null && sampleCell !== '' && typeof sampleCell !== 'boolean');
                      return (
                        <th
                          key={col}
                          onClick={() => handleSort(col)}
                          className={`px-3 py-2 font-medium whitespace-nowrap cursor-pointer select-none hover:bg-surface-cream-strong/50 transition-colors ${
                            j === 0 ? 'sticky left-0 bg-surface-card z-10 shadow-[1px_0_0_0_rgba(0,0,0,0.08)]' : ''
                          } ${isNum ? 'text-right' : 'text-left'}`}
                          title={`Klik untuk mengurutkan data berdasarkan ${col}`}
                        >
                          <div className={`inline-flex items-center gap-1 ${isNum ? 'justify-end w-full' : ''}`}>
                            <span>{formatHeaderKolom(col)}</span>
                            {isSorted ? (
                              sortDir === 'asc' ? (
                                <ArrowUp size={12} className="text-primary" />
                              ) : (
                                <ArrowDown size={12} className="text-primary" />
                              )
                            ) : (
                              <ArrowUpDown size={11} className="text-muted/40 hover:text-muted" />
                            )}
                          </div>
                        </th>
                      );
                    })}
                  </tr>
                </thead>
                <tbody className="divide-y divide-hairline">
                  {paginatedRows.length === 0 ? (
                    <tr>
                      <td colSpan={activeColumns.length} className="px-3 py-4 text-center text-xs text-muted">
                        Tidak ada data yang cocok dengan pencarian "{tableSearch}".
                      </td>
                    </tr>
                  ) : (
                    paginatedRows.map((row, i) => {
                      const cells = Array.isArray(row) ? row : Object.values(row || {});
                      return (
                        <tr key={i} className="hover:bg-surface-card/40 transition-colors group">
                          {cells.map((cell, j) => {
                            const isDateOrTime = formatTanggalWaktu(cell) !== null;
                            const isNum = !isDateOrTime && (typeof cell === 'number' || (typeof cell === 'string' && cell.trim() !== '' && !Number.isNaN(Number(cell))));
                            return (
                              <td
                                key={j}
                                className={`px-3 py-2 whitespace-nowrap ${
                                  j === 0
                                    ? 'sticky left-0 bg-canvas group-hover:bg-surface-card z-10 shadow-[1px_0_0_0_rgba(0,0,0,0.08)] text-ink font-medium'
                                    : isNum
                                      ? 'text-right font-mono tabular-nums text-ink'
                                      : isDateOrTime
                                        ? 'text-left font-mono tabular-nums text-body'
                                        : 'text-body'
                                }`}
                              >
                                {formatSel(cell, activeColumns?.[j])}
                              </td>
                            );
                          })}
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>

            {/* Kontrol Paginasi */}
            {sortedRows.length > 0 && pageSize !== 'all' && (
              <div className="flex items-center justify-between text-xs text-muted pt-1 px-1">
                <span>
                  Menampilkan {Math.min((tablePage - 1) * pageSize + 1, sortedRows.length)}–
                  {Math.min(tablePage * pageSize, sortedRows.length)} dari {sortedRows.length} data
                  {currentTab.total_full_count && currentTab.total_full_count > activeRows.length && (
                    <span className="text-primary font-medium ml-1">
                      (Total: {currentTab.total_full_count.toLocaleString('id-ID')} transaksi)
                    </span>
                  )}
                  {filteredRows.length !== activeRows.length && ` (disaring dari ${activeRows.length})`}
                </span>
                {totalPages > 1 && (
                  <div className="flex items-center gap-1">
                    <button
                      type="button"
                      disabled={tablePage <= 1}
                      onClick={() => setTablePage((p) => Math.max(1, p - 1))}
                      className="p-1 rounded-md border border-hairline bg-canvas hover:bg-surface-soft disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer"
                      title="Halaman sebelumnya"
                    >
                      <ChevronLeft size={13} />
                    </button>
                    <span className="px-1.5 font-medium text-ink font-mono text-[11px]">
                      {tablePage} / {totalPages}
                    </span>
                    <button
                      type="button"
                      disabled={tablePage >= totalPages}
                      onClick={() => setTablePage((p) => Math.min(totalPages, p + 1))}
                      className="p-1 rounded-md border border-hairline bg-canvas hover:bg-surface-soft disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer"
                      title="Halaman berikutnya"
                    >
                      <ChevronRight size={13} />
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    )}

        {/* Peringatan hasil terpotong (row cap 500 di executor) */}
        {answer.truncated && (
          <p className="flex items-center gap-1.5 text-xs text-error">
            <AlertTriangle size={13} className="shrink-0" />
            Hasil dipotong pada {answer.row_count} baris — persempit pertanyaan
            untuk melihat sisanya.
          </p>
        )}


        {/* Meta info: baris + durasi + jam */}
        <p className="text-[11px] text-muted">
          {answer.row_count} baris{durasi && ` · ${durasi}`}
          {createdAt &&
            ` · ${new Date(createdAt).toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' })}`}
        </p>

        {/* Feedback (Human-in-the-Loop) */}
        {answer.memory_id && !memoryStatus && (onConfirm || onReject) && (
          <div className="flex items-center justify-between gap-2 pt-2 border-t border-hairline flex-wrap">
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted">Apakah jawaban ini benar?</span>
              {onConfirm && (
                <button
                  type="button"
                  onClick={onConfirm}
                  disabled={!!feedbackBusy}
                  className="inline-flex items-center gap-1 px-2.5 py-1 text-xs border border-hairline rounded-md text-success hover:bg-success/10 disabled:opacity-50 disabled:cursor-not-allowed transition-colors cursor-pointer"
                >
                  <Check size={13} />
                  Jawaban benar
                </button>
              )}
              {onReject && (
                <button
                  type="button"
                  onClick={onReject}
                  disabled={!!feedbackBusy}
                  className="inline-flex items-center gap-1 px-2.5 py-1 text-xs border border-hairline rounded-md text-error hover:bg-error/10 disabled:opacity-50 disabled:cursor-not-allowed transition-colors cursor-pointer"
                >
                  <X size={13} />
                  Jawaban salah
                </button>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Tawaran Proaktif Rincian Terpisah (Gaya 1 -> Gaya 2) - 100% Icon Lucide, Zero Emoji */}
      {breakdownSaran.length > 0 && onAsk && (
        <div className="rounded-lg border border-primary/20 bg-primary/5 p-3 sm:p-3.5 space-y-2.5 animate-fadeIn">
          <div className="flex items-center gap-2 text-xs font-medium text-primary">
            <SplitSquareVertical size={14} className="text-primary shrink-0" />
            <span>Ingin melihat data transaksi masing-masing periode secara terpisah?</span>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            {breakdownSaran.map((s, idx) => (
              <button
                key={`${s}-${idx}`}
                type="button"
                onClick={() => onAsk(s)}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium border border-primary/30 rounded-md bg-canvas text-ink hover:bg-primary/10 hover:border-primary text-left transition-all cursor-pointer shadow-2xs group"
              >
                {s.toLowerCase().includes('terpisah') ? (
                  <SplitSquareVertical size={12} className="text-primary group-hover:scale-105 transition-transform shrink-0" />
                ) : (
                  <ArrowRight size={12} className="text-primary group-hover:translate-x-0.5 transition-transform shrink-0" />
                )}
                <span>{s}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Saran pertanyaan lanjutan kontekstual reguler (Zero Emoji) */}
      {regularSaran.length > 0 && (
        <div className="space-y-1.5 pt-1">
          <p className="text-[11px] text-muted flex items-center gap-1.5 font-medium">
            <Compass size={12} className="text-primary" />
            <span>Rekomendasi eksplorasi data selanjutnya:</span>
          </p>
          <div className="flex items-center gap-1.5 flex-wrap">
            {regularSaran.map((s, idx) => (
              <button
                key={`${s}-${idx}`}
                type="button"
                onClick={() => onAsk(s)}
                className="px-2.5 py-1 text-xs border border-hairline rounded-md bg-canvas text-body hover:bg-surface-soft hover:border-primary/40 hover:text-ink transition-colors cursor-pointer text-left shadow-2xs"
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
