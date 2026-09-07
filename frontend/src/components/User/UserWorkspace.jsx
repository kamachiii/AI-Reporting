import { useEffect, useRef, useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import toast from 'react-hot-toast';
import {
  Check, Loader2, LogOut, Send, Bot, RotateCcw,
  PanelLeftOpen, MessageSquarePlus,
  Car, Wrench, Package, BarChart3, ShieldCheck, ArrowRight,
} from 'lucide-react';

import AssistantAnswerCard from './AssistantAnswerCard';
import ClarificationCard from './ClarificationCard';
import ChatHistorySidebar from './ChatHistorySidebar';
import { api } from '../../services/api';

// Cabang aktif = penugasan PERTAMA user (App.jsx: user.allowed_branches =
// list kode cabang dari login). Dropdown multi-cabang: nanti, tidak di F4.
const cabangPertama = (u) => (u?.allowed_branches || [])[0] || null;

// Tahapan pipeline yang dianimasikan selama menunggu respons (label jujur —
// urutan nyata pipeline backend: normalisasi -> planner LLM -> verifier ->
// executor). Animasi berjalan sinkron dengan durasi request nyata: maju
// berkala, berhenti di tahap terakhir sampai jawaban/error datang.
const PIPELINE_STAGES = [
  { key: 'understand', label: 'Memvalidasi konteks kueri bisnis & skema cabang…' },
  { key: 'plan', label: 'Menyusun rencana SQL deterministik / Text2SQL…' },
  { key: 'verify', label: 'Memeriksa verifier 6-gerbang keamanan AST & budget…' },
  { key: 'fetch', label: 'Mengeksekusi database read-only & agregasi baris…' },
];
const STAGE_INTERVAL_MS = 1100;

// Rekomendasi kueri analitik awal (Executive Command Deck)
const PROMPT_SUGGESTIONS = [
  {
    category: 'Penjualan Unit',
    icon: Car,
    query: 'Bandingkan tren penjualan unit per bulan tahun ini',
    desc: 'Omzet, unit terjual, dan komparasi bulanan',
  },
  {
    category: 'Layanan Bengkel',
    icon: Wrench,
    query: 'Berapa unit entry WO servis dan mekanik aktif bulan ini?',
    desc: 'Work order, produktivitas SA & teknisi',
  },
  {
    category: 'Suku Cadang & Stok',
    icon: Package,
    query: 'Tampilkan suku cadang dengan stok menipis di gudang',
    desc: 'Inventori part, slow vs fast-moving',
  },
  {
    category: 'Komparasi Lintas Divisi',
    icon: BarChart3,
    query: 'Bandingkan performa antar divisi tahun ini',
    desc: 'Sinergi pilar 3S (Sales, Service, Sparepart)',
  },
];

// ID pesan sekuensial untuk pesan baru (riwayat hydrate memakai awalan h-)
let messageSeq = 0;
const nextMessageId = () => {
  messageSeq += 1;
  return `msg-${Date.now()}-${messageSeq}-${Math.random().toString(36).slice(2, 6)}`;
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
    let sebab = 'verifikasi gagal';
    if (Array.isArray(detail)) {
      sebab = detail.map((d) => d.msg || d.reason || JSON.stringify(d)).join(', ');
    } else if (detail && typeof detail === 'object') {
      sebab = `${detail.gate ?? '-'}: ${detail.reason ?? detail.message ?? '-'}`;
    } else if (typeof detail === 'string') {
      sebab = detail;
    }
    return `Pertanyaan ini tidak dapat dijawab otomatis (${sebab}). `
      + 'Coba ubah kalimat pertanyaan.';
  }
  if (status === 502) {
    return 'AI gagal menyusun rencana — coba ulangi atau ubah kalimat pertanyaan.';
  }
  if (status === 503) {
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
function pesanDariHistory(m, idx, allMsgs = []) {
  const id = m.id ? `h-${m.id}` : `h-${idx}-${m.created_at || ''}`;
  if (m.role === 'user') {
    return { id, role: 'user', text: m.content, createdAt: m.created_at };
  }
  let answer = null;
  try {
    const parsed = JSON.parse(m.content);
    if (parsed && (Array.isArray(parsed.rows) || parsed.source === 'clarification' || parsed.status === 'clarification_needed')) {
      answer = parsed;
    }
  } catch {
    // konten non-JSON (pesan lama/aset lain) — tampilkan apa adanya
  }
  const prevUserMsg = allMsgs && idx > 0 ? allMsgs[idx - 1] : null;
  const questionText = answer?.question || prevUserMsg?.content || prevUserMsg?.text || '';

  if (answer) {
    return { id, role: 'assistant', status: 'done', answer, question: questionText, createdAt: m.created_at };
  }
  return { id, role: 'assistant', status: 'error', text: m.content, createdAt: m.created_at };
}

/**
 * Indikator bertahap pipeline AI selama request berjalan.
 * Telemetri tenang, berkelas teknis, tanpa gimmick berlebih.
 */
function PipelineIndicator({ stageIndex }) {
  return (
    <div className="space-y-2 py-1 select-none" aria-live="polite">
      <div className="text-[11px] font-mono text-muted uppercase tracking-wider flex items-center gap-1.5 pb-1 border-b border-hairline/60">
        <span className="w-2 h-2 rounded-full bg-primary animate-ping" />
        <span>Eksekusi Pipeline Intelijen Data</span>
      </div>
      <div className="space-y-1.5">
        {PIPELINE_STAGES.map((stage, i) => {
          const isDone = i < stageIndex;
          const isActive = i === stageIndex;
          return (
            <div
              key={stage.key}
              className={`flex items-center gap-2.5 text-xs transition-colors ${
                isActive ? 'text-ink font-medium' : isDone ? 'text-body/80' : 'text-muted/40'
              }`}
            >
              {isDone ? (
                <div className="w-4 h-4 rounded-full bg-emerald-50 text-emerald-600 flex items-center justify-center shrink-0 border border-emerald-200">
                  <Check size={11} />
                </div>
              ) : isActive ? (
                <div className="w-4 h-4 flex items-center justify-center shrink-0">
                  <Loader2 size={13} className="animate-spin text-primary" />
                </div>
              ) : (
                <span className="w-4 h-4 rounded-full border border-hairline/80 flex items-center justify-center text-[10px] text-muted/50 font-mono">
                  {i + 1}
                </span>
              )}
              <span className="leading-snug">{stage.label}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** Satu blok pertukaran pesan: pesan user (kanan) atau dossier jawaban (kiri). */
function MessageBubble({
  message, branchCode, feedbackBusy, onAsk, onFeedback,
}) {
  if (message.role === 'user') {
    return (
      <motion.div
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.2 }}
        className="flex justify-end py-1.5"
      >
        <div className="max-w-[85%] sm:max-w-[75%] space-y-1">
          <div className="flex items-center justify-end gap-2 text-[11px] text-muted-soft font-medium pr-1">
            <span>Pertanyaan Anda</span>
            {message.createdAt && (
              <span className="font-mono text-[10px] text-muted-soft tabular-nums">
                {new Date(message.createdAt).toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' })}
              </span>
            )}
          </div>
          <div className="px-4 py-3 bg-surface-cream-strong text-ink rounded-lg text-sm leading-relaxed shadow-2xs border border-hairline font-sans">
            {message.text}
          </div>
        </div>
      </motion.div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      className="py-2 w-full space-y-1.5"
    >
      <div className="flex items-center gap-2 text-[11px] text-muted-soft font-medium pl-0.5">
        <div className="w-5 h-5 rounded-md bg-primary/10 text-primary flex items-center justify-center shrink-0 border border-primary/20">
          <Bot size={13} />
        </div>
        <span className="font-medium text-ink">Intelijen Dealer AI</span>
        <span className="text-hairline">•</span>
        <span className="font-mono text-[10px] text-muted-soft">Core Engine</span>
        {message.createdAt && (
          <span className="font-mono text-[10px] text-muted-soft ml-auto tabular-nums">
            {new Date(message.createdAt).toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' })}
          </span>
        )}
      </div>

      {message.status === 'processing' ? (
        <div className="bg-canvas border border-hairline rounded-lg p-4 shadow-2xs max-w-md">
          <PipelineIndicator stageIndex={message.stageIndex} />
        </div>
      ) : message.status === 'error' ? (
        <div className="max-w-2xl bg-rose-50/80 border border-rose-200 rounded-lg px-4 py-3.5 shadow-2xs text-xs text-rose-900 leading-relaxed space-y-2">
          <div className="font-semibold flex items-center justify-between gap-1.5 text-red-800">
            <span>Pemeriksaan Gagal</span>
            {message.question && onAsk && (
              <button
                type="button"
                onClick={() => onAsk(message.question)}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-rose-100 hover:bg-rose-200 text-rose-900 font-medium text-[11px] transition-colors cursor-pointer"
              >
                <RotateCcw size={11} />
                <span>Coba Lagi</span>
              </button>
            )}
          </div>
          <p>{message.text}</p>
        </div>
      ) : message.answer?.source === 'clarification' || message.answer?.status === 'clarification_needed' ? (
        <div className="w-full min-w-0">
          <ClarificationCard
            answer={message.answer}
            onAsk={onAsk}
          />
        </div>
      ) : (
        <div className="w-full min-w-0">
          <AssistantAnswerCard
            answer={message.answer}
            question={message.question}
            branchCode={branchCode}
            createdAt={message.createdAt}
            memoryStatus={message.memoryStatus}
            feedbackBusy={feedbackBusy}
            onAsk={onAsk}
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
  const [conversations, setConversations] = useState([]);
  const [activeConversationId, setActiveConversationId] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isProcessing, setIsProcessing] = useState(false);
  const [feedbackBusy, setFeedbackBusy] = useState(null);
  const bottomRef = useRef(null);

  useEffect(() => {
    document.title = 'Chat · DMS AI Platform';
  }, []);

  const loadConversations = useCallback(async (bCode) => {
    if (!bCode) return [];
    try {
      const data = await api.getConversations(bCode);
      const list = Array.isArray(data) ? data : (data?.conversations || []);
      setConversations(list);
      return list;
    } catch {
      return [];
    }
  }, []);

  // Hydrate percakapan cabang ini saat halaman dibuka
  useEffect(() => {
    if (!branchCode) return undefined;
    let batal = false;
    loadConversations(branchCode).then((list) => {
      if (batal || !list || list.length === 0) return;
      // Aktifkan sesi percakapan terbaru jika ada
      const first = list[0];
      setActiveConversationId(first.id);
      api.getConversationMessages(first.id)
        .then((data) => {
          if (!batal) {
            setMessages((data.messages || []).map((m, idx, arr) => pesanDariHistory(m, idx, arr)));
          }
        })
        .catch(() => {
          if (!batal) toast.error('Riwayat percakapan gagal dimuat.');
        });
    });
    return () => {
      batal = true;
    };
  }, [branchCode, loadConversations]);

  // Auto-scroll ke pesan terbaru setiap daftar pesan berubah
  // (termasuk saat indikator pipeline berpindah tahap).
  useEffect(() => {
    if (messages.length > 0) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
    }
  }, [messages]);

  const handleSelectConversation = async (convId) => {
    if (isProcessing || convId === activeConversationId) return;
    setActiveConversationId(convId);
    try {
      const data = await api.getConversationMessages(convId);
      setMessages((data.messages || []).map((m, idx, arr) => pesanDariHistory(m, idx, arr)));
    } catch {
      toast.error('Gagal memuat percakapan yang dipilih.');
    }
  };

  const handleNewChat = () => {
    if (isProcessing) return;
    setActiveConversationId(null);
    setMessages([]);
  };

  const handleDeleteConversation = async (convId) => {
    try {
      await api.deleteConversation(convId);
      toast.success('Percakapan dihapus.');
      setConversations((prev) => prev.filter((c) => c.id !== convId));
      if (activeConversationId === convId) {
        handleNewChat();
      }
    } catch {
      toast.error('Gagal menghapus percakapan.');
    }
  };

  const handleClearAllConversations = async () => {
    if (!branchCode) return;
    try {
      await api.clearAllConversations(branchCode);
      toast.success('Semua riwayat percakapan dihapus.');
      setConversations([]);
      handleNewChat();
    } catch {
      toast.error('Gagal membersihkan riwayat.');
    }
  };

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
      const answer = await api.askAssistant(branchCode, trimmed, activeConversationId);
      setMessages((prev) => prev.map((m) => (
        m.id === assistantId
          ? { ...m, status: 'done', answer, question: trimmed, createdAt: new Date().toISOString() }
          : m
      )));
      if (answer.conversation_id) {
        setActiveConversationId(answer.conversation_id);
      }
      loadConversations(branchCode);
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
      {/* Header (Top Navigation 64px sesuai DESIGN-claude.md) */}
      <header className="h-16 bg-canvas border-b border-hairline shrink-0 px-4">
        <div className="h-full flex items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-primary/10 text-primary flex items-center justify-center border border-primary/20 shrink-0 shadow-2xs">
              <Bot size={18} />
            </div>
            <div>
              <h1 className="font-serif text-base sm:text-lg text-ink font-medium tracking-tight leading-none">
                DMS AI Platform
              </h1>
              <p className="text-[11px] text-muted-soft mt-0.5 font-sans">
                Asisten Laporan Dealer
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleNewChat}
              title="Mulai Sesi Chat Baru"
              className="h-9 flex items-center gap-1.5 px-3 rounded-md bg-canvas hover:bg-surface-soft border border-hairline text-xs font-medium text-ink transition-colors shadow-2xs cursor-pointer"
            >
              <MessageSquarePlus size={14} className="text-primary" />
              <span className="hidden sm:inline">Sesi Baru</span>
            </button>

            {branchCode && (
              <div className="hidden sm:inline-flex items-center gap-2 px-3 py-1 rounded-full bg-surface-card border border-hairline text-xs font-medium text-ink">
                <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                <span className="font-mono font-medium">{branchCode}</span>
                <span className="text-hairline text-[10px]">|</span>
                <span className="text-muted text-[11px]">Database Siap</span>
              </div>
            )}

            <div className="h-4 w-[1px] bg-hairline hidden md:block mx-0.5" />

            <span className="hidden md:inline text-xs text-muted-soft font-medium font-mono">{user?.username}</span>

            <button
              onClick={onLogout}
              title="Keluar dari sesi"
              className="h-9 flex items-center gap-1.5 px-2.5 border border-hairline rounded-md text-xs text-muted hover:bg-surface-soft hover:text-ink transition-colors cursor-pointer"
            >
              <LogOut size={13} />
              <span className="hidden sm:inline">Keluar</span>
            </button>
          </div>
        </div>
      </header>

      {/* Main Container: Sidebar Riwayat (Kiri) + Area Chat (Kanan) */}
      <div className="flex-1 flex overflow-hidden relative">
        <AnimatePresence initial={false}>
          {sidebarOpen && (
            <ChatHistorySidebar
              conversations={conversations}
              activeId={activeConversationId}
              onSelectConversation={handleSelectConversation}
              onNewChat={handleNewChat}
              onDeleteConversation={handleDeleteConversation}
              onClearAll={handleClearAllConversations}
              isOpen={sidebarOpen}
              onToggleOpen={() => setSidebarOpen(false)}
            />
          )}
        </AnimatePresence>

        <div className="flex-1 flex flex-col min-w-0 h-full overflow-hidden relative">
          {/* Floating Edge Handle: Membuka sidebar dari tepi layar tanpa menggeser navbar (Gaya Linear & Cursor) */}
          <AnimatePresence>
            {!sidebarOpen && (
              <motion.button
                initial={{ x: -30, opacity: 0 }}
                animate={{ x: 0, opacity: 1 }}
                exit={{ x: -30, opacity: 0 }}
                transition={{ duration: 0.2, ease: 'easeOut' }}
                type="button"
                onClick={() => setSidebarOpen(true)}
                title="Buka Riwayat Percakapan"
                aria-label="Buka Riwayat Percakapan"
                className="absolute left-0 top-3 z-30 group flex items-center gap-2 pl-2.5 pr-3 py-1.5 bg-surface-card hover:bg-surface-cream-strong border-y border-r border-hairline rounded-r-xl shadow-xs hover:shadow-sm text-body hover:text-ink transition-colors cursor-pointer select-none"
              >
                <PanelLeftOpen size={14} className="text-primary group-hover:scale-105 transition-transform" />
                <span className="text-xs font-sans font-normal text-body hover:text-ink tracking-tight">
                  Riwayat Chat
                </span>
              </motion.button>
            )}
          </AnimatePresence>

          {/* Area percakapan */}
          <main className="flex-1 overflow-y-auto">
            <div className="max-w-3xl mx-auto px-4 py-6 space-y-4">
              {messages.length === 0 && (
                <motion.div
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.3 }}
                  className="py-6 sm:py-10 space-y-7 select-none"
                >
                  {/* Hero Dossier Header */}
                  <div className="text-center max-w-xl mx-auto space-y-2.5">
                    <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-surface-card border border-hairline text-xs font-medium text-body">
                      <ShieldCheck size={13} className="text-emerald-600" />
                      <span>Terhubung ke Basis Data Dealer ({branchCode || 'Aktif'})</span>
                    </div>
                    <h2 className="font-serif text-3xl sm:text-4xl text-ink font-normal tracking-tight text-balance leading-tight">
                      Eksplorasi Data & Kinerja Dealer
                    </h2>
                    <p className="text-body text-xs sm:text-sm leading-relaxed text-pretty max-w-lg mx-auto font-sans">
                      Analisis performa penjualan unit, operasional servis bengkel, dan ketersediaan stok
                      secara langsung dari database transaksi riil tanpa perlu menyusun SQL manual.
                    </p>
                  </div>

                  {/* Quick Analytical Command Grid (Claude feature-card format) */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 max-w-2xl mx-auto pt-1">
                    {PROMPT_SUGGESTIONS.map((item, idx) => (
                      <button
                        key={idx}
                        type="button"
                        onClick={() => handleSend(item.query)}
                        disabled={isProcessing || !branchCode}
                        className="group text-left p-5 rounded-lg bg-surface-card border border-hairline hover:border-primary/50 transition-all cursor-pointer flex flex-col justify-between shadow-2xs"
                      >
                        <div className="flex items-center justify-between mb-1.5">
                          <span className="inline-flex items-center gap-1.5 text-xs font-medium text-ink group-hover:text-primary transition-colors">
                            <item.icon size={14} className="text-primary" />
                            {item.category}
                          </span>
                          <ArrowRight size={13} className="text-muted/40 group-hover:text-primary group-hover:translate-x-0.5 transition-all" />
                        </div>
                        <p className="text-xs text-ink font-sans font-medium mt-1 leading-snug">
                          &ldquo;{item.query}&rdquo;
                        </p>
                        <p className="text-[11px] text-muted mt-1 font-sans">
                          {item.desc}
                        </p>
                      </button>
                    ))}
                  </div>

                  {/* System Telemetry Metadata */}
                  <div className="flex items-center justify-center gap-3 text-[11px] text-muted-soft font-mono pt-3 border-t border-hairline/60 max-w-md mx-auto">
                    <span>2.387 Tabel Terpantau</span>
                    <span>•</span>
                    <span>Read-Only Enforced</span>
                    <span>•</span>
                    <span>AST Verifier Active</span>
                  </div>
                </motion.div>
              )}

              {messages.map((m) => (
                <MessageBubble
                  key={m.id}
                  message={m}
                  branchCode={branchCode}
                  feedbackBusy={feedbackBusy}
                  onAsk={handleSend}
                  onFeedback={handleFeedback}
                />
              ))}

              <div ref={bottomRef} />
            </div>
          </main>

          {/* Kolom input console */}
          <footer className="bg-canvas/95 backdrop-blur-xs border-t border-hairline shrink-0">
            <div className="max-w-3xl mx-auto px-4 py-3">
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  handleSend();
                }}
                className="relative flex items-center bg-canvas border border-hairline rounded-md shadow-2xs focus-within:border-primary focus-within:ring-3 focus-within:ring-primary/15 transition-all"
              >
                <input
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  disabled={isProcessing || !branchCode}
                  placeholder={
                    !branchCode
                      ? 'Pilih cabang aktif terlebih dahulu…'
                      : isProcessing
                        ? 'Sedang menganalisis basis data dealer…'
                        : `Ajukan pertanyaan analitik untuk cabang ${branchCode}…`
                  }
                  className="flex-1 h-11 pl-4 pr-12 bg-transparent text-sm text-ink placeholder:text-muted-soft focus:outline-none disabled:opacity-60 font-sans"
                  aria-label="Pertanyaan analitik"
                />
                <div className="absolute right-1.5 top-1/2 -translate-y-1/2 flex items-center gap-1">
                  <button
                    type="submit"
                    disabled={isProcessing || !branchCode || !input.trim()}
                    className="p-2 rounded-md bg-primary hover:bg-primary-active text-on-primary disabled:bg-primary-disabled disabled:text-muted disabled:cursor-not-allowed transition-colors cursor-pointer shadow-2xs"
                    title="Kirim Pertanyaan"
                    aria-label="Kirim Pertanyaan"
                  >
                    {isProcessing ? <Loader2 size={15} className="animate-spin" /> : <Send size={15} />}
                  </button>
                </div>
              </form>

              <div className="flex items-center justify-between text-[11px] text-muted-soft pt-2 px-1">
                <span className="flex items-center gap-1.5">
                  <ShieldCheck size={12} className="text-emerald-600" />
                  <span>Kueri dieksekusi secara read-only dengan verifikasi AST & pgvector</span>
                </span>
                <span className="font-mono text-[10px] hidden sm:inline">Enter ↵ kirim</span>
              </div>
            </div>
          </footer>
        </div>
      </div>
    </div>
  );
}
