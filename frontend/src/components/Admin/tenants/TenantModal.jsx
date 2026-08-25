import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Loader2, Eye, EyeOff, Wifi, CheckCircle, XCircle } from 'lucide-react';
import { notify } from '../../../utils/notification';
import { api } from '../../../services/api';

export default function TenantModal({ 
  isOpen, 
  onClose, 
  onSave, 
  onTest, 
  branchCode, 
  tenant, 
  isSaving,
  isTesting 
}) {
  const isEditMode = !!tenant;

  // Inisialisasi form
  const [form, setForm] = useState(
    tenant 
      ? { ...tenant, db_password: '' }
      : { 
          db_host: '', 
          db_port: '5432', 
          db_name: '', 
          db_username: '', 
          db_password: '' 
        }
  );
  
  // Sync saat tenant berubah
  useEffect(() => {
    setForm(
      tenant 
        ? { ...tenant, db_password: '' }
        : { db_host: '', db_port: '5432', db_name: '', db_username: '', db_password: '' }
    );
  }, [tenant]);
  
  const [showPass, setShowPass] = useState(false);
  const [testResult, setTestResult] = useState(null);

  const handleTestConnection = async () => {
    if (!form.db_host || !form.db_name || !form.db_username) {
      notify.error('Harap isi Host, DB Name, dan Username terlebih dahulu.');
      return;
    }

    setTestResult(null);
    try {
      let result;
      if (isEditMode) {
        // Mode Edit
        result = await onTest(branchCode, form);
      } else {
        // Mode Create
        result = await api.testTenantDraft({
          ...form,
          branch_code: branchCode
        });
      }
      
      setTestResult(result);
      if (result.status === 'connected') {
        notify.success('Koneksi berhasil!');
      } else {
        notify.error(`Koneksi gagal: ${result.message || ''}`);
      }
    } catch (e) {
      setTestResult({ status: 'disconnected', message: 'Terjadi kesalahan' });
      notify.error('Gagal melakukan uji koneksi');
    }
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    if (isEditMode && !form.db_password) {
      const { db_password, ...rest } = form;
      onSave(rest);
    } else {
      onSave(form);
    }
  };

  const handleChange = (e) => {
    const { name, value } = e.target;
    setForm(prev => ({ ...prev, [name]: value }));
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
              disabled={isSaving || isTesting}
              className="absolute right-4 top-4 text-muted hover:text-ink disabled:opacity-50"
            >
              <X size={20} />
            </button>
            <h3 className="font-serif text-lg text-ink mb-4">
              Konfigurasi Database - {branchCode}
            </h3>
            <form onSubmit={handleSubmit} className="space-y-4">
              
              {/* Baris 1: Host & Port */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-ink mb-1">Database Host</label>
                  <input
                    required
                    name="db_host"
                    value={form.db_host}
                    onChange={handleChange}
                    className="w-full px-3 py-2 border border-hairline rounded-md bg-canvas focus:ring-2 focus:ring-primary/30"
                    placeholder="localhost atau domain"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-ink mb-1">Port</label>
                  <input
                    required
                    type="number"
                    name="db_port"
                    value={form.db_port}
                    onChange={handleChange}
                    className="w-full px-3 py-2 border border-hairline rounded-md bg-canvas focus:ring-2 focus:ring-primary/30"
                    placeholder="5432"
                  />
                </div>
              </div>

              {/* Baris 2: DB Name & Username */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-ink mb-1">Database Name</label>
                  <input
                    required
                    name="db_name"
                    value={form.db_name}
                    onChange={handleChange}
                    className="w-full px-3 py-2 border border-hairline rounded-md bg-canvas focus:ring-2 focus:ring-primary/30"
                    placeholder="nama_database"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-ink mb-1">Username DB</label>
                  <input
                    required
                    name="db_username"
                    value={form.db_username}
                    onChange={handleChange}
                    className="w-full px-3 py-2 border border-hairline rounded-md bg-canvas focus:ring-2 focus:ring-primary/30"
                    placeholder="postgres"
                  />
                </div>
              </div>

              {/* Baris 3: Password */}
              <div>
                <label className="block text-sm font-medium text-ink mb-1">
                  Password {isEditMode && <span className="text-muted font-normal">(kosongkan jika tidak ingin mengubah)</span>}
                </label>
                <div className="relative">
                  <input
                    type={showPass ? 'text' : 'password'}
                    name="db_password"
                    value={form.db_password}
                    onChange={handleChange}
                    className="w-full px-3 py-2 border border-hairline rounded-md bg-canvas focus:ring-2 focus:ring-primary/30 pr-10"
                    placeholder={'••••••••'}
                    required={!isEditMode}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPass(!showPass)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-muted hover:text-ink"
                  >
                    {showPass ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>

              {/* Tombol Uji Koneksi & Hasil */}
              <div className="flex items-center gap-4 pt-1">
                <button
                  type="button"
                  onClick={handleTestConnection}
                  disabled={isTesting || isSaving}
                  className="flex items-center gap-2 px-4 py-2 border border-hairline rounded-md text-sm bg-surface-soft hover:bg-hairline transition-colors disabled:opacity-50"
                >
                  {isTesting ? <Loader2 size={14} className="animate-spin" /> : <Wifi size={14} />}
                  {isTesting ? 'Menguji...' : 'Uji Koneksi'}
                </button>
                {testResult && (
                  <div className={`text-sm flex items-center gap-1 ${testResult.status === 'connected' ? 'text-success' : 'text-error'}`}>
                    {testResult.status === 'connected' ? <CheckCircle size={14} /> : <XCircle size={14} />}
                    {testResult.status === 'connected' ? 'Koneksi berhasil!' : `Gagal: ${testResult.message || ''}`}
                  </div>
                )}
              </div>

              {/* Tombol Batal / Simpan */}
              <div className="flex justify-end gap-2 pt-3 border-t border-hairline mt-4">
                <button
                  type="button"
                  onClick={onClose}
                  disabled={isSaving || isTesting}
                  className="px-4 py-2 border border-hairline rounded-md text-sm hover:bg-surface-soft disabled:opacity-50"
                >
                  Batal
                </button>
                <button
                  type="submit"
                  disabled={isSaving || isTesting}
                  className="flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-md text-sm hover:bg-primary-active disabled:opacity-60"
                >
                  {isSaving && <Loader2 size={14} className="animate-spin" />}
                  {isEditMode ? 'Update Konfigurasi' : 'Simpan Konfigurasi'}
                </button>
              </div>
            </form>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}