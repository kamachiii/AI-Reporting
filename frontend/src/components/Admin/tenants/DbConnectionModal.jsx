import { useState } from 'react';
import { motion } from 'framer-motion';
import { X, Loader2 } from 'lucide-react';

/**
 * Modal daftarkan / edit database di registry.
 * Kredensial diisi sekali di sini; cabang cukup memilih namanya.
 */
export default function DbConnectionModal({ isOpen, onClose, onSave, editing, isSaving }) {
  const isEdit = !!editing;

  const [form, setForm] = useState(
    editing
      ? {
          name: editing.name,
          db_host: editing.db_host,
          db_port: String(editing.db_port),
          db_name: editing.db_name,
          db_username: editing.db_username,
          db_password: '', // kosong = tidak diubah
        }
      : { name: '', db_host: '', db_port: '5432', db_name: '', db_username: '', db_password: '' }
  );

  if (!isOpen) return null;

  const handleSubmit = (e) => {
    e.preventDefault();
    onSave({
      ...form,
      db_port: Number(form.db_port) || 5432,
      id: editing?.id,
    });
  };

  const field = "w-full px-3 py-2 border border-hairline rounded-md bg-canvas focus:ring-2 focus:ring-primary/30 text-sm";
  const label = "block text-sm font-medium text-ink mb-1";

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <motion.div
        initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}
        transition={{ type: 'spring', damping: 20, stiffness: 300 }}
        className="bg-white rounded-xl p-6 max-w-lg w-full shadow-xl border border-hairline relative max-h-[90vh] overflow-y-auto"
      >
        <button onClick={onClose} aria-label="Tutup" className="absolute right-4 top-4 text-muted hover:text-ink">
          <X size={20} />
        </button>
        <h3 className="font-serif text-lg text-ink mb-4">
          {isEdit ? 'Edit Database Terdaftar' : 'Daftarkan Database'}
        </h3>
        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className={label}>Nama (untuk dipilih admin cabang)</label>
            <input required value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              className={field} placeholder="mis. DB Penjualan Pusat" />
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div className="col-span-2">
              <label className={label}>Host</label>
              <input required value={form.db_host}
                onChange={(e) => setForm({ ...form, db_host: e.target.value })}
                className={field} placeholder="localhost / domain" />
            </div>
            <div>
              <label className={label}>Port</label>
              <input required type="number" value={form.db_port}
                onChange={(e) => setForm({ ...form, db_port: e.target.value })}
                className={field} placeholder="5432" />
            </div>
          </div>
          <div>
            <label className={label}>Nama Database</label>
            <input required value={form.db_name}
              onChange={(e) => setForm({ ...form, db_name: e.target.value })}
              className={field} placeholder="nama_database" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={label}>Username</label>
              <input required value={form.db_username}
                onChange={(e) => setForm({ ...form, db_username: e.target.value })}
                className={field} placeholder="postgres" />
            </div>
            <div>
              <label className={label}>
                Password {isEdit && <span className="text-muted font-normal">(kosongkan jika tetap)</span>}
              </label>
              <input type="password" value={form.db_password}
                onChange={(e) => setForm({ ...form, db_password: e.target.value })}
                className={field} placeholder="••••••••" required={!isEdit} />
            </div>
          </div>
          <div className="flex justify-end gap-2 pt-3 border-t border-hairline mt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 border border-hairline rounded-md text-sm hover:bg-surface-soft">Batal</button>
            <button type="submit" disabled={isSaving}
              className="px-4 py-2 bg-primary text-white rounded-md text-sm hover:bg-primary-active disabled:opacity-50 flex items-center gap-2">
              {isSaving && <Loader2 size={14} className="animate-spin" />}
              {isEdit ? 'Simpan Perubahan' : 'Daftarkan'}
            </button>
          </div>
        </form>
      </motion.div>
    </div>
  );
}
