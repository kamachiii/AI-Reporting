import { useState } from 'react';
import { motion } from 'framer-motion';
import { X, Loader2, Gauge } from 'lucide-react';

const PRESETS = [25000, 50000, 100000, 250000];

export default function BranchQuotaModal({ isOpen, onClose, branch, onSave, isSaving }) {
  const [quota, setQuota] = useState(branch?.daily_token_quota || 50000);
  const [error, setError] = useState('');

  if (!isOpen || !branch) return null;

  const handleSubmit = (e) => {
    e.preventDefault();
    const val = Number(quota);
    if (!val || val < 1000 || val > 5000000) {
      setError('Batas kuota harian harus antara 1.000 dan 5.000.000 token.');
      return;
    }
    setError('');
    onSave(branch.branch_code, val);
  };

  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
      onClick={(e) => { if (e.target === e.currentTarget && !isSaving) onClose(); }}
    >
      <motion.div
        initial={{ scale: 0.95, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ type: 'spring', damping: 20, stiffness: 300 }}
        className="bg-white rounded-xl p-6 max-w-md w-full shadow-xl border border-hairline relative"
      >
        <button
          aria-label="Tutup"
          onClick={onClose}
          disabled={isSaving}
          className="absolute right-4 top-4 text-muted hover:text-ink disabled:opacity-50"
        >
          <X size={20} />
        </button>

        <div className="flex items-center gap-2 mb-2 text-primary">
          <Gauge size={20} />
          <h3 className="font-serif text-lg text-ink">Ubah Batas Kuota Token Harian</h3>
        </div>

        <p className="text-xs text-muted mb-4">
          Atur kuota token AI harian untuk cabang <strong className="text-ink">{branch.branch_name} ({branch.branch_code})</strong>. Jika kuota habis, kueri non-memory akan dibatasi demi kontrol biaya.
        </p>

        {error && (
          <div className="mb-4 p-2.5 bg-error/10 border border-error/20 rounded-md text-xs text-error">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-ink mb-1">
              Batas Kuota Harian (Token)
            </label>
            <input
              type="number"
              min="1000"
              max="5000000"
              step="1000"
              value={quota}
              onChange={(e) => setQuota(e.target.value)}
              className="w-full px-3 py-2 border border-hairline rounded-md text-sm text-ink focus:outline-none focus:border-primary font-mono"
              required
            />
          </div>

          {/* Quick presets */}
          <div>
            <span className="block text-xs text-muted mb-1.5">Preset Cepat:</span>
            <div className="flex gap-2 flex-wrap">
              {PRESETS.map((p) => (
                <button
                  type="button"
                  key={p}
                  onClick={() => setQuota(p)}
                  className={`px-2.5 py-1 text-xs rounded border transition-colors ${
                    Number(quota) === p
                      ? 'bg-primary text-white border-primary font-medium'
                      : 'border-hairline text-ink hover:bg-surface-soft'
                  }`}
                >
                  {p.toLocaleString('id-ID')}
                </button>
              ))}
            </div>
          </div>

          <div className="pt-2 flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={isSaving}
              className="px-4 py-2 text-sm rounded-md border border-hairline text-muted hover:bg-surface-soft transition-colors"
            >
              Batal
            </button>
            <button
              type="submit"
              disabled={isSaving}
              className="px-4 py-2 text-sm rounded-md bg-primary text-white font-medium hover:bg-primary/90 transition-colors flex items-center gap-1.5 disabled:opacity-50"
            >
              {isSaving && <Loader2 size={14} className="animate-spin" />}
              Simpan Kuota
            </button>
          </div>
        </form>
      </motion.div>
    </div>
  );
}
