import { useEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import toast from 'react-hot-toast';
import { Bot, Building2, Check, Loader2, LogOut, Send, Sparkles } from 'lucide-react';

import AssistantAnswerCard from './AssistantAnswerCard';
import { api } from '../../services/api';

// Cabang aktif = penugasan PERTAMA user (App.jsx: user.allowed_branches =
// list kode cabang dari login). Dropdown multi-cabang: nanti, tidak di F4.
const cabangPertama = (u) => (u?.allowed_branches || [])[0] || null;

// Tahapan pipeline yang dianimasikan selama menunggu respons (label jujur —
// urutan nyata pipeline backend: normalisasi -> planner LLM -> verifier ->
// executor). Animasi berjalan sinkron dengan durasi request nyata: maju
// berkala, berhenti di tahap terakhir sampai jawaban/error datang.
const PIPELINE_STAGES = [
  { key: 'understand', label: 'Memahami pertanyaan…' },
  { key: 'plan', label: 'Menyusun rencana…' },
  { key: 'verify', label: 'Memeriksa keamanan…' },
  { key: 'fetch', label: 'Mengambil data…' },
];
const STAGE_INTERVAL_MS = 1200;

const SUGGESTED_QUESTIONS = [
  'Penjualan bulan ini',
  'Stok kendaraan tersedia',
  'Servis bulan ini',
];

// ID pesan sekuensial untuk pesan baru (riwayat hydrate memakai awalan h-)
let messageSeq = 0;
const nextMessageId = () => {
  messageSeq += 1;
  return `msg-${messageSeq}`;
};

/**
 * Pesan error API -> kalimat Indonesia ramah per kode (bentuk detail sesuai
 * routers/chat.py: string untuk sebagian besar kode; OBJEK {message, gate,
 * reason} khusus 422 dari VerifierDitolak).
 */
function pesanErrorChat(error) {
  const status = error?.response?.status;
  const detail = error?.response?.data?.detail;
  if (!status) {
    return 'Tidak dapat terhubung ke server. Periksa koneksi lalu coba lagi.';
  }
  if (status === 422) {
    const sebab = detail && typeof detail === 'object'
      ? `${detail.gate ?? '-'}: ${detail.reason ?? '-'}`
      : (typeof detail === 'string' ? detail : 'lolos verifikasi');
    return `Pertanyaan ini tidak dapat dijawab otomatis (${sebab}). `
      + 'Coba ubah kalimat pertanyaan.';
  }
  if (status === 502) {
    return 'AI gagal menyusun rencana — coba ulangi atau ubah kalimat pertanyaan.';
  }
  if (status === 503) {
    // 503 bisa AI belum dikonfigurasi ATAU database tenant tidak tersedia
    if (typeof detail === 'string' && detail.includes('Database tenant')) {
      return 'Database cabang sedang tidak tersedia — coba lagi nanti.';
    }
    return 'AI belum dikonfigurasi — hubungi admin.';
  }
  if (status === 504) return 'Query terlalu lama — persempit pertanyaan.';
  if (status === 429) {
    return typeof detail === 'string' ? detail : 'Terlalu sering, tunggu sebentar.';
  }
  if (status === 403) {
    return typeof detail === 'string' ? detail : 'Anda tidak punya akses ke cabang ini.';
  }
  if (status === 409) {
    return typeof detail === 'string' ? detail : 'Cabang belum siap — hubungi administrator.';
  }
  return 'Maaf, terjadi kesalahan saat memproses pertanyaan. Silakan coba lagi.';
}

/**
 * Pesan riwayat dari GET /chat/history -> bentuk pesan UI.
 * Pesan assistant menyimpan objek jawaban sebagai JSON string (lihat
 * chat_pipeline.simpan_pesan) — parse gagal = tampilkan sebagai teks.
 */
function pesanDariHistory(m, idx) {
  const id = `h-${idx}`;
  if (m.role === 'user') {
    return { id, role: 'user', text: m.content, createdAt: m.created_at };
  }
  let answer = null;
  try {
    const parsed = JSON.parse(m.content);
    if (parsed && Array.isArray(parsed.rows)) answer = parsed;
  } catch {
    // konten non-JSON (pesan lama/aset lain) — tampilkan apa adanya
  }
  if (answer) {
    return { id, role: 'assistant', status: 'done', answer, createdAt: m.created_at };
  }
  return { id, role: 'assistant', status: 'error', text: m.content, createdAt: m.created_at };
}

/**
 * Indikator bertahap pipeline AI selama request berjalan.
 * Tahap selesai -> centang, tahap aktif -> spinner, tahap berikutnya -> titik.
 */
function PipelineIndicator({ stageIndex }) {
  return (
    <div className="space-y-1.5" aria-live="polite">
      {PIPELINE_STAGES.map((stage, i) => {
        const isDone = i < stageIndex;
        const isActive = i === stageIndex;
        return (
          <div
            key={stage.key}
            className={`flex items-center gap-2 text-sm ${
              isActive ? 'text-ink font-medium' : isDone ? 'text-body' : 'text-muted/60'
            }`}
          >
            {isDone ? (
              <Check size={15} className="text-success" />
            ) : isActive ? (
              <Loader2 size={15} className="animate-spin text-primary" />
            ) : (
              <span className="w-[15px] h-[15px] rounded-full border border-hairline" aria-hidden="true" />
            )}
            {stage.label}
          </div>
        );
      })}
    </div>
  );
}

/** Satu gelembung pesan: pesan user (kanan) atau balasan asisten (kiri). */
function MessageBubble({ message, feedbackBusy, onFeedback }) {
  if (message.role === 'user') {
    return (
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.25 }}
        className="flex justify-end"
      >
        <div className="max-w-[80%] px-4 py-2.5 bg-primary text-white rounded-2xl rounded-br-md text-sm shadow-sm">
          {message.text}
        </div>
      </motion.div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      className="flex items-start gap-2.5"
    >
      <div className="w-8 h-8 rounded-full bg-primary/10 text-primary flex items-center justify-center shrink-0">
        <Bot size={16} />
      </div>

      {message.status === 'processing' ? (
        <div className="bg-white border border-hairline rounded-xl rounded-tl-md px-4 py-3 shadow-sm">
          <PipelineIndicator stageIndex={message.stageIndex} />
        </div>
      ) : message.status === 'error' ? (
        <div className="max-w-[80%] bg-white border border-hairline rounded-xl rounded-tl-md px-4 py-3 shadow-sm text-sm text-error">
          {message.text}
        </div>
      ) : (
        <div className="max-w-[85%] min-w-0">
          <AssistantAnswerCard
            answer={message.answer}
            createdAt={message.createdAt}
            memoryStatus={message.memoryStatus}
            feedbackBusy={feedbackBusy}
            onConfirm={() => onFeedback(message.id, 'confirm')}
            onReject={() => onFeedback(message.id, 'reject')}
          />
        </div>
      )}
    </motion.div>
  );
}

