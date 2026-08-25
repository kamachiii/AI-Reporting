import { useState } from 'react';
import { motion } from 'framer-motion';
import { X } from 'lucide-react';

/**
 * Modal tambah tenant baru (koneksi DB per cabang).
 * Form dimiliki modal ini; parent menerima payload via onSubmit(form).
 */
export default function TenantFormModal({ isOpen, onClose, onSubmit }) {
  const [form, setForm] = useState({
    branch_code: '',
    db_host: '',
    db_port: '5432',
    db_name: '',
    db_username: '',
    db_password: '',
  });

  if (!isOpen) return null;

  const handleSubmit = (e) => {
    e.preventDefault();
    onSubmit({
      ...form,
      db_port: Number(form.db_port) || 5432,
    });
    // reset untuk pemakaian berikutnya
    setForm({ branch_code: '', db_host: '', db_port: '5432', db_name: '', db_username: '', db_password: '' });
  };

  const field = "w-full px-3 py-2 border border-hairline rounded-md bg-canvas focus:ring-2 focus:ring-primary/30";
  const label = "block text-sm font-medium text-ink mb-1";

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <motion.div
        initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}
        transition={{ type: 'spring', damping: 20, stiffness: 300 }}
        className="bg-white rounded-xl p-6 max-w-lg w-full shadow-xl border border-hairline relative"
      >
        <button onClick={onClose} className="absolute right-4 top-4 text-muted hover:text-ink">
          <X size={20} />
        </button>
        <h3 className="font-serif text-lg text-ink mb-4">Tambah Tenant Baru</h3>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={label}>Kode Cabang</label>
              <input required value={form.branch_code}
                onChange={(e) => setForm({ ...form, branch_code: e.target.value.toUpperCase() })}
                className={field} placeholder="JKT_01" />
            </div>
            <div>
              <label className={label}>Database Port</label>
              <input required type="number" value={form.db_port}
                onChange={(e) => setForm({ ...form, db_port: e.target.value })}
                className={field} placeholder="5432" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={label}>Database Host</label>
              <input required value={form.db_host}
                onChange={(e) => setForm({ ...form, db_host: e.target.value })}
                className={field} placeholder="localhost atau domain" />
            </div>
            <div>
              <label className={label}>Database Name</label>
              <input required value={form.db_name}
                onChange={(e) => setForm({ ...form, db_name: e.target.value })}
                className={field} placeholder="nama_database" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={label}>Username DB</label>
              <input required value={form.db_username}
                onChange={(e) => setForm({ ...form, db_username: e.target.value })}
                className={field} placeholder="postgres" />
            </div>
            <div>
              <label className={label}>Password DB</label>
              <input required type="password" value={form.db_password}
                onChange={(e) => setForm({ ...form, db_password: e.target.value })}
                className={field} placeholder="••••••••" />
            </div>
          </div>
          <div className="flex justify-end gap-2 pt-3 border-t border-hairline mt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 border border-hairline rounded-md text-sm hover:bg-surface-soft">Batal</button>
            <button type="submit" className="px-4 py-2 bg-primary text-white rounded-md text-sm hover:bg-primary-active">Simpan Tenant</button>
          </div>
        </form>
      </motion.div>
    </div>
  );
}
