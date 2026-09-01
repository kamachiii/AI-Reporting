import { useState } from 'react';
import {
  AlertTriangle, Check, ChevronDown, ChevronRight, Database, Sparkles, X,
} from 'lucide-react';

/** Durasi ms -> teks ringkas ("320 ms" / "1,4 dtk"). */
function formatDurasi(ms) {
  if (ms === null || ms === undefined) return null;
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} dtk`;
}

/** Sel tabel: null/undefined tampil sebagai garis, bukan kosong. */
function formatSel(nilai) {
  if (nilai === null || nilai === undefined) return '—';
  return String(nilai);
}

/**
 * Kartu jawaban asisten dari Chat API nyata (F4).
 *
 * `answer` = response POST /chat/query: {source, confidence, sql, columns,
 * rows, row_count, truncated, duration_ms, memory_id}. Tidak ada ringkasan
 * naratif — presenter LLM #2 adalah F2.5 (UI menyajikan tabel + SQL apa adanya).
 *
 * `memoryStatus`: 'confirmed' | 'rejected' (hasil feedback user, lokal) —
 * undefined selama belum dinilai. Tombol feedback tampil hanya untuk
 * jawaban yang punya memory_id (entri SQL memory pending).
 */
export default function AssistantAnswerCard({
  answer,
  createdAt,
  memoryStatus,
  feedbackBusy,
  onConfirm,
  onReject,
}) {
  const [tampilSql, setTampilSql] = useState(false);
  const durasi = formatDurasi(answer.duration_ms);
  const terverifikasi = answer.source === 'memory' || memoryStatus === 'confirmed';
  const ditolak = memoryStatus === 'rejected';

  return (
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

      {/* Tabel data — atau EmptyState bila query tidak mengembalikan baris */}
      {answer.rows.length === 0 ? (
        <div className="border border-dashed border-hairline rounded-lg px-4 py-6 text-center">
          <Database size={18} className="mx-auto text-muted/60 mb-1" aria-hidden="true" />
          <p className="text-sm text-body font-medium">Tidak ada data</p>
          <p className="text-xs text-muted mt-0.5">
            Query berjalan tanpa kesalahan tetapi tidak mengembalikan baris —
            coba ubah rentang waktu atau filter pertanyaan.
          </p>
        </div>
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
              {answer.rows.map((row, i) => (
                <tr key={i} className="hover:bg-surface-soft/50 transition-colors">
                  {row.map((cell, j) => (
                    <td
                      key={j}
                      className={`px-3 py-2 whitespace-nowrap ${j === 0 ? 'text-ink font-medium' : 'text-body'}`}
                    >
                      {formatSel(cell)}
                    </td>
                  ))}
                </tr>
              ))}
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

      {/* SQL disertakan apa adanya (kejujuran UI) — teks, BUKAN dirender HTML */}
      <div>
        <button
          type="button"
          onClick={() => setTampilSql((v) => !v)}
          className="inline-flex items-center gap-1 text-xs text-muted hover:text-ink transition-colors"
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

      {/* Meta: jumlah baris + durasi eksekusi + waktu jawaban */}
      <p className="text-[11px] text-muted">
        {answer.row_count} baris{durasi && ` · ${durasi}`}
        {createdAt &&
          ` · ${new Date(createdAt).toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' })}`}
      </p>

      {/* Feedback (F4): hanya jawaban dengan memory_id & belum dinilai.
          Setelah diklik tombol hilang — badge berubah via memoryStatus. */}
      {answer.memory_id && !memoryStatus && (onConfirm || onReject) && (
        <div className="flex items-center gap-2 pt-2 border-t border-hairline">
          <span className="text-xs text-muted">Apakah jawaban ini benar?</span>
          {onConfirm && (
            <button
              type="button"
              onClick={onConfirm}
              disabled={!!feedbackBusy}
              className="inline-flex items-center gap-1 px-2.5 py-1 text-xs border border-hairline rounded-md text-success hover:bg-success/10 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
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
              className="inline-flex items-center gap-1 px-2.5 py-1 text-xs border border-hairline rounded-md text-error hover:bg-error/10 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              <X size={13} />
              Jawaban salah
            </button>
          )}
        </div>
      )}
    </div>
  );
}
