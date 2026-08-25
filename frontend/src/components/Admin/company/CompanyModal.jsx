import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Loader2 } from 'lucide-react';

export default function CompanyModal({ isOpen, onClose, onSave, company, isSaving }) {
  const [form, setForm] = useState(
    company || { code: '', name: '', address: '', is_active: true }
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
              {company ? 'Edit Perusahaan' : 'Tambah Perusahaan Baru'}
            </h3>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-ink mb-1">Kode Perusahaan</label>
                  <input
                    required
                    value={form.code}
                    onChange={(e) => setForm({ ...form, code: e.target.value })}
                    className="w-full px-3 py-2 border border-hairline rounded-md bg-canvas focus:ring-2 focus:ring-primary/30 disabled:bg-surface-soft disabled:text-muted"
                    placeholder="CMP_01"
                    disabled={!!company}
                  />
                  {company && (
                    <p className="text-xs text-muted mt-1">Kode tidak bisa diubah setelah dibuat.</p>
                  )}
                </div>
                <div>
                  <label className="block text-sm font-medium text-ink mb-1">Nama Perusahaan</label>
                  <input
                    required
                    value={form.name}
                    onChange={(e) => setForm({ ...form, name: e.target.value })}
                    className="w-full px-3 py-2 border border-hairline rounded-md bg-canvas focus:ring-2 focus:ring-primary/30"
                    placeholder="AutoDealer Corp"
                  />
                </div>
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
                  {company ? 'Update Perusahaan' : 'Simpan Perusahaan'}
                </button>
              </div>
            </form>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}