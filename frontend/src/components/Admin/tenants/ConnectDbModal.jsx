import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { X, Loader2, Database } from 'lucide-react';
import { api } from '../../../services/api';
import toast from 'react-hot-toast';

/**
 * Modal hubungkan/ganti database untuk satu cabang.
 * Admin cukup MEMILIH database dari registry (bukan mengisi kredensial).
 */
export default function ConnectDbModal({ isOpen, onClose, branchCode, currentConnId, onSaved }) {
  const [connections, setConnections] = useState([]);
  const [selectedId, setSelectedId] = useState(currentConnId || '');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      try {
        const data = await api.getDbConnections();
        if (!cancelled) {
          // hanya tampilkan registry aktif; entri cabang ini sendiri tetap tampak
          setConnections(data.filter(c => c.is_active || c.id === currentConnId));
        }
      } catch {
        toast.error('Gagal memuat daftar database');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  if (!isOpen) return null;

  const handleTest = async () => {
    if (!selectedId) return;
    setTesting(true);
    try {
      const result = await api.testDbConnection(Number(selectedId));
      result.status === 'connected'
        ? toast.success('Koneksi berhasil!')
        : toast.error(`Gagal: ${result.message || ''}`);
    } catch {
      toast.error('Gagal menguji koneksi');
    } finally {
      setTesting(false);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!selectedId) return;
    setSaving(true);
    try {
      if (currentConnId) {
        await onSaved({ db_connection_id: Number(selectedId), isChange: true });
      } else {
        await onSaved({ branch_code: branchCode, db_connection_id: Number(selectedId), isChange: false });
      }
    } finally {
      setSaving(false);
    }
  };

  return (
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
        <div className="flex items-center gap-2 mb-1">
          <span className="w-8 h-8 rounded-full bg-primary/10 text-primary flex items-center justify-center">
            <Database size={16} />
          </span>
          <h3 className="font-serif text-lg text-ink">
            {currentConnId ? 'Ganti Database' : 'Hubungkan Database'}
          </h3>
        </div>
        <p className="text-xs text-muted mb-4">Cabang <strong className="text-body">{branchCode}</strong></p>

        {loading ? (
          <div className="flex items-center justify-center py-8 text-muted text-sm">
            <Loader2 size={18} className="animate-spin mr-2" /> Memuat daftar database…
          </div>
        ) : connections.length === 0 ? (
          <div className="text-sm text-muted py-6 text-center">
            Belum ada database terdaftar.<br />
            Daftarkan dulu di bagian <strong>Database Terdaftar</strong> di atas.
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-3">
            <label className="block text-sm font-medium text-ink">Pilih Database</label>
            <select
              value={selectedId}
              onChange={(e) => setSelectedId(e.target.value)}
              required
              className="w-full px-3 py-2 border border-hairline rounded-md bg-canvas text-sm focus:ring-2 focus:ring-primary/30"
            >
              <option value="" disabled>— Pilih —</option>
              {connections.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} ({c.db_name} @ {c.db_host}){!c.is_active ? ' [nonaktif]' : ''}
                </option>
              ))}
            </select>

            <button type="button" onClick={handleTest} disabled={!selectedId || testing}
              className="text-xs text-primary hover:underline disabled:opacity-50 flex items-center gap-1">
              {testing && <Loader2 size={12} className="animate-spin" />} Uji koneksi dulu
            </button>

            <div className="flex justify-end gap-2 pt-3 border-t border-hairline mt-2">
              <button type="button" onClick={onClose} className="px-4 py-2 border border-hairline rounded-md text-sm hover:bg-surface-soft">Batal</button>
              <button type="submit" disabled={saving || !selectedId}
                className="px-4 py-2 bg-primary text-white rounded-md text-sm hover:bg-primary-active disabled:opacity-50 flex items-center gap-2">
                {saving && <Loader2 size={14} className="animate-spin" />}
                {currentConnId ? 'Simpan Perubahan' : 'Hubungkan'}
              </button>
            </div>
          </form>
        )}
      </motion.div>
    </div>
  );
}
