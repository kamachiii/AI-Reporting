import { useState, useMemo } from 'react';
import {
  MessageSquare, Plus, Trash2, Search, PanelLeftClose,
  Clock, Check, AlertCircle, X,
} from 'lucide-react';

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
    <aside
      className="w-72 border-r border-hairline bg-surface-card flex flex-col h-full shrink-0 transition-all duration-200 select-none"
      aria-label="Riwayat Percakapan"
    >
      {/* Header Sidebar: Judul + Tombol Tutup */}
      <div className="p-3.5 border-b border-hairline flex items-center justify-between">
        <div className="flex items-center gap-2 text-ink font-semibold text-sm">
          <Clock size={16} className="text-primary" />
          <span>Riwayat Chat</span>
        </div>
        <button
          type="button"
          onClick={onToggleOpen}
          title="Ciutkan Sidebar"
          className="p-1.5 rounded-lg text-muted hover:text-ink hover:bg-surface-soft transition-colors cursor-pointer"
        >
          <PanelLeftClose size={16} />
        </button>
      </div>

      {/* Tombol + Chat Baru */}
      <div className="p-3 border-b border-hairline">
        <button
          type="button"
          onClick={onNewChat}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-surface-dark text-white text-xs font-medium shadow-xs hover:bg-black transition-colors cursor-pointer"
        >
          <Plus size={14} className="text-white" />
          <span>Sesi Percakapan Baru</span>
        </button>

        {/* Input Pencarian Riwayat jika percakapan > 3 */}
        {conversations.length > 3 && (
          <div className="relative mt-2.5">
            <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Cari arsip sesi…"
              className="w-full pl-8 pr-7 py-1.5 text-xs bg-surface-soft/60 border border-hairline rounded-md text-ink placeholder:text-muted/60 focus:outline-none focus:ring-1 focus:ring-primary/40 focus:border-primary/60 transition-colors"
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted hover:text-ink cursor-pointer"
              >
                <X size={12} />
              </button>
            )}
          </div>
        )}
      </div>

      {/* Daftar Sesi Percakapan */}
      <div className="flex-1 overflow-y-auto p-2 space-y-4 text-xs">
        {filtered.length === 0 ? (
          <div className="text-center py-8 text-muted px-4">
            <MessageSquare size={22} className="mx-auto mb-2 opacity-30 text-muted" />
            <p className="font-medium text-ink">
              {searchQuery ? 'Tidak ada arsip cocok' : 'Belum ada arsip percakapan'}
            </p>
            <p className="text-[11px] mt-0.5 text-muted">
              {searchQuery ? 'Gunakan kata kunci lain' : 'Mulai eksplorasi dengan mengajukan pertanyaan'}
            </p>
          </div>
        ) : (
          Object.entries(grouped).map(([groupName, items]) => {
            if (items.length === 0) return null;
            return (
              <div key={groupName} className="space-y-1">
                <p className="px-2 text-[10px] font-semibold text-muted uppercase tracking-wider">
                  {groupName}
                </p>
                {items.map((conv) => {
                  const isActive = activeId === conv.id;
                  const isConfirmingDelete = deleteConfirmId === conv.id;

                  return (
                    <div
                      key={conv.id}
                      className={`group relative flex items-center justify-between rounded-lg px-2.5 py-2 transition-colors cursor-pointer ${
                        isActive
                          ? 'bg-white text-ink font-semibold border-l-2 border-l-primary border-y border-r border-hairline shadow-2xs'
                          : 'text-body hover:text-ink hover:bg-surface-soft/60 border border-transparent'
                      }`}
                      onClick={() => !isConfirmingDelete && onSelectConversation(conv.id)}
                    >
                      <div className="flex items-center gap-2 min-w-0 pr-2">
                        <MessageSquare
                          size={13}
                          className={`shrink-0 ${isActive ? 'text-primary' : 'text-muted/70'}`}
                        />
                        <span className="truncate text-xs tracking-tight" title={conv.title}>
                          {conv.title || 'Percakapan Tanpa Judul'}
                        </span>
                      </div>

                      {/* Tombol Hapus per Item */}
                      <div
                        className="shrink-0"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {isConfirmingDelete ? (
                          <div className="flex items-center gap-1">
                            <button
                              type="button"
                              title="Konfirmasi Hapus"
                              onClick={() => {
                                onDeleteConversation(conv.id);
                                setDeleteConfirmId(null);
                              }}
                              className="p-1 rounded bg-error/10 hover:bg-error text-error hover:text-white transition-colors cursor-pointer"
                            >
                              <Check size={11} />
                            </button>
                            <button
                              type="button"
                              title="Batal"
                              onClick={() => setDeleteConfirmId(null)}
                              className="p-1 rounded hover:bg-surface-soft text-muted hover:text-ink transition-colors cursor-pointer"
                            >
                              <X size={11} />
                            </button>
                          </div>
                        ) : (
                          <button
                            type="button"
                            title="Hapus Sesi"
                            onClick={() => setDeleteConfirmId(conv.id)}
                            className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-error/10 hover:text-error text-muted transition-all cursor-pointer"
                          >
                            <Trash2 size={12} />
                          </button>
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

      {/* Footer: Hapus Semua Riwayat */}
      {conversations.length > 0 && (
        <div className="p-2.5 border-t border-hairline">
          {showClearConfirm ? (
            <div className="p-2 rounded-lg bg-error/5 border border-error/20 space-y-1.5 text-center">
              <p className="text-[11px] text-error font-medium flex items-center justify-center gap-1">
                <AlertCircle size={12} />
                <span>Hapus seluruh riwayat cabang ini?</span>
              </p>
              <div className="flex items-center justify-center gap-1.5">
                <button
                  type="button"
                  onClick={() => {
                    onClearAll();
                    setShowClearConfirm(false);
                  }}
                  className="px-2.5 py-1 text-[11px] font-medium bg-error text-white rounded-md hover:bg-error/90 transition-colors cursor-pointer"
                >
                  Ya, Hapus Semua
                </button>
                <button
                  type="button"
                  onClick={() => setShowClearConfirm(false)}
                  className="px-2 py-1 text-[11px] text-muted hover:text-ink hover:bg-surface-soft rounded-md transition-colors cursor-pointer"
                >
                  Batal
                </button>
              </div>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setShowClearConfirm(true)}
              className="w-full flex items-center justify-center gap-1.5 px-2.5 py-1.5 text-xs text-muted hover:text-error hover:bg-error/5 rounded-lg transition-colors cursor-pointer"
            >
              <Trash2 size={12} />
              <span>Hapus Semua Riwayat</span>
            </button>
          )}
        </div>
      )}
    </aside>
  );
}
