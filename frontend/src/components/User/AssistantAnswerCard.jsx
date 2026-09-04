import { Component, useState } from 'react';
import {
  AlertTriangle, Check, ChevronDown, ChevronRight, Database, Layers, Sparkles, X, Zap,
  BarChart2, Table as TableIcon, Loader2, GraduationCap,
} from 'lucide-react';
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, Legend,
} from 'recharts';
import { api } from '../../services/api';
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

/** Deteksi apakah hasil data kueri cocok untuk ditampilkan sebagai grafik (0 token). */
function deteksiKecocokanGrafik(columns, rows) {
  if (!columns || !rows || rows.length === 0) return { cocok: false };

  let categoryIdx = -1;
  const numericIndices = [];

  for (let i = 0; i < columns.length; i += 1) {
    const colName = String(columns[i]).toLowerCase();
    const sampleVal = rows[0]?.[i] !== undefined ? rows[0][i] : rows[0]?.[columns[i]];
    const isNum = typeof sampleVal === 'number' || (!Number.isNaN(Number(sampleVal)) && String(sampleVal).trim() !== '');

    const isPriorityCategory = /tahun|thn|year|bulan|bln|month|periode|cabang|nama|kategori|tipe|model|jenis/i.test(colName);

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
    return { cocok: false };
  }

  const categoryCol = columns[categoryIdx];
  const valueCols = numericIndices.map((idx) => columns[idx]);

  const chartData = rows.slice(0, 30).map((r) => {
    const cells = Array.isArray(r) ? r : Object.values(r || {});
    const obj = { [categoryCol]: String(cells[categoryIdx] ?? '') };
    numericIndices.forEach((numIdx) => {
      const colName = columns[numIdx];
      const val = Number(cells[numIdx]);
      obj[colName] = Number.isNaN(val) ? 0 : val;
    });
    return obj;
  });

  return {
    cocok: true, categoryCol, valueCols, chartData,
  };
}

const BAR_COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899'];

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
      <div className="bg-white border border-hairline rounded-lg p-2 shadow-md text-xs">
        <p className="font-semibold text-ink mb-1">{label}</p>
        {payload.map((entry, index) => (
          <p key={index} style={{ color: entry.color }} className="flex justify-between gap-3">
            <span>{entry.name}:</span>
            <span className="font-medium">{formatSel(entry.value, entry.name)}</span>
          </p>
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
  const [activeTab, setActiveTab] = useState('table'); // 'table' | 'chart'
  const [penjelasan, setPenjelasan] = useState(null);
  const [loadingExplain, setLoadingExplain] = useState(false);
  const [trainingBusy, setTrainingBusy] = useState(false);
  const [trained, setTrained] = useState(false);

  const durasi = formatDurasi(answer.duration_ms);
  const terverifikasi = answer.source === 'memory' || memoryStatus === 'confirmed';
  const ditolak = memoryStatus === 'rejected';
  const saran = !ditolak && onAsk && Array.isArray(answer.saran) ? answer.saran : [];

  const grafikConfig = deteksiKecocokanGrafik(answer.columns, answer.rows);

  const handleExplain = async () => {
    if (loadingExplain || !branchCode) return;
    setLoadingExplain(true);
    try {
      const res = await api.explainChat({
        branchCode,
        question: question || answer.question || '',
        sql: answer.sql,
        rows: answer.rows,
      });
      setPenjelasan(res.narasi);
    } catch {
      toast.error('Gagal memuat penjelasan naratif.');
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
        sql: answer.sql,
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
              {loadingExplain ? 'Menganalisis data mendalam...' : '✨ Jelaskan Lebih Dalam dengan AI'}
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

        {/* Switcher Tab: Tabel Data vs Grafik Otomatis (0 token) */}
        {grafikConfig.cocok && answer.rows.length > 0 && (
          <div className="flex items-center justify-between pt-1">
            <div className="flex items-center gap-1 bg-surface-soft p-0.5 rounded-lg border border-hairline">
              <button
                type="button"
                onClick={() => setActiveTab('table')}
                className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium transition-colors cursor-pointer ${
                  activeTab === 'table' ? 'bg-white shadow-xs text-ink' : 'text-muted hover:text-ink'
                }`}
              >
                <TableIcon size={12} />
                Tabel Data
              </button>
              <button
                type="button"
                onClick={() => setActiveTab('chart')}
                className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium transition-colors cursor-pointer ${
                  activeTab === 'chart' ? 'bg-white shadow-xs text-ink' : 'text-muted hover:text-ink'
                }`}
              >
                <BarChart2 size={12} />
                Grafik
              </button>
            </div>
            <span className="text-[11px] text-muted hidden sm:inline">
              Visualisasi otomatis
            </span>
          </div>
        )}

        {/* Tampilan Konten: Grafik vs Tabel */}
        {answer.rows.length === 0 ? (
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
            <div className="border border-hairline rounded-lg p-3 bg-surface-soft/20">
              <div className="h-64 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={grafikConfig.chartData} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e5e7eb" />
                    <XAxis dataKey={grafikConfig.categoryCol} tick={{ fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 11 }} />
                    <Tooltip content={<CustomChartTooltip />} />
                    <Legend wrapperStyle={{ fontSize: '11px', paddingTop: '8px' }} />
                    {grafikConfig.valueCols.map((col, idx) => (
                      <Bar
                        key={col}
                        dataKey={col}
                        fill={BAR_COLORS[idx % BAR_COLORS.length]}
                        radius={[4, 4, 0, 0]}
                      />
                    ))}
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </SilentChartErrorBoundary>
        ) : (
          <div className="border border-hairline rounded-lg overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-surface-soft text-xs text-muted">
                <tr>
                  {answer.columns.map((col) => (
                    <th key={col} className="px-3 py-2 font-medium whitespace-nowrap">
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-hairline">
                {answer.rows.map((row, i) => {
                  const cells = Array.isArray(row) ? row : Object.values(row || {});
                  return (
                    <tr key={i} className="hover:bg-surface-soft/50 transition-colors">
                      {cells.map((cell, j) => (
                        <td
                          key={j}
                          className={`px-3 py-2 whitespace-nowrap ${j === 0 ? 'text-ink font-medium' : 'text-body'}`}
                        >
                          {formatSel(cell, answer.columns?.[j])}
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
            Lihat SQL
          </button>
          {tampilSql && (
            <pre className="mt-1.5 bg-canvas border border-hairline rounded-lg p-3 text-[11px] leading-relaxed font-mono text-body overflow-x-auto whitespace-pre-wrap break-words">
              {answer.sql}
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

      {/* Saran pertanyaan lanjutan */}
      {saran.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap pt-0.5">
          {saran.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => onAsk(s)}
              className="px-3 py-1 text-xs border border-hairline rounded-full bg-canvas text-body hover:bg-surface-soft hover:border-primary/40 transition-colors cursor-pointer"
            >
              {s}
            </button>
          ))}
        </div>
      )}
    </>
  );
}
