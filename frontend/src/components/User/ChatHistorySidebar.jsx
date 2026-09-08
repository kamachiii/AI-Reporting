import { useState, useMemo } from 'react';
import { motion } from 'framer-motion';
import {
  MessageSquare, MessageSquarePlus, Trash2, Search, PanelLeftClose,
  History, Bot, X,
} from 'lucide-react';

function formatWaktuItem(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  const now = new Date();
  const diffDays = Math.floor((now - d) / (1000 * 60 * 60 * 24));

  if (diffDays === 0) {
    return d.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' });
  }
  if (diffDays === 1) return 'Kemarin';
  if (diffDays < 7) {
    return d.toLocaleDateString('id-ID', { weekday: 'short' });
  }
  return d.toLocaleDateString('id-ID', { day: 'numeric', month: 'short' });
}

function formatKelompokWaktu(dateStr) {
  if (!dateStr) return 'Sebelumnya';
  const d = new Date(dateStr);
  const now = new Date();
  const diffDays = Math.floor((now - d) / (1000 * 60 * 60 * 24));

  if (diffDays === 0) return 'Hari Ini';
  if (diffDays === 1) return 'Kemarin';
  if (diffDays <= 7) return '7 Hari Terakhir';
  return 'Lebih Lama';
}

export default function ChatHistorySidebar({
  conversations = [],
  activeId = null,
  onSelectConversation,
  onNewChat,
  onDeleteConversation,
  onClearAll,
  isOpen = true,
  onToggleOpen,
}) {
  const [searchQuery, setSearchQuery] = useState('');
  const [deleteConfirmId, setDeleteConfirmId] = useState(null);
  const [showClearConfirm, setShowClearConfirm] = useState(false);

  // Filter percakapan berdasarkan input pencarian
  const filtered = useMemo(() => {
    if (!searchQuery.trim()) return conversations;
    const q = searchQuery.toLowerCase();
    return conversations.filter((c) => (c.title || '').toLowerCase().includes(q));
  }, [conversations, searchQuery]);

  // Kelompokkan percakapan berdasarkan waktu
  const grouped = useMemo(() => {
    const groups = {
      'Hari Ini': [],
      Kemarin: [],
      '7 Hari Terakhir': [],
      'Lebih Lama': [],
    };

    filtered.forEach((conv) => {
      const g = formatKelompokWaktu(conv.updated_at || conv.created_at);
      if (groups[g]) {
        groups[g].push(conv);
      } else {
        groups['Lebih Lama'].push(conv);
      }
    });

    return groups;
  }, [filtered]);

  if (!isOpen) {
    return null;
  }

  return (
    <motion.aside
      initial={{ width: 0, opacity: 0 }}
      animate={{ width: 288, opacity: 1 }}
      exit={{ width: 0, opacity: 0 }}
      transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
      className="border-r border-hairline bg-surface-card flex flex-col h-full shrink-0 select-none overflow-hidden"
      aria-label="Riwayat Percakapan"
    >
      <div className="w-72 flex flex-col h-full shrink-0">
        {/* Header Sidebar: Compact & Refined */}
        <div className="h-14 px-3.5 border-b border-hairline/70 flex items-center justify-between bg-surface-card shrink-0">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded-md bg-primary/10 text-primary flex items-center justify-center border border-primary/20 shrink-0">
              <History size={13.5} />
            </div>
            <span className="text-[15px] font-serif font-medium text-ink tracking-tight">
              Arsip Percakapan
            </span>
            {conversations.length > 0 && (
              <span className="text-[10px] font-mono px-1.5 py-0.5 bg-canvas border border-hairline rounded-full text-muted font-medium">
                {conversations.length}
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={onToggleOpen}
            title="Ciutkan Sidebar (Ctrl+B)"
            className="p-1.5 rounded-md text-primary hover:text-primary-active hover:bg-surface-cream-strong transition-colors cursor-pointer"
          >
            <PanelLeftClose size={15} />
          </button>
        </div>

      {/* Action Bar: Sleek New Chat Button & Search */}
      <div className="p-3 border-b border-hairline/60 space-y-2 shrink-0">
        <button
          type="button"
          onClick={onNewChat}
          className="w-full flex items-center justify-between h-9 px-3 rounded-lg bg-canvas hover:bg-surface-cream-strong border border-hairline text-xs font-medium text-ink transition-all shadow-2xs group cursor-pointer hover:border-primary/40"
        >
          <span className="flex items-center gap-2">
            <MessageSquarePlus size={14} className="text-primary group-hover:scale-105 transition-transform" />
            <span>Percakapan Baru</span>
          </span>
          <span className="text-[10px] font-mono text-muted-soft border border-hairline px-1.5 py-0.5 rounded bg-surface-card font-medium">
            +
          </span>
        </button>

        {conversations.length > 0 && (
          <div className="relative">
            <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-soft" />
            <input
              type="text"
              id="search-chat-history"
              name="search-chat-history"
              aria-label="Cari topik percakapan"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Cari topik percakapan…"
              className="w-full h-8 pl-8 pr-7 text-xs bg-canvas/70 hover:bg-canvas focus:bg-canvas border border-hairline rounded-lg text-ink placeholder:text-muted-soft focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/15 transition-all font-sans font-normal"
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-soft hover:text-ink cursor-pointer"
              >
                <X size={12} />
              </button>
            )}
          </div>
        )}
      </div>

      {/* Daftar Sesi Percakapan */}
      <div className="flex-1 overflow-y-auto p-2 space-y-3 text-xs">
        {filtered.length === 0 ? (
          <div className="py-12 px-4 text-center space-y-3">
            <div className="w-10 h-10 rounded-xl bg-canvas border border-hairline flex items-center justify-center mx-auto text-primary shadow-2xs">
              <Bot size={20} />
            </div>
            <div className="space-y-1">
              <p className="text-sm font-serif font-medium text-ink">
                {searchQuery ? 'Topik Tidak Ditemukan' : 'Arsip Masih Kosong'}
              </p>
              <p className="text-[11px] text-muted-soft leading-relaxed max-w-[200px] mx-auto font-sans">
                {searchQuery
                  ? `Tidak ada percakapan yang cocok dengan "${searchQuery}".`
                  : 'Setiap analisis data yang Anda tanyakan akan tersimpan rapi di sini per sesi.'}
              </p>
            </div>
          </div>
        ) : (
          Object.entries(grouped).map(([groupName, items]) => {
            if (items.length === 0) return null;
            return (
              <div key={groupName} className="space-y-1">
                <div className="px-2 pt-2 pb-1 text-[10px] font-mono uppercase tracking-wider text-muted font-semibold flex items-center justify-between">
                  <span>{groupName}</span>
                  <span className="text-[9px] text-muted-soft font-normal">{items.length}</span>
                </div>
                {items.map((conv) => {
                  const isActive = activeId === conv.id;
                  const isConfirmingDelete = deleteConfirmId === conv.id;
                  const waktuItem = formatWaktuItem(conv.updated_at || conv.created_at);

                  return (
                    <div
                      key={conv.id}
                      className={`group relative flex items-center justify-between rounded-lg px-2.5 py-2 transition-all cursor-pointer ${
                        isActive
                          ? 'bg-surface-cream-strong text-ink font-medium border border-hairline/80 shadow-2xs'
                          : 'text-body hover:text-ink hover:bg-surface-cream-strong/60 border border-transparent font-normal'
                      }`}
                      onClick={() => !isConfirmingDelete && onSelectConversation(conv.id)}
                    >
                      <div className="flex items-center gap-2 min-w-0 pr-1 flex-1">
                        {isActive ? (
                          <span className="w-1.5 h-1.5 rounded-full bg-primary shrink-0" />
                        ) : (
                          <MessageSquare size={13} className="shrink-0 text-muted-soft group-hover:text-ink transition-colors" />
                        )}
                        <div className="min-w-0 flex-1">
                          <p
                            className={`truncate text-xs tracking-tight font-sans ${
                              isActive ? 'font-medium text-ink' : 'font-normal text-body group-hover:text-ink'
                            }`}
                            title={conv.title}
                          >
                            {conv.title || 'Percakapan Tanpa Judul'}
                          </p>
                        </div>
                      </div>

                      {/* Right side: Time tag or Delete button */}
                      <div className="shrink-0 flex items-center" onClick={(e) => e.stopPropagation()}>
                        {isConfirmingDelete ? (
                          <div className="flex items-center gap-1 bg-canvas border border-hairline p-0.5 rounded-md shadow-xs animate-fadeIn">
                            <button
                              type="button"
                              title="Hapus percakapan"
                              onClick={() => {
                                onDeleteConversation(conv.id);
                                setDeleteConfirmId(null);
                              }}
                              className="px-1.5 py-0.5 text-[10px] bg-rose-600 text-white rounded font-medium hover:bg-rose-700 transition-colors cursor-pointer"
                            >
                              Hapus
                            </button>
                            <button
                              type="button"
                              title="Batal"
                              onClick={() => setDeleteConfirmId(null)}
                              className="px-1.5 py-0.5 text-[10px] text-muted hover:text-ink rounded transition-colors cursor-pointer"
                            >
                              Batal
                            </button>
                          </div>
                        ) : (
                          <div className="flex items-center gap-1">
                            {waktuItem && (
                              <span className="text-[10px] font-mono text-muted-soft group-hover:hidden tabular-nums">
                                {waktuItem}
                              </span>
                            )}
                            <button
                              type="button"
                              title="Hapus Sesi"
                              onClick={() => setDeleteConfirmId(conv.id)}
                              className="hidden group-hover:flex p-1 rounded hover:bg-rose-50 hover:text-rose-700 text-muted-soft transition-all cursor-pointer"
                            >
                              <Trash2 size={12} />
                            </button>
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            );
          })
        )}
      </div>

      {/* Footer: Hapus Semua Riwayat & Info Sesi */}
      {conversations.length > 0 && (
        <div className="p-3 border-t border-hairline/80 shrink-0 flex items-center justify-between text-[11px] text-muted-soft font-sans">
          <span className="font-mono text-[10px]">
            {conversations.length} sesi tersimpan
          </span>

          {showClearConfirm ? (
            <div className="flex items-center gap-1.5 animate-fadeIn">
              <button
                type="button"
                onClick={() => {
                  onClearAll();
                  setShowClearConfirm(false);
                }}
                className="px-2 py-0.5 text-[10px] font-medium bg-rose-600 text-white rounded hover:bg-rose-700 transition-colors cursor-pointer"
              >
                Hapus Semua
              </button>
              <button
                type="button"
                onClick={() => setShowClearConfirm(false)}
                className="px-1.5 py-0.5 text-[10px] text-muted hover:text-ink transition-colors cursor-pointer"
              >
                Batal
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setShowClearConfirm(true)}
              className="hover:text-rose-700 transition-colors cursor-pointer flex items-center gap-1"
              title="Bersihkan seluruh riwayat cabang ini"
            >
              <Trash2 size={11} />
              <span>Bersihkan</span>
            </button>
          )}
        </div>
      )}
      </div>
    </motion.aside>
  );
}
