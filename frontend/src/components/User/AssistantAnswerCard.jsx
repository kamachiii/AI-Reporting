import { Component, useMemo, useState } from 'react';
import {
  AlertTriangle, Check, ChevronDown, ChevronRight, ChevronLeft, Database, Layers, X,
  BarChart2, LineChart as LineChartIcon, Table as TableIcon, Loader2, GraduationCap,
  TrendingUp, TrendingDown, Lightbulb, Compass, Award,
  Car, Wrench, Package, FileSpreadsheet, ArrowUpDown, ArrowUp, ArrowDown, Copy, Search,
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

const UANG_KEYWORDS = [
  'harga', 'omzet', 'omset', 'beli', 'jual', 'biaya', 'uang', 'dpp', 'ppn',
  'nominal', 'saldo', 'total_pembelian', 'total_penjualan', 'total_nilai',
  'hpunit', 'hpdpp', 'hpppn', 'hppbm', 'tarif', 'subtotal', 'diskon',
  'selisih', 'laba', 'rugi', 'profit', 'margin', 'pendapatan', 'piutang', 'hutang',
  'nilai_transaksi',
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
  'nilai_transaksi',
];

function isKolomUang(colName) {
  if (!colName) return false;
  const col = String(colName).toLowerCase();
  if (EKSPLISIT_UANG.some((k) => col.includes(k))) return true;
  if (KUANTITAS_KEYWORDS.some((k) => col.includes(k))) return false;
  return UANG_KEYWORDS.some((k) => col.includes(k));
}

/** Bersihkan notasi ilmiah dan angka di teks ringkasan agar rapi dengan format Rp. */
function bersihkanRingkasan(teks) {
  if (!teks) return '';
  return teks.replace(/([a-zA-Z0-9_]+:\s*)([+-]?\d+(?:\.\d+)?[eE][+-]?\d+|[+-]?\d+)/g, (match, prefix, numStr) => {
    const num = Number(numStr);
    if (Number.isNaN(num)) return match;
    const isUang = isKolomUang(prefix);
    const isPersen = prefix.toLowerCase().includes('persen') || prefix.toLowerCase().includes('pct');
    const formatted = new Intl.NumberFormat('id-ID', { maximumFractionDigits: 2 }).format(Math.abs(Math.round(num)));
    if (isUang) {
      return `${prefix}${num < 0 ? '-Rp ' : 'Rp '}${formatted}`;
    }
    if (isPersen) {
      return `${prefix}${num < 0 ? '-' : ''}${formatted}%`;
    }
    return `${prefix}${num < 0 ? '-' : ''}${formatted}`;
  });
}

/** Sel tabel: null/undefined tampil sebagai garis, angka dan uang diformat id-ID rapi. */
function formatSel(nilai, colName = '') {
  if (nilai === null || nilai === undefined) return '—';
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

/** Format narasi analisis eksekutif agar terstruktur rapi, tidak menjadi semut berbaris. */
function FormattedExecutiveAnalysis({ text }) {
  if (!text) return null;

  // Pisahkan teks berdasarkan baris baru ganda bila ada
  let paragraphs = text
    .split(/\n\n+/)
    .map((p) => p.trim())
    .filter(Boolean);

  // Jika AI mengembalikan 1 paragraf panjang tanpa \n\n (teks padat berbaris):
  if (paragraphs.length === 1 && paragraphs[0].length > 160) {
    const splitRegex = /(?=\b(?:Namun,|Jika angka nol|Jika hanya masalah|Jika benar tidak|Langkah pertama|Rekomendasi:)\b)/g;
    const parts = paragraphs[0].split(splitRegex).map((p) => p.trim()).filter(Boolean);
    if (parts.length > 1) {
      paragraphs = parts;
    }
  }

  return (
    <div className="space-y-3 text-sm text-body leading-relaxed font-sans">
      {paragraphs.map((para, idx) => {
        const isRekomendasi = /^Rekomendasi:/i.test(para);
        const isList = para.split('\n').some((l) => /^[•\-*]|\d+\.\s/.test(l.trim()));

        if (isRekomendasi) {
          const rawContent = para.replace(/^Rekomendasi:\s*/i, '');
          const bulletItems = rawContent
            .split(/(?:\r?\n|(?<=[^\s])\s*•|\s+•\s+)/)
            .map((b) => b.replace(/^[•\-*]\s*/, '').trim())
            .filter(Boolean);

          return (
            <div
              key={idx}
              className="p-4 rounded-md bg-primary/5 border-l-2 border-primary border-y border-r border-hairline/60 space-y-2.5 mt-2"
            >
              <div className="text-xs font-semibold text-primary uppercase tracking-wider flex items-center gap-1.5">
                <Compass size={13} />
                <span>Rekomendasi Tindakan Strategis</span>
              </div>
              {bulletItems.length > 1 ? (
                <ul className="space-y-1.5 pl-0.5">
                  {bulletItems.map((item, bIdx) => (
                    <li key={bIdx} className="flex items-start gap-2 text-sm text-ink">
                      <span className="w-1.5 h-1.5 rounded-full bg-primary shrink-0 mt-2" />
                      <span className="leading-relaxed">{item}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-ink text-sm leading-relaxed">{rawContent}</p>
              )}
            </div>
          );
        }

        if (isList) {
          const lines = para.split('\n').map((l) => l.trim()).filter(Boolean);
          return (
            <ul key={idx} className="space-y-1.5 pl-1">
              {lines.map((line, lIdx) => {
                const cleaned = line.replace(/^[•\-*]\s*|\d+\.\s*/, '');
                return (
                  <li key={lIdx} className="flex items-start gap-2 text-sm text-body">
                    <span className="w-1.5 h-1.5 rounded-full bg-primary/70 shrink-0 mt-2" />
                    <span>{cleaned}</span>
                  </li>
                );
              })}
            </ul>
          );
        }

        return (
          <p key={idx} className="text-body leading-relaxed">
            {para}
          </p>
        );
      })}
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
  const [tampilSql, setTampilSql] = useState(false);
  const [userTabPreference, setUserTabPreference] = useState(null); // 'table' | 'chart' | null
  const [chartType, setChartType] = useState('bar'); // 'bar' | 'line'
  const [penjelasan, setPenjelasan] = useState(null);
  const [loadingExplain, setLoadingExplain] = useState(false);
  const [trainingBusy, setTrainingBusy] = useState(false);
  const [trained, setTrained] = useState(false);
  const [activeDomainTab, setActiveDomainTab] = useState(0);
  const [isExporting, setIsExporting] = useState(false);
  const [tableSearch, setTableSearch] = useState('');
  const [sortCol, setSortCol] = useState(null);
  const [sortDir, setSortDir] = useState('asc');
  const [tablePage, setTablePage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [isCopied, setIsCopied] = useState(false);
  const [isSqlCopied, setIsSqlCopied] = useState(false);

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

  const smartInsights = useMemo(
    () => hitungSmartInsights(activeColumns, activeRows),
    [activeColumns, activeRows]
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
    return (rawSaran || [])
      .filter((s) => {
        if (!s || typeof s !== 'string') return false;
        const sLower = s.toLowerCase().trim();
        return sLower !== curQ && !sLower.includes(curQ) && !curQ.includes(sLower);
      })
      .slice(0, 3);
  }, [ditolak, onAsk, answer.saran, question, answer.question, activeColumns, activeRows, activeSql]);

  const grafikConfig = useMemo(
    () => deteksiKecocokanGrafik(activeColumns, activeRows),
    [activeColumns, activeRows]
  );

  const activeTab = (userTabPreference !== null)
    ? (userTabPreference === 'chart' && !grafikConfig.cocok ? 'table' : userTabPreference)
    : (grafikConfig.shouldDefaultChart ? 'chart' : 'table');

  const handleExplain = async () => {
    if (loadingExplain || !branchCode) return;
    setLoadingExplain(true);
    try {
      const qText = (question || answer.question || 'Analisis data transaksi').trim() || 'Analisis data transaksi';
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

  const handleTrain = async () => {
    if (trainingBusy || trained || !branchCode) return;
    setTrainingBusy(true);
    try {
      await api.trainVanna({
        branchCode,
        question: question || answer.question || '',
        sql: activeSql,
      });
      setTrained(true);
      toast.success('Jawaban berhasil dilatih ke AI (pgvector)!');
    } catch {
      toast.error('Gagal melatih AI.');
    } finally {
      setTrainingBusy(false);
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
      return cells.map((c) => (c === null || c === undefined ? '' : String(c))).join('\t');
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

            <span className="text-[11px] text-muted font-mono bg-surface-card px-2 py-0.5 rounded-md border border-hairline">
              Keyakinan: <strong className="text-ink">{answer.confidence || 'B'}</strong>
            </span>
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
            <p className="font-sans text-sm sm:text-[15px] leading-relaxed text-ink font-medium">
              {bersihkanRingkasan(answer.ringkasan)}
            </p>
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

        {/* Domain Tab Bar (Pilar 3S Multi-Table) - HANYA tampil jika minimal 2 tabel memiliki data */}
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
                     <Layers size={13} />}
                    <span>{tab.title}</span>
                    <span className={`px-1.5 py-0.2 rounded-full text-[10px] ${
                      isActive ? 'bg-primary/10 text-primary' : 'bg-surface-card text-muted'
                    }`}>
                      {tab.row_count ?? tab.rows?.length ?? 0}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* Ringkasan Indikator Statistik Data */}
        {smartInsights.hasInsights && (
          <div className="bg-surface-card/60 border border-hairline rounded-lg p-3 space-y-2 text-xs">
            <div className="flex items-center justify-between text-muted text-[11px]">
              <span className="inline-flex items-center gap-1.5 font-medium text-ink tracking-wide">
                <Lightbulb size={13} className="text-primary" />
                <span>Indikator Statistik Utama</span>
              </span>
              <span className="font-mono tabular-nums text-muted">{smartInsights.jumlahData} baris data</span>
            </div>

            <div className="flex items-center gap-2 flex-wrap text-xs">
              {smartInsights.deltaPersen !== null && (
                <div
                  className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md border text-xs font-medium tabular-nums ${
                    smartInsights.arahTren === 'naik'
                      ? 'bg-emerald-50/80 text-emerald-800 border-emerald-200/80'
                      : smartInsights.arahTren === 'turun'
                        ? 'bg-rose-50/80 text-rose-800 border-rose-200/80'
                        : 'bg-canvas text-body border-hairline'
                  }`}
                >
                  {smartInsights.arahTren === 'naik' ? (
                    <TrendingUp size={12} />
                  ) : smartInsights.arahTren === 'turun' ? (
                    <TrendingDown size={12} />
                  ) : null}
                  <span>
                    Tren {Number(smartInsights.deltaPersen) > 0 ? `+${smartInsights.deltaPersen}%` : `${smartInsights.deltaPersen}%`}
                  </span>
                </div>
              )}

              {smartInsights.tertinggi && (
                <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-canvas border border-hairline text-body">
                  <Award size={12} className="text-primary shrink-0" />
                  <span className="truncate max-w-[240px]">
                    Tertinggi: <strong className="font-semibold text-ink">{smartInsights.tertinggi.label}</strong> (<span className="font-mono tabular-nums">{smartInsights.tertinggi.nilaiFormatted}</span>)
                  </span>
                </div>
              )}

              {smartInsights.totalFormatted && (
                <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-canvas border border-hairline text-muted">
                  <span>Total: <strong className="text-ink font-mono tabular-nums">{smartInsights.totalFormatted}</strong></span>
                </div>
              )}

              {smartInsights.rataRataFormatted && (
                <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-canvas border border-hairline text-muted">
                  <span>Rata-rata: <strong className="text-ink font-mono tabular-nums">{smartInsights.rataRataFormatted}</strong></span>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Switcher Tab & Toolbar Aksi: Tabel Data vs Grafik Otomatis vs Unduh Excel */}
        {activeRows.length > 0 && (
          <div className="flex items-center justify-between pt-1 flex-wrap gap-2">
            <div className="flex items-center gap-2 flex-wrap">
              {grafikConfig.cocok && (
                <div className="flex items-center gap-1 bg-surface-card p-0.5 rounded-md border border-hairline">
                  <button
                    type="button"
                    onClick={() => setUserTabPreference('table')}
                    className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium transition-colors cursor-pointer ${
                      activeTab === 'table' ? 'bg-canvas shadow-xs text-ink font-medium border border-hairline' : 'text-muted hover:text-ink'
                    }`}
                  >
                    <TableIcon size={12} />
                    <span>Tabel Data</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setUserTabPreference('chart')}
                    className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium transition-colors cursor-pointer ${
                      activeTab === 'chart' ? 'bg-canvas shadow-xs text-primary font-medium border border-hairline' : 'text-muted hover:text-ink'
                    }`}
                  >
                    <BarChart2 size={12} />
                    <span>Grafik Visual</span>
                    {grafikConfig.shouldDefaultChart && userTabPreference === null && (
                      <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
                    )}
                  </button>
                </div>
              )}

              {/* Sub-toggle tipe chart jika di tab chart */}
              {grafikConfig.cocok && activeTab === 'chart' && (
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

              {/* Tombol Unduh Excel Format Akuntansi */}
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
        ) : activeTab === 'chart' && grafikConfig.cocok ? (
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
                    <LineChart data={grafikConfig.chartData} margin={{ top: 10, right: 15, left: 5, bottom: 5 }}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e6dfd8" />
                      <XAxis
                        dataKey={grafikConfig.categoryCol}
                        tick={{ fontSize: 11, fill: '#6c6a64' }}
                        tickLine={{ stroke: '#e6dfd8' }}
                      />
                      <YAxis
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
                    <BarChart data={grafikConfig.chartData} margin={{ top: 10, right: 15, left: 5, bottom: 5 }}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e6dfd8" />
                      <XAxis
                        dataKey={grafikConfig.categoryCol}
                        tick={{ fontSize: 11, fill: '#6c6a64' }}
                        tickLine={{ stroke: '#e6dfd8' }}
                      />
                      <YAxis
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
        ) : (
          <div className="space-y-2">
            {/* Filter pencarian cepat & pemilih limit per halaman jika data > 5 baris */}
            {activeRows.length > 5 && (
              <div className="flex items-center justify-between gap-2 pb-0.5 text-xs flex-wrap">
                <div className="relative flex-1 min-w-[180px] max-w-xs">
                  <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted" />
                  <input
                    type="text"
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
                            isNum ? 'text-right' : 'text-left'
                          }`}
                          title={`Klik untuk mengurutkan data berdasarkan ${col}`}
                        >
                          <div className={`inline-flex items-center gap-1 ${isNum ? 'justify-end w-full' : ''}`}>
                            <span>{col}</span>
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
                        <tr key={i} className="hover:bg-surface-card/40 transition-colors">
                          {cells.map((cell, j) => {
                            const isNum = typeof cell === 'number' || (typeof cell === 'string' && cell.trim() !== '' && !Number.isNaN(Number(cell)));
                            return (
                              <td
                                key={j}
                                className={`px-3 py-2 whitespace-nowrap ${
                                  isNum ? 'text-right font-mono tabular-nums text-ink' : (j === 0 ? 'text-ink font-medium' : 'text-body')
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

        {/* Peringatan hasil terpotong (row cap 500 di executor) */}
        {answer.truncated && (
          <p className="flex items-center gap-1.5 text-xs text-error">
            <AlertTriangle size={13} className="shrink-0" />
            Hasil dipotong pada {answer.row_count} baris — persempit pertanyaan
            untuk melihat sisanya.
          </p>
        )}

        {/* SQL Window Card - Signature Claude Artifact Aesthetic */}
        <div className="pt-1">
          <button
            type="button"
            onClick={() => setTampilSql((v) => !v)}
            className="inline-flex items-center gap-1.5 text-xs text-muted hover:text-ink transition-colors cursor-pointer"
            aria-expanded={tampilSql}
          >
            {tampilSql ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
            <span className="font-mono text-[11px]">
              {isMultiTab ? `SQL Query (${currentTab.title || 'Tab Aktif'})` : 'SQL Query'}
            </span>
          </button>
          {tampilSql && (
            <div className="mt-2 bg-surface-dark border border-hairline/20 rounded-lg overflow-hidden shadow-xs">
              {/* Window Header */}
              <div className="flex items-center justify-between px-3 py-2 bg-surface-dark-soft border-b border-hairline/15 text-xs">
                <div className="flex items-center gap-2">
                  <div className="flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-full bg-[#ff5f57]/80 inline-block" />
                    <span className="w-2.5 h-2.5 rounded-full bg-[#febc2e]/80 inline-block" />
                    <span className="w-2.5 h-2.5 rounded-full bg-[#28c840]/80 inline-block" />
                  </div>
                  <span className="font-mono text-[11px] text-muted-soft pl-1.5 border-l border-hairline/20">
                    query.sql
                  </span>
                </div>
                <button
                  type="button"
                  onClick={() => {
                    navigator.clipboard.writeText(activeSql);
                    setIsSqlCopied(true);
                    toast.success('SQL disalin ke clipboard');
                    setTimeout(() => setIsSqlCopied(false), 2000);
                  }}
                  className="inline-flex items-center gap-1 text-[11px] font-mono text-muted-soft hover:text-on-dark transition-colors cursor-pointer"
                  title="Salin SQL"
                >
                  {isSqlCopied ? <Check size={11} className="text-emerald-400" /> : <Copy size={11} />}
                  <span>{isSqlCopied ? 'Tersalin' : 'Salin'}</span>
                </button>
              </div>
              {/* Code Body */}
              <pre className="p-3.5 text-[11px] leading-relaxed font-mono text-[#f5f4ef] overflow-x-auto whitespace-pre-wrap break-words bg-surface-dark">
                {activeSql}
              </pre>
            </div>
          )}
        </div>

        {/* Meta info: baris + durasi + jam */}
        <p className="text-[11px] text-muted">
          {answer.row_count} baris{durasi && ` · ${durasi}`}
          {answer.attempts > 1 && ` · ${answer.attempts} percobaan`}
          {createdAt &&
            ` · ${new Date(createdAt).toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' })}`}
        </p>

        {/* Feedback & Instant Training (Human-in-the-Loop) */}
        <div className="flex items-center justify-between gap-2 pt-2 border-t border-hairline flex-wrap">
          {answer.memory_id && !memoryStatus && (onConfirm || onReject) ? (
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
          ) : (
            <div />
          )}

          {/* Tombol Latih AI Instan */}
          {branchCode && answer.sql && (
            <button
              type="button"
              onClick={handleTrain}
              disabled={trainingBusy || trained}
              className={`inline-flex items-center gap-1.5 px-2.5 py-1 text-xs border border-hairline rounded-md transition-colors cursor-pointer ${
                trained
                  ? 'bg-success/10 text-success border-success/30'
                  : 'text-muted hover:text-primary hover:bg-primary/5'
              } disabled:opacity-50`}
            >
              {trainingBusy ? <Loader2 size={12} className="animate-spin" /> : <GraduationCap size={12} />}
              {trained ? 'Telah Dilatih ke AI' : 'Latih Jawaban Ini'}
            </button>
          )}
        </div>
      </div>

      {/* Saran pertanyaan lanjutan kontekstual */}
      {smartSaran.length > 0 && (
        <div className="space-y-1.5 pt-1">
          <p className="text-[11px] text-muted flex items-center gap-1.5 font-medium">
            <Compass size={12} className="text-primary" />
            <span>Rekomendasi eksplorasi data selanjutnya:</span>
          </p>
          <div className="flex items-center gap-1.5 flex-wrap">
            {smartSaran.map((s) => (
              <button
                key={s}
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
