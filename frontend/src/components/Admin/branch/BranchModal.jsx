import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Loader2 } from 'lucide-react';

export default function BranchModal({ isOpen, onClose, onSave, branch, companies, isSaving }) {
  const [form, setForm] = useState(
    branch || { code: '', name: '', company_code: '', address: '', is_active: true }
  );

  const handleSubmit = (e) => {
    e.preventDefault();
    onSave(form);
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
          onClick={(e) => { if (e.target === e.currentTarget && !isSaving) onClose(); }}
        >
          <motion.div
            initial={{ scale: 0.95, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.95, opacity: 0 }}
            transition={{ type: 'spring', damping: 20, stiffness: 300 }}
            className="bg-white rounded-xl p-6 max-w-lg w-full shadow-xl border border-hairline relative"
          >
            <button aria-label="Tutup"
              onClick={onClose}
              disabled={isSaving}
              className="absolute right-4 top-4 text-muted hover:text-ink disabled:opacity-50"
            >
              <X size={20} />
            </button>
            <h3 className="font-serif text-lg text-ink mb-4">
              {branch ? 'Edit Cabang' : 'Tambah Cabang Baru'}
            </h3>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-ink mb-1">Kode Cabang</label>
                  <input
                    required
                    value={form.code}
                    onChange={(e) => setForm({ ...form, code: e.target.value })}
                    className="w-full px-3 py-2 border border-hairline rounded-md bg-canvas focus:ring-2 focus:ring-primary/30 disabled:bg-surface-soft disabled:text-muted"
                    placeholder="JKT_01"
                    disabled={!!branch}
                  />
                  {branch && (
                    <p className="text-xs text-muted mt-1">Kode tidak bisa diubah setelah dibuat.</p>
                  )}
                </div>
                <div>
                  <label className="block text-sm font-medium text-ink mb-1">Nama Cabang</label>
                  <input
                    required
                    value={form.name}
                    onChange={(e) => setForm({ ...form, name: e.target.value })}
                    className="w-full px-3 py-2 border border-hairline rounded-md bg-canvas focus:ring-2 focus:ring-primary/30"
                    placeholder="Jakarta"
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-ink mb-1">Perusahaan</label>
                  <select
                    required
                    value={form.company_code}
                    onChange={(e) => setForm({ ...form, company_code: e.target.value })}
                    className="w-full px-3 py-2 border border-hairline rounded-md bg-canvas focus:ring-2 focus:ring-primary/30 disabled:bg-surface-soft disabled:text-muted"
                    disabled={!!branch}
                  >
                    <option value="">Pilih Perusahaan</option>
                    {companies.filter(c => c.is_active).map(c => (
                      <option key={c.code} value={c.code}>{c.code} - {c.name}</option>
                    ))}
                  </select>
                  {branch && (
                    <p className="text-xs text-muted mt-1">Pindah perusahaan tidak bisa diubah.</p>
                  )}
                </div>
                <div>
                  <label className="block text-sm font-medium text-ink mb-1">Alamat</label>
                  <input
                    value={form.address}
                    onChange={(e) => setForm({ ...form, address: e.target.value })}
                    className="w-full px-3 py-2 border border-hairline rounded-md bg-canvas focus:ring-2 focus:ring-primary/30"
                    placeholder="Jl. Sudirman No. 1"
                  />
                </div>
              </div>
              <div className="flex justify-end gap-2 pt-3 border-t border-hairline mt-2">
                <button
                  type="button"
                  onClick={onClose}
                  disabled={isSaving}
                  className="px-4 py-2 border border-hairline rounded-md text-sm hover:bg-surface-soft disabled:opacity-50"
                >
                  Batal
                </button>
                <button
                  type="submit"
                  disabled={isSaving}
                  className="flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-md text-sm hover:bg-primary-active disabled:opacity-60"
                >
                  {isSaving && <Loader2 size={14} className="animate-spin" />}
                  {branch ? 'Update Cabang' : 'Simpan Cabang'}
                </button>
              </div>
            </form>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}