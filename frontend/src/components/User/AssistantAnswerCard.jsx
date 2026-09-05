import { Component, useMemo, useState } from 'react';
import {
  AlertTriangle, Check, ChevronDown, ChevronRight, Database, Layers, Sparkles, X, Zap,
  BarChart2, LineChart as LineChartIcon, Table as TableIcon, Loader2, GraduationCap,
  TrendingUp, TrendingDown, Lightbulb, Compass, Award,
  Car, Wrench, Package,
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
  'nilai_transaksi', 'total_transaksi',
];

// Kolom yang pasti kuantitas / hitungan unit — BUKAN uang
const KUANTITAS_KEYWORDS = [
  'jumlah', 'qty', 'count', 'cnt', 'banyak', 'total_unit', 'unit_terjual',
  'frekuensi', 'freq', 'banyaknya', 'nomor', 'kode',
];

// Pengecualian: kolom yang mengandung kata 'jumlah' / 'total' tapi eksplisit uang
const EKSPLISIT_UANG = [
  'jumlah_nominal', 'jumlah_uang', 'jumlah_biaya', 'jumlah_rupiah', 'jumlah_rp',
  'total_nominal', 'total_biaya', 'total_rupiah', 'total_rp', 'total_nilai',
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
    const isUang = isKolomUang(colName) || (isPeriodeMusiman && isNominalBesar);

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

const BAR_COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#f43f5e', '#06b6d4'];

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
      <div className="bg-white border border-hairline rounded-lg p-2.5 shadow-lg text-xs space-y-1 z-50">
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

  const isMultiTab = Boolean(answer.is_multi_tab && Array.isArray(answer.tabs) && answer.tabs.length > 1);
  const currentTab = (isMultiTab && answer.tabs[activeDomainTab]) ? answer.tabs[activeDomainTab] : answer;

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
    if (Array.isArray(answer.saran) && answer.saran.length > 0) return answer.saran;
    return buatRekomendasiPertanyaan(
      question || answer.question || '',
      activeColumns,
      activeRows,
      activeSql
    );
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

  return (
    <>
      <div className="bg-white border border-hairline rounded-xl rounded-tl-md shadow-sm p-4 space-y-3">
        {/* Badge sumber + level keyakinan */}
        <div className="flex items-center gap-2 flex-wrap">
          {terverifikasi ? (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-success/10 text-success text-[11px] font-medium">
              <Check size={11} />
              Memori (terverifikasi)
            </span>
          ) : ditolak ? (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-surface-soft text-muted text-[11px] font-medium">
              <X size={11} />
              Ditolak
            </span>
          ) : answer.source === 'vanna' ? (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-surface-card text-ink border border-hairline text-[11px] font-medium">
              <Zap size={11} className="text-muted" />
              Mode Vanna (pgvector)
            </span>
          ) : answer.source === 'tier2' ? (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-surface-card text-ink text-[11px] font-medium">
              <Layers size={11} />
              SQL Kompleks (Level C)
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-primary/10 text-primary text-[11px] font-medium">
              <Sparkles size={11} />
              Jawaban baru
            </span>
          )}
          <span className="px-2 py-0.5 rounded-full border border-hairline text-muted text-[11px]">
            Keyakinan {answer.confidence}
          </span>
        </div>

        {/* Ringkasan naratif / ringkasan otomatis */}
        {answer.ringkasan && (
          <p className="border-l-2 border-primary/40 pl-3 font-serif italic text-[15px] leading-relaxed text-ink">
            {bersihkanRingkasan(answer.ringkasan)}
          </p>
        )}

        {/* Tombol On-Demand Explain (Mode Operasional) */}
        {answer.allow_explain && !penjelasan && (
          <div className="pt-0.5">
            <button
              type="button"
              onClick={handleExplain}
              disabled={loadingExplain}
              className="inline-flex items-center gap-1.5 px-3 py-1 text-xs font-medium border border-primary/30 rounded-lg text-primary bg-primary/5 hover:bg-primary/10 transition-colors disabled:opacity-50 cursor-pointer"
            >
              {loadingExplain ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
              {loadingExplain ? 'Menganalisis data mendalam...' : 'Jelaskan Lebih Dalam dengan AI'}
            </button>
          </div>
        )}

        {/* Hasil Narasi Analisis Eksekutif On-Demand */}
        {penjelasan && (
          <div className="bg-surface-soft border border-hairline rounded-lg p-3 text-xs leading-relaxed text-ink space-y-1.5 animate-fadeIn">
            <div className="flex items-center gap-1.5 text-primary font-medium text-[11px] uppercase tracking-wider">
              <Sparkles size={12} />
              <span>Analisis Eksekutif AI</span>
            </div>
            <p className="whitespace-pre-wrap text-body font-sans">{penjelasan}</p>
          </div>
        )}

        {/* Domain Tab Bar (Pilar 3S Multi-Table) */}
        {isMultiTab && (
          <div className="pt-1">
            <div className="flex items-center gap-1.5 p-1 bg-surface-soft/80 rounded-xl border border-hairline overflow-x-auto">
              {answer.tabs.map((tab, idx) => {
                const isActive = activeDomainTab === idx;
                return (
                  <button
                    key={tab.id || idx}
                    type="button"
                    onClick={() => {
                      setActiveDomainTab(idx);
                    }}
                    className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-all cursor-pointer whitespace-nowrap ${
                      isActive
                        ? 'bg-white shadow-xs text-primary font-semibold border border-hairline'
                        : 'text-muted hover:text-ink hover:bg-white/50'
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

        {/* Smart Insights (Zero-Token Analisis Matematis) */}
        {smartInsights.hasInsights && (
          <div className="bg-canvas border border-hairline rounded-lg p-2.5 space-y-2 text-xs">
            <div className="flex items-center justify-between text-muted text-[11px]">
              <span className="inline-flex items-center gap-1 font-medium text-ink">
                <Lightbulb size={13} className="text-amber-500" />
                Smart Insight (Zero-Token)
              </span>
              <span>{smartInsights.jumlahData} data dianalisis</span>
            </div>

            <div className="flex items-center gap-2 flex-wrap text-xs">
              {smartInsights.deltaPersen !== null && (
                <div
                  className={`inline-flex items-center gap-1 px-2 py-1 rounded-md border font-medium ${
                    smartInsights.arahTren === 'naik'
                      ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                      : smartInsights.arahTren === 'turun'
                        ? 'bg-rose-50 text-rose-700 border-rose-200'
                        : 'bg-surface-soft text-body border-hairline'
                  }`}
                >
                  {smartInsights.arahTren === 'naik' ? (
                    <TrendingUp size={13} />
                  ) : smartInsights.arahTren === 'turun' ? (
                    <TrendingDown size={13} />
                  ) : null}
                  <span>
                    Tren: {Number(smartInsights.deltaPersen) > 0 ? `+${smartInsights.deltaPersen}%` : `${smartInsights.deltaPersen}%`}
                  </span>
                </div>
              )}

              {smartInsights.tertinggi && (
                <div className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-surface-soft/80 border border-hairline text-body">
                  <Award size={13} className="text-amber-600 shrink-0" />
                  <span className="truncate max-w-[240px]">
                    Tertinggi: <strong className="font-semibold text-ink">{smartInsights.tertinggi.label}</strong> ({smartInsights.tertinggi.nilaiFormatted})
                  </span>
                </div>
              )}

              {smartInsights.totalFormatted && (
                <div className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-surface-soft/80 border border-hairline text-muted">
                  <span>Total: <strong className="text-ink">{smartInsights.totalFormatted}</strong></span>
                </div>
              )}

              {smartInsights.rataRataFormatted && (
                <div className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-surface-soft/80 border border-hairline text-muted">
                  <span>Rata-rata: <strong className="text-ink">{smartInsights.rataRataFormatted}</strong></span>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Switcher Tab: Tabel Data vs Grafik Otomatis (0 token) */}
        {grafikConfig.cocok && activeRows.length > 0 && (
          <div className="flex items-center justify-between pt-1 flex-wrap gap-2">
            <div className="flex items-center gap-1.5">
              <div className="flex items-center gap-1 bg-surface-soft p-0.5 rounded-lg border border-hairline">
                <button
                  type="button"
                  onClick={() => setUserTabPreference('table')}
                  className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium transition-colors cursor-pointer ${
                    activeTab === 'table' ? 'bg-white shadow-xs text-ink font-semibold border border-hairline' : 'text-muted hover:text-ink'
                  }`}
                >
                  <TableIcon size={12} />
                  <span>Tabel Data</span>
                </button>
                <button
                  type="button"
                  onClick={() => setUserTabPreference('chart')}
                  className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium transition-colors cursor-pointer ${
                    activeTab === 'chart' ? 'bg-white shadow-xs text-primary font-semibold border border-hairline' : 'text-muted hover:text-ink'
                  }`}
                >
                  <BarChart2 size={12} />
                  <span>Grafik Visual</span>
                  {grafikConfig.shouldDefaultChart && userTabPreference === null && (
                    <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
                  )}
                </button>
              </div>

              {/* Sub-toggle tipe chart jika di tab chart */}
              {activeTab === 'chart' && (
                <div className="flex items-center gap-0.5 bg-surface-soft/80 p-0.5 rounded-md border border-hairline">
                  <button
                    type="button"
                    title="Grafik Batang (Bar)"
                    onClick={() => setChartType('bar')}
                    className={`p-1 rounded text-xs transition-colors cursor-pointer ${
                      chartType === 'bar' ? 'bg-white shadow-xs text-primary font-semibold' : 'text-muted hover:text-ink'
                    }`}
                  >
                    <BarChart2 size={13} />
                  </button>
                  <button
                    type="button"
                    title="Grafik Garis Tren (Line)"
                    onClick={() => setChartType('line')}
                    className={`p-1 rounded text-xs transition-colors cursor-pointer ${
                      chartType === 'line' ? 'bg-white shadow-xs text-primary font-semibold' : 'text-muted hover:text-ink'
                    }`}
                  >
                    <LineChartIcon size={13} />
                  </button>
                </div>
              )}
            </div>

            <span className="text-[11px] text-muted flex items-center gap-1">
              <Sparkles size={11} className="text-primary" />
              <span>{grafikConfig.title} (0 Token)</span>
            </span>
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
            <div className="border border-hairline rounded-xl p-3.5 bg-surface-soft/30 shadow-xs space-y-2">
              <div className="flex items-center justify-between text-xs pb-1 border-b border-hairline">
                <span className="font-semibold text-ink flex items-center gap-1.5">
                  <TrendingUp size={13} className="text-primary" />
                  {grafikConfig.title}
                </span>
                <span className="text-[10px] text-muted font-mono bg-canvas px-1.5 py-0.5 rounded border border-hairline">
                  {grafikConfig.chartData.length} data point
                </span>
              </div>
              <div className="h-72 w-full pt-1">
                <ResponsiveContainer width="100%" height="100%">
                  {chartType === 'line' ? (
                    <LineChart data={grafikConfig.chartData} margin={{ top: 10, right: 15, left: 5, bottom: 5 }}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                      <XAxis
                        dataKey={grafikConfig.categoryCol}
                        tick={{ fontSize: 11, fill: '#64748b' }}
                        tickLine={{ stroke: '#cbd5e1' }}
                      />
                      <YAxis
                        tick={{ fontSize: 11, fill: '#64748b' }}
                        tickLine={{ stroke: '#cbd5e1' }}
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
                          dot={{ r: 3.5, strokeWidth: 1.5, fill: '#ffffff' }}
                          activeDot={{ r: 6 }}
                        />
                      ))}
                    </LineChart>
                  ) : (
                    <BarChart data={grafikConfig.chartData} margin={{ top: 10, right: 15, left: 5, bottom: 5 }}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                      <XAxis
                        dataKey={grafikConfig.categoryCol}
                        tick={{ fontSize: 11, fill: '#64748b' }}
                        tickLine={{ stroke: '#cbd5e1' }}
                      />
                      <YAxis
                        tick={{ fontSize: 11, fill: '#64748b' }}
                        tickLine={{ stroke: '#cbd5e1' }}
                        tickFormatter={(val) => formatCompactAxis(val, grafikConfig.hasCurrencyCol)}
                      />
                      <Tooltip content={<CustomChartTooltip />} />
                      <Legend wrapperStyle={{ fontSize: '11px', paddingTop: '10px' }} />
                      {grafikConfig.valueCols.map((col, idx) => (
                        <Bar
                          key={col}
                          dataKey={col}
                          fill={BAR_COLORS[idx % BAR_COLORS.length]}
                          radius={[4, 4, 0, 0]}
                          maxBarSize={48}
                        />
                      ))}
                    </BarChart>
                  )}
                </ResponsiveContainer>
              </div>
            </div>
          </SilentChartErrorBoundary>
        ) : (
          <div className="border border-hairline rounded-lg overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-surface-soft text-xs text-muted">
                <tr>
                  {activeColumns.map((col) => (
                    <th key={col} className="px-3 py-2 font-medium whitespace-nowrap">
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-hairline">
                {activeRows.map((row, i) => {
                  const cells = Array.isArray(row) ? row : Object.values(row || {});
                  return (
                    <tr key={i} className="hover:bg-surface-soft/50 transition-colors">
                      {cells.map((cell, j) => (
                        <td
                          key={j}
                          className={`px-3 py-2 whitespace-nowrap ${j === 0 ? 'text-ink font-medium' : 'text-body'}`}
                        >
                          {formatSel(cell, activeColumns?.[j])}
                        </td>
                      ))}
                    </tr>
                  );
                })}
              </tbody>
            </table>
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

        {/* SQL disertakan apa adanya (kejujuran UI) */}
        <div>
          <button
            type="button"
            onClick={() => setTampilSql((v) => !v)}
            className="inline-flex items-center gap-1 text-xs text-muted hover:text-ink transition-colors cursor-pointer"
            aria-expanded={tampilSql}
          >
            {tampilSql ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
            {isMultiTab ? `Lihat SQL (${currentTab.title || 'Tab Aktif'})` : 'Lihat SQL'}
          </button>
          {tampilSql && (
            <pre className="mt-1.5 bg-canvas border border-hairline rounded-lg p-3 text-[11px] leading-relaxed font-mono text-body overflow-x-auto whitespace-pre-wrap break-words">
              {activeSql}
            </pre>
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

      {/* Saran pertanyaan lanjutan kontekstual (Zero-Token Chips) */}
      {smartSaran.length > 0 && (
        <div className="space-y-1.5 pt-1">
          <p className="text-[11px] text-muted flex items-center gap-1 font-medium">
            <Compass size={12} className="text-primary" />
            Rekomendasi pertanyaan berikutnya:
          </p>
          <div className="flex items-center gap-2 flex-wrap">
            {smartSaran.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => onAsk(s)}
                className="px-3 py-1 text-xs border border-hairline rounded-full bg-canvas text-body hover:bg-surface-soft hover:border-primary/40 hover:text-primary transition-colors cursor-pointer text-left shadow-2xs"
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
