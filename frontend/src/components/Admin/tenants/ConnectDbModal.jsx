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
export default function ConnectDbModal({ isOpen, onClose, branchCode, currentConnId, onSaved }) {
  const [connections, setConnections] = useState([]);
  const [selectedId, setSelectedId] = useState(currentConnId || null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [showAddModal, setShowAddModal] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    setLoading(true);
    api.getDbConnections()
      .then((data) => {
        if (cancelled) return;
        // registry aktif; entri milik cabang ini tetap tampak walau nonaktif
        setConnections(data.filter(c => c.is_active || c.id === currentConnId));
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

          {/* LIST KARTU DATABASE */}
          <div className="mt-4 max-h-[300px] overflow-y-auto space-y-2 pr-1">
            {loading ? (
              <div className="flex items-center justify-center py-10 text-muted text-sm">
                <Loader2 size={18} className="animate-spin mr-2" /> Memuat…
              </div>
            ) : connections.length === 0 ? (
              <div className="text-center py-8">
                <p className="text-sm text-muted mb-3">Belum ada database terdaftar.</p>
              </div>
            ) : (
              connections.map((c) => {
                const active = c.id === Number(selectedId);
                return (
                  <button key={c.id} type="button" onClick={() => setSelectedId(c.id)}
                    className={`w-full flex items-center gap-3 p-3 rounded-lg border text-left transition-all ${
                      active
                        ? 'border-primary bg-primary/5 ring-1 ring-primary/40'
                        : 'border-hairline hover:border-muted/40 hover:bg-surface-soft'
                    }`}>
                    {/* ikon database dalam lingkaran — beda gaya dari list AI */}
                    <span className={`w-10 h-10 rounded-full flex items-center justify-center shrink-0 border ${
                      c.is_active ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-600'
                                  : 'bg-slate-400/10 border-slate-400/30 text-slate-400'
                    }`}>
                      <Server size={17} />
                    </span>

                    <span className="flex-1 min-w-0">
                      <span className="block text-sm font-medium text-ink truncate">{c.name}</span>
                      <span className="block text-xs text-muted truncate">{c.db_name} @ {c.db_host}:{c.db_port}</span>
                    </span>

                    <span className="flex items-center gap-2 shrink-0">
                      <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-surface-soft border border-hairline text-muted whitespace-nowrap">
                        {c.used_by} cabang
                      </span>
                      {active && (
                        <span className="w-5 h-5 rounded-full bg-primary text-white flex items-center justify-center">
                          <Check size={12} strokeWidth={3} />
                        </span>
                      )}
                    </span>
                  </button>
                );
              })
            )}
          </div>

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
