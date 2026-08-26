import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import {
  X, Loader2, Database, Check, Plus, Server
} from 'lucide-react';
import { api } from '../../../services/api';
import toast from 'react-hot-toast';
import DbConnectionModal from './DbConnectionModal';

/**
 * Modal hubungkan/ganti database untuk satu cabang.
 * - List kartu bergaya katalog (ikon database berbeda dari list AI).
 * - "Tambah Database" membuka modal form di ATAS modal ini; setelah
 *   tersimpan, database baru LANGSUNG TERHUBUNG ke cabang ini.
 * - Tidak ada uji-koneksi manual: status nyata muncul otomatis
 *   di kolom Database setelah connect.
 */
const PAGE_SIZE = 6;

export default function ConnectDbModal({ isOpen, onClose, branchCode, currentConnId, onSaved }) {
  const [connections, setConnections] = useState([]);
  const [selectedId, setSelectedId] = useState(currentConnId || null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [showAddModal, setShowAddModal] = useState(false);
  const [page, setPage] = useState(1);

  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    setLoading(true);
    api.getDbConnections()
      .then((data) => {
        if (cancelled) return;
        // registry aktif; entri milik cabang ini tetap tampak walau nonaktif
        const filtered = data.filter(c => c.is_active || c.id === currentConnId);
        setConnections(filtered);
        // buka halaman yang memuat DB terpilih
        if (currentConnId) {
          const idx = filtered.findIndex(c => c.id === currentConnId);
          if (idx >= 0) setPage(Math.floor(idx / PAGE_SIZE) + 1);
        }
      })
      .catch(() => toast.error('Gagal memuat daftar database'))
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  if (!isOpen) return null;

  const isChange = !!currentConnId;

  const handleConnect = async () => {
    if (!selectedId) return;
    setSaving(true);
    try {
      await onSaved({
        branch_code: branchCode,
        db_connection_id: Number(selectedId),
        isChange,
      });
    } finally {
      setSaving(false);
    }
  };

  // Setelah tambah DB baru: langsung hubungkan ke cabang ini.
  const handleNewDatabase = async (payload) => {
    try {
      const result = await api.createDbConnection(payload);
      const newId = result?.id;
      if (!newId) throw new Error('id tidak dikembalikan');
      await onSaved({ branch_code: branchCode, db_connection_id: newId, isChange });
      setShowAddModal(false);
    } catch (e) {
      // biarkan parent/interceptor menampilkan detail; jangan tutup modal form
      toast.error(e.response?.data?.detail || 'Gagal menambahkan database');
    }
  };


  return (
    <>
      <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
        onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
        <motion.div
          initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}
          transition={{ type: 'spring', damping: 20, stiffness: 300 }}
          className="bg-white rounded-xl p-6 max-w-md w-full shadow-xl border border-hairline relative"
        >
          <button onClick={onClose} aria-label="Tutup" className="absolute right-4 top-4 text-muted hover:text-ink">
            <X size={20} />
          </button>

          <div className="flex items-center gap-3 mb-1">
            <span className="w-9 h-9 rounded-lg bg-violet-500/10 border border-violet-500/30 text-violet-500 flex items-center justify-center shrink-0">
              <Database size={18} />
            </span>
            <div>
              <h3 className="font-serif text-lg text-ink leading-tight">
                {isChange ? 'Ganti Database' : 'Hubungkan Database'}
              </h3>
              <p className="text-xs text-muted">Cabang <strong className="text-body">{branchCode}</strong></p>
            </div>
          </div>

          {/* LIST KARTU DATABASE — grid fix-size + paginasi */}
          {loading ? (
            <div className="flex items-center justify-center py-14 text-muted text-sm">
              <Loader2 size={18} className="animate-spin mr-2" /> Memuat…
            </div>
          ) : connections.length === 0 ? (
            <div className="text-center py-10">
              <p className="text-sm text-muted mb-3">Belum ada database terdaftar.</p>
            </div>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-2 min-h-[264px] content-start">
                {connections.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE).map((c) => {
                  const active = c.id === Number(selectedId);
                  return (
                    <button key={c.id} type="button" onClick={() => setSelectedId(c.id)}
                      className={`relative flex flex-col items-start gap-1.5 p-3 rounded-lg border text-left transition-all ${
                        active
                          ? 'border-primary bg-primary/5 ring-1 ring-primary/40'
                          : 'border-hairline hover:border-muted/40 hover:bg-surface-soft'
                      }`}>
                      <span className="flex items-center gap-2 w-full">
                        <span className={`w-9 h-9 rounded-lg flex items-center justify-center shrink-0 border ${
                          c.is_active ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-600'
                                      : 'bg-slate-400/10 border-slate-400/30 text-slate-400'
                        }`}>
                          <Server size={15} />
                        </span>
                        {active && (
                          <span className="ml-auto w-5 h-5 rounded-full bg-primary text-white flex items-center justify-center">
                            <Check size={12} strokeWidth={3} />
                          </span>
                        )}
                      </span>
                      <span className="block text-sm font-medium text-ink truncate w-full">{c.name}</span>
                      <span className="block text-[11px] text-muted truncate w-full">{c.db_name}</span>
                      <span className="flex items-center justify-between w-full mt-auto pt-1">
                        <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-surface-soft border border-hairline text-muted whitespace-nowrap">
                          {c.used_by} cabang
                        </span>
                        <span className={`w-1.5 h-1.5 rounded-full ${c.is_active ? 'bg-success' : 'bg-slate-300'}`} />
                      </span>
                    </button>
                  );
                })}
              </div>

              {/* paginasi dalam modal */}
              {connections.length > PAGE_SIZE && (
                <div className="flex items-center justify-between mt-3">
                  <span className="text-[10px] text-muted">
                    {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, connections.length)} dari {connections.length}
                  </span>
                  <span className="flex gap-1.5">
                    <button type="button" onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1}
                      className="px-2 py-1 border border-hairline rounded text-xs hover:bg-surface-soft disabled:opacity-40">‹</button>
                    <span className="px-2 py-1 text-xs text-muted">{page} / {Math.ceil(connections.length / PAGE_SIZE)}</span>
                    <button type="button" onClick={() => setPage(p => Math.min(Math.ceil(connections.length / PAGE_SIZE), p + 1))} disabled={page >= Math.ceil(connections.length / PAGE_SIZE)}
                      className="px-2 py-1 border border-hairline rounded text-xs hover:bg-surface-soft disabled:opacity-40">›</button>
                  </span>
                </div>
              )}
            </>
          )}

          {/* FOOTER: tambah + batal + hubungkan */}
          <div className="flex items-center justify-between mt-5 pt-4 border-t border-hairline">
            <button type="button" onClick={() => setShowAddModal(true)}
              className="flex items-center gap-1.5 text-xs font-medium text-primary hover:text-primary-active transition-colors">
              <Plus size={14} /> Tambah Database
            </button>
            <div className="flex gap-2">
              <button type="button" onClick={onClose}
                className="px-4 py-2 border border-hairline rounded-md text-sm hover:bg-surface-soft">Batal</button>
              <button type="button" onClick={handleConnect} disabled={!selectedId || saving}
                className="px-4 py-2 bg-primary text-white rounded-md text-sm hover:bg-primary-active disabled:opacity-50 flex items-center gap-2">
                {saving && <Loader2 size={14} className="animate-spin" />}
                Hubungkan
              </button>
            </div>
          </div>
        </motion.div>
      </div>

      {/* MODAL TAMBAH DATABASE (nested, di atas) */}
      {showAddModal && (
        <DbConnectionModal
          key="add-from-connect"
          isOpen
          onClose={() => setShowAddModal(false)}
          onSave={handleNewDatabase}
          editing={null}
          isSaving={false}
        />
      )}
    </>
  );
}
