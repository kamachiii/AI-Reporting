import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { X, Loader2, Eye, EyeOff } from 'lucide-react';

export default function UserModal({ isOpen, onClose, onSave, user, branches, isSaving }) {
  const isEditMode = !!user;

  const [form, setForm] = useState({
    username: '',
    email: '',
    password: '',
    role: 'user',
    branch_codes: [],
  });
  const [showPass, setShowPass] = useState(false);
  const [confirmError, setConfirmError] = useState('');

  useEffect(() => {
    if (isEditMode) {
      setForm({
        username: user.username,
        email: user.email || '',
        password: '', // kosong = tidak diubah
        role: user.role,
        branch_codes: user.branches || [],
      });
    } else {
      setForm({ username: '', email: '', password: '', role: 'user', branch_codes: [] });
    }
    setShowPass(false);
    setConfirmError('');
  }, [user, isEditMode]);

  if (!isOpen) return null;

  const toggleBranch = (code) => {
    setForm((prev) => ({
      ...prev,
      branch_codes: prev.branch_codes.includes(code)
        ? prev.branch_codes.filter((c) => c !== code)
        : [...prev.branch_codes, code],
    }));
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    // Username tidak boleh diubah saat edit (identitas & FK log)
    if (!isEditMode && form.username.trim().length < 3) {
      setConfirmError('Username minimal 3 karakter.');
      return;
    }
    if (!isEditMode && form.password.length < 6) {
      setConfirmError('Password minimal 6 karakter.');
      return;
    }
    setConfirmError('');
    const payload = {
      username: form.username.trim(),
      email: form.email.trim() || null,
      role: form.role,
      branch_codes: form.branch_codes,
    };
    if (!isEditMode || form.password) payload.password = form.password;
    onSave(payload);
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
      onClick={(e) => { if (e.target === e.currentTarget && !isSaving) onClose(); }}
    >
      <motion.div
        initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}
        transition={{ type: 'spring', damping: 20, stiffness: 300 }}
        className="bg-white rounded-xl p-6 max-w-lg w-full shadow-xl border border-hairline relative max-h-[90vh] overflow-y-auto"
      >
        <button onClick={onClose} disabled={isSaving} className="absolute right-4 top-4 text-muted hover:text-ink disabled:opacity-50">
          <X size={20} />
        </button>
        <h3 className="font-serif text-lg text-ink mb-4">
          {isEditMode ? `Edit User - ${user.username}` : 'Tambah User Baru'}
        </h3>

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Username */}
          <div>
            <label className="block text-sm font-medium text-ink mb-1">Username</label>
            <input
              type="text" value={form.username}
              onChange={(e) => setForm({ ...form, username: e.target.value })}
              disabled={isEditMode}
              required minLength={3}
              className="w-full px-3 py-2 border border-hairline rounded-md bg-canvas focus:ring-2 focus:ring-primary/30 disabled:bg-surface-soft disabled:text-muted"
              placeholder="cth: budi_jkt"
            />
            {isEditMode && <p className="text-xs text-muted mt-1">Username tidak dapat diubah.</p>}
          </div>

          {/* Email */}
          <div>
            <label className="block text-sm font-medium text-ink mb-1">Email <span className="text-muted font-normal">(opsional)</span></label>
            <input
              type="email" value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
              className="w-full px-3 py-2 border border-hairline rounded-md bg-canvas focus:ring-2 focus:ring-primary/30"
              placeholder="nama@perusahaan.com"
            />
          </div>

          {/* Password */}
          <div>
            <label className="block text-sm font-medium text-ink mb-1">
              Password {isEditMode && <span className="text-muted font-normal">(kosongkan jika tidak diubah)</span>}
            </label>
            <div className="relative">
              <input
                type={showPass ? 'text' : 'password'} value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                required={!isEditMode} minLength={6}
                className="w-full px-3 py-2 border border-hairline rounded-md bg-canvas focus:ring-2 focus:ring-primary/30 pr-10"
                placeholder="••••••••"
              />
              <button type="button" onClick={() => setShowPass(!showPass)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-muted hover:text-ink">
                {showPass ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>

          {/* Role */}
          <div>
            <label className="block text-sm font-medium text-ink mb-2">Role</label>
            <div className="flex gap-2 border border-hairline rounded-md p-1 bg-surface-soft">
              {[['user', 'User'], ['admin', 'Admin']].map(([val, label]) => (
                <button key={val} type="button"
                  onClick={() => setForm({ ...form, role: val })}
                  className={`flex-1 py-1.5 text-xs font-medium rounded transition-colors ${
                    form.role === val ? 'bg-white text-ink shadow-sm' : 'text-muted hover:text-ink'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {/* Branch assignment */}
          <div>
            <label className="block text-sm font-medium text-ink mb-2">Akses Cabang</label>
            {branches.length === 0 ? (
              <p className="text-sm text-muted bg-surface-soft rounded-md p-3">
                Belum ada cabang. Buat cabang dulu di menu "Perusahaan & Cabang".
              </p>
            ) : (
              <div className="grid grid-cols-2 gap-2 border border-hairline rounded-md p-3 max-h-36 overflow-y-auto">
                {branches.map((b) => (
                  <label key={b.code} className="flex items-center gap-2 text-sm cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={form.branch_codes.includes(b.code)}
                      onChange={() => toggleBranch(b.code)}
                      className="accent-[var(--color-primary)]"
                    />
                    <span className="text-body">{b.code}</span>
                    <span className="text-muted text-xs truncate">{b.name}</span>
                  </label>
                ))}
              </div>
            )}
          </div>

          {confirmError && (
            <div className="p-3 bg-red-50 border border-red-200 rounded-md text-error text-sm">{confirmError}</div>
          )}

          <div className="flex justify-end gap-2 pt-3 border-t border-hairline mt-2">
            <button type="button" onClick={onClose} disabled={isSaving}
              className="px-4 py-2 border border-hairline rounded-md text-sm hover:bg-surface-soft disabled:opacity-50">
              Batal
            </button>
            <button type="submit" disabled={isSaving || branches.length === 0}
              className="flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-md text-sm hover:bg-primary-active disabled:opacity-60">
              {isSaving && <Loader2 size={14} className="animate-spin" />}
              {isEditMode ? 'Simpan Perubahan' : 'Buat User'}
            </button>
          </div>
        </form>
      </motion.div>
    </div>
  );
}
