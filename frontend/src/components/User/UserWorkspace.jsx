import { useEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { Bot, Building2, Check, Loader2, LogOut, Send, Sparkles } from 'lucide-react';

import AssistantAnswerCard from './AssistantAnswerCard';
import {
  MOCK_PIPELINE_STAGES,
  MOCK_USER_CONTEXT,
  SUGGESTED_QUESTIONS,
  askAssistant,
} from '../../services/mockChat';

// ID pesan sekuensial (cukup in-memory — riwayat sengaja tidak dipersist)
let messageSeq = 0;
const nextMessageId = () => {
  messageSeq += 1;
  return `msg-${messageSeq}`;
};

/**
 * Indikator bertahap pipeline AI yang sedang disimulasikan.
 * Tahap selesai -> centang, tahap aktif -> spinner, tahap berikutnya -> titik.
 */
function PipelineIndicator({ stageIndex }) {
  return (
    <div className="space-y-1.5" aria-live="polite">
      {MOCK_PIPELINE_STAGES.map((stage, i) => {
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
function MessageBubble({ message }) {
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
          <AssistantAnswerCard answer={message.answer} />
        </div>
      )}
    </motion.div>
  );
}

/**
 * Halaman chat untuk role `user` — menggantikan placeholder User Workspace.
 * Data & logika pipeline 100% MOCK (services/mockChat.js); komponen ini
 * hanya mengonsumsi `askAssistant()`.
 */
export default function UserWorkspace({ user, onLogout }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isProcessing, setIsProcessing] = useState(false);
  const bottomRef = useRef(null);

  useEffect(() => {
    document.title = 'Chat · DMS AI Platform';
  }, []);

  // Auto-scroll ke pesan terbaru setiap daftar pesan berubah
  // (termasuk saat indikator pipeline berpindah tahap).
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages]);

  const handleSend = async (rawText) => {
    const text = typeof rawText === 'string' ? rawText : input;
    const trimmed = text.trim();
    if (!trimmed || isProcessing) return;

    setInput('');
    setIsProcessing(true);
    const assistantId = nextMessageId();
    setMessages((prev) => [
      ...prev,
      { id: nextMessageId(), role: 'user', text: trimmed },
      { id: assistantId, role: 'assistant', status: 'processing', stageIndex: 0 },
    ]);

    try {
      const answer = await askAssistant(trimmed, {
        onStage: (stageIndex) =>
          setMessages((prev) =>
            prev.map((m) => (m.id === assistantId ? { ...m, stageIndex } : m)),
          ),
      });
      setMessages((prev) =>
        prev.map((m) => (m.id === assistantId ? { ...m, status: 'done', answer } : m)),
      );
    } catch {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId
            ? { ...m, status: 'error', text: 'Maaf, terjadi kesalahan saat memproses pertanyaan. Silakan coba lagi.' }
            : m,
        ),
      );
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <div className="h-screen bg-canvas flex flex-col overflow-hidden">
      {/* Header: judul app + info cabang user (mock) */}
      <header className="bg-white border-b border-hairline shrink-0">
        <div className="max-w-3xl mx-auto px-4 py-3 flex items-center justify-between gap-3">
          <div>
            <h1 className="font-serif text-lg text-ink leading-tight">DMS AI Platform</h1>
            <p className="text-xs text-muted">Asisten Laporan Dealer</p>
          </div>
          <div className="flex items-center gap-2">
            <span className="hidden sm:flex items-center gap-1.5 px-3 py-1 bg-primary/10 text-primary text-xs font-medium rounded-full">
              <Building2 size={13} />
              {MOCK_USER_CONTEXT.branchName}
            </span>
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
                Saya asisten AI untuk {MOCK_USER_CONTEXT.branchName}. Tanyakan apa saja tentang
                penjualan, stok, atau servis — saya rangkum datanya untukmu.
              </p>
            </motion.div>
          )}

          {messages.map((m) => (
            <MessageBubble key={m.id} message={m} />
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
                disabled={isProcessing}
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
              disabled={isProcessing}
              placeholder={
                isProcessing
                  ? 'Sedang memproses…'
                  : `Tanya apa saja tentang ${MOCK_USER_CONTEXT.branchName}…`
              }
              className="flex-1 py-2.5 px-4 border border-hairline rounded-md bg-canvas text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 disabled:opacity-60"
              aria-label="Pertanyaan"
            />
            <button
              type="submit"
              disabled={isProcessing || !input.trim()}
              className="flex items-center gap-2 px-4 py-2.5 bg-primary text-white rounded-md text-sm hover:bg-primary-active shadow-sm disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {isProcessing ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
              Kirim
            </button>
          </form>

          <p className="text-[11px] text-muted text-center">
            Mode simulasi (MOCK) — pipeline AI akan disambungkan ke backend pada Fase 3.
          </p>
        </div>
      </footer>
    </div>
  );
}