/**
 * Halaman chat untuk role `user` — tersambung ke Chat API nyata (F4):
 * POST /chat/query + GET /chat/history + confirm/reject SQL memory.
 */
export default function UserWorkspace({ user, onLogout }) {
  const branchCode = cabangPertama(user);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isProcessing, setIsProcessing] = useState(false);
  const [feedbackBusy, setFeedbackBusy] = useState(null);
  const bottomRef = useRef(null);

  useEffect(() => {
    document.title = 'Chat · DMS AI Platform';
  }, []);

  // Hydrate riwayat percakapan cabang ini saat halaman dibuka
  useEffect(() => {
    if (!branchCode) return undefined;
    let batal = false;
    api.fetchChatHistory(branchCode)
      .then((data) => {
        if (!batal) setMessages(data.messages.map(pesanDariHistory));
      })
      .catch(() => {
        if (!batal) toast.error('Riwayat percakapan gagal dimuat.');
      });
    return () => {
      batal = true;
    };
  }, [branchCode]);

  // Auto-scroll ke pesan terbaru setiap daftar pesan berubah
  // (termasuk saat indikator pipeline berpindah tahap).
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages]);

  const handleSend = async (rawText) => {
    const text = typeof rawText === 'string' ? rawText : input;
    const trimmed = text.trim();
    if (!trimmed || isProcessing || !branchCode) return;

    setInput('');
    setIsProcessing(true);
    const assistantId = nextMessageId();
    setMessages((prev) => [
      ...prev,
      { id: nextMessageId(), role: 'user', text: trimmed },
      { id: assistantId, role: 'assistant', status: 'processing', stageIndex: 0 },
    ]);

    // Animasi tahap maju berkala; berhenti di tahap terakhir sampai respons.
    const timer = setInterval(() => {
      setMessages((prev) => prev.map((m) => (
        m.id === assistantId && m.status === 'processing'
          && m.stageIndex < PIPELINE_STAGES.length - 1
          ? { ...m, stageIndex: m.stageIndex + 1 }
          : m
      )));
    }, STAGE_INTERVAL_MS);

    try {
      const answer = await api.askAssistant(branchCode, trimmed);
      setMessages((prev) => prev.map((m) => (
        m.id === assistantId
          ? { ...m, status: 'done', answer, createdAt: new Date().toISOString() }
          : m
      )));
    } catch (error) {
      // Bubble error ikut masuk riwayat lokal
      setMessages((prev) => prev.map((m) => (
        m.id === assistantId
          ? { ...m, status: 'error', text: pesanErrorChat(error) }
          : m
      )));
    } finally {
      clearInterval(timer);
      setIsProcessing(false);
    }
  };

  /** Tombol "Jawaban benar/salah" -> confirm/reject SQL memory (F4). */
  const handleFeedback = async (messageId, aksi) => {
    const msg = messages.find((m) => m.id === messageId);
    const memoryId = msg?.answer?.memory_id;
    if (!memoryId || !branchCode || feedbackBusy) return;
    setFeedbackBusy(aksi);
    try {
      if (aksi === 'confirm') {
        await api.confirmMemory(branchCode, memoryId);
        toast.success('Jawaban disimpan sebagai memori terverifikasi.');
      } else {
        await api.rejectMemory(branchCode, memoryId);
        toast.success('Jawaban ditandai salah — terima kasih atas koreksinya.');
      }
      // Tombol hilang: memoryStatus terisi -> badge berubah / chip abu.
      setMessages((prev) => prev.map((m) => (
        m.id === messageId
          ? { ...m, memoryStatus: aksi === 'confirm' ? 'confirmed' : 'rejected' }
          : m
      )));
    } catch (error) {
      toast.error(pesanErrorChat(error));
    } finally {
      setFeedbackBusy(null);
    }
  };

  return (
    <div className="h-screen bg-canvas flex flex-col overflow-hidden">
      {/* Header: judul app + info cabang aktif (penugasan pertama user) */}
      <header className="bg-white border-b border-hairline shrink-0">
        <div className="max-w-3xl mx-auto px-4 py-3 flex items-center justify-between gap-3">
          <div>
            <h1 className="font-serif text-lg text-ink leading-tight">DMS AI Platform</h1>
            <p className="text-xs text-muted">Asisten Laporan Dealer</p>
          </div>
          <div className="flex items-center gap-2">
            {branchCode && (
              <span className="hidden sm:flex items-center gap-1.5 px-3 py-1 bg-primary/10 text-primary text-xs font-medium rounded-full">
                <Building2 size={13} />
                {branchCode}
              </span>
            )}
            <span className="hidden md:inline text-xs text-muted">{user?.username}</span>
            <button
              onClick={onLogout}
              title="Keluar"
              className="flex items-center gap-1.5 px-3 py-1.5 border border-hairline rounded-md text-sm text-muted hover:bg-surface-soft hover:text-ink transition-colors"
            >
              <LogOut size={15} />
              Keluar
            </button>
          </div>
        </div>
      </header>

      {/* Area percakapan */}
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-4 py-6 space-y-4">
          {messages.length === 0 && (
            <motion.div
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.35 }}
              className="flex flex-col items-center text-center mt-10"
            >
              <div className="w-14 h-14 rounded-full bg-primary/10 text-primary flex items-center justify-center mb-4">
                <Bot size={28} />
              </div>
              <h2 className="font-serif text-2xl text-ink">Halo, {user?.username}!</h2>
              <p className="text-body text-sm mt-2 max-w-md">
                {branchCode
                  ? <>Saya asisten AI untuk cabang <span className="font-medium text-ink">{branchCode}</span>. Tanyakan apa saja tentang penjualan, stok, atau servis — saya ambilkan datanya langsung dari database.</>
                  : 'Tidak ada cabang yang ditugaskan ke akun Anda — hubungi administrator untuk bisa menggunakan asisten.'}
              </p>
            </motion.div>
          )}

          {messages.map((m) => (
            <MessageBubble
              key={m.id}
              message={m}
              feedbackBusy={feedbackBusy}
              onFeedback={handleFeedback}
            />
          ))}

          <div ref={bottomRef} />
        </div>
      </main>

      {/* Chip saran + kolom input */}
      <footer className="bg-white border-t border-hairline shrink-0">
        <div className="max-w-3xl mx-auto px-4 py-3 space-y-2">
          <div className="flex items-center gap-2 flex-wrap">
            <Sparkles size={14} className="text-primary shrink-0" aria-hidden="true" />
            {SUGGESTED_QUESTIONS.map((q) => (
              <button
                key={q}
                type="button"
                disabled={isProcessing || !branchCode}
                onClick={() => handleSend(q)}
                className="px-3 py-1 text-xs border border-hairline rounded-full bg-canvas text-body hover:bg-surface-soft hover:border-primary/40 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {q}
              </button>
            ))}
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleSend();
            }}
            className="flex items-center gap-2"
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={isProcessing || !branchCode}
              placeholder={
                !branchCode
                  ? 'Tidak ada cabang aktif…'
                  : isProcessing
                    ? 'Sedang memproses…'
                    : `Tanya apa saja tentang cabang ${branchCode}…`
              }
              className="flex-1 py-2.5 px-4 border border-hairline rounded-md bg-canvas text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 disabled:opacity-60"
              aria-label="Pertanyaan"
            />
            <button
              type="submit"
              disabled={isProcessing || !branchCode || !input.trim()}
              className="flex items-center gap-2 px-4 py-2.5 bg-primary text-white rounded-md text-sm hover:bg-primary-active shadow-sm disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {isProcessing ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
              Kirim
            </button>
          </form>

          <p className="text-[11px] text-muted text-center">
            Jawaban disertai SQL-nya — klik &quot;Lihat SQL&quot; untuk memeriksa query yang dijalankan.
          </p>
        </div>
      </footer>
    </div>
  );
}
