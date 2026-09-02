import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { X, CheckCircle, XCircle, Eye, EyeOff, RefreshCw, Loader2, Info, Zap, Cpu, Wifi } from 'lucide-react';
import ModelPickerModal from './ModelPickerModal';
import TargetPicker from './TargetPicker';
import { api } from '../../../services/api';
import toast from 'react-hot-toast';

/**
 * Modal tambah/edit konfigurasi AI.
 * State form dimiliki modal ini; parent menerima hasil via onSave(payload).
 * editing (object | null) menentukan mode edit/tambah.
 */
export default function AIConfigModal({ isOpen, onClose, onSave, editing }) {
  const isEdit = !!editing;

  const [form, setForm] = useState(
    editing
      ? {
          scope: editing.scope,
          target_id: editing.target_id || '',
          provider: editing.provider || '',
          api_key: '', // kosong = tidak diubah
          model: editing.model,
          temperature: editing.temperature,
          api_type: editing.api_type || 'openai',
          base_url: editing.base_url || 'https://api.openai.com/v1',
        }
      : {
          scope: 'global',
          target_id: '',
          provider: '',
          api_key: '',
          model: '',
          temperature: 0.7,
          api_type: 'openai',
          base_url: '', // kosong: wajib diisi sesuai provider (default OpenAI menyesatkan utk provider lain)
        }
  );
  const [showPass, setShowPass] = useState(false);
  const [fetchingModels, setFetchingModels] = useState(false);
  const [models, setModels] = useState([]);
  const [isTesting, setIsTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);
  const [isModelPickerOpen, setIsModelPickerOpen] = useState(false);
  const [targetOptions, setTargetOptions] = useState([]);

  // Muat opsi TargetPicker sesuai scope (sekali per perubahan scope)
  useEffect(() => {
    if (!isOpen || form.scope === 'global') { setTargetOptions([]); return; }
    let cancelled = false;
    if (form.scope === 'tenant') {
      api.getBranchesWithTenants().then((rows) => {
        if (cancelled) return;
        setTargetOptions((rows || [])
          .filter((r) => r.is_active && r.db_host)  // hanya yang ter-hubung database
          .map((r) => ({ value: r.code, label: `${r.code} — ${r.name}`, sub: `${r.db_name_label || ''}` })));
      }).catch(() => setTargetOptions([]));
    } else if (form.scope === 'user') {
      api.getUsers().then((rows) => {
        if (cancelled) return;
        setTargetOptions((rows || [])
          .filter((u) => u.role === 'user')
          .map((u) => ({ value: u.username, label: u.username, sub: u.email || '' })));
      }).catch(() => setTargetOptions([]));
    }
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, form.scope]);

  if (!isOpen) return null;

  const handleTestDraft = async () => {
    if (!isEdit && !form.api_key) {
      toast.error('Masukkan API Key terlebih dahulu');
      return;
    }
    if (form.api_type === 'openai' && !form.base_url) {
      toast.error('Base URL wajib diisi');
      return;
    }
    setTestResult(null);
    setIsTesting(true);
    try {
      const result = await api.testAIConfigDraft(form.api_type, form.base_url, form.api_key, isEdit ? editing.id : null);
      setTestResult(result);
    } catch {
      setTestResult({ status: 'disconnected', message: 'Gagal melakukan uji koneksi' });
    } finally {
      setIsTesting(false);
    }
  };

  const handleFetchModels = async () => {
    if (!isEdit && !form.api_key) {
      toast.error('Masukkan API Key terlebih dahulu');
      return;
    }
    if (form.api_type === 'openai' && !form.base_url) {
      toast.error('Base URL wajib diisi');
      return;
    }
    setFetchingModels(true);
    setModels([]);
    try {
      const result = await api.fetchProviderModels(form.provider || 'Custom', form.api_key, form.api_type, form.base_url, isEdit ? editing.id : null);
      setModels(result.models || []);
      if (result.models?.length > 0) {
        toast.success(`Berhasil mengambil ${result.models.length} model!`);
      } else if (form.api_type === 'anthropic') {
        toast('Untuk Anthropic, silakan ketik nama model secara manual.', { icon: 'ℹ️' });
      } else {
        toast('Tidak ada model yang ditemukan untuk provider ini.', { icon: '⚠️' });
      }
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Gagal mengambil model');
    } finally {
      setFetchingModels(false);
    }
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    // Base URL wajib utk api_type openai — default OpenAI menyesatkan utk provider lain
    // (insiden 2026-09-02: key ByNara + base_url OpenAI = gagal test & fetch model).
    if (form.api_type === 'openai' && !form.base_url.trim()) {
      toast.error('Base URL wajib diisi (harus cocok dengan provider API key-mu)');
      return;
    }
    // Payload identik dengan skema backend; password/api_key kosong saat edit = tidak diubah
    onSave({ ...form, target_id: form.target_id.trim() });
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <motion.div
        initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}
        transition={{ type: 'spring', damping: 20, stiffness: 300 }}
        className="bg-white rounded-xl p-6 max-w-lg w-full shadow-xl border border-hairline relative max-h-[90vh] overflow-y-auto"
      >
        <button onClick={onClose} aria-label="Tutup" className="absolute right-4 top-4 text-muted hover:text-ink">
          <X size={20} />
        </button>
        <h3 className="font-serif text-lg text-ink mb-4">
          {isEdit ? 'Edit Konfigurasi AI' : 'Tambah Konfigurasi AI'}
        </h3>
        <form onSubmit={handleSubmit} className="space-y-3">

          {/* Scope */}
          <div>
            <label className="block text-sm font-medium text-ink mb-2">Scope</label>
            <div className="flex gap-2 border border-hairline rounded-md p-1 bg-surface-soft">
              {['global', 'tenant', 'user'].map((s) => (
                <button key={s} type="button"
                  onClick={() => setForm({ ...form, scope: s, target_id: '' })}
                  className={`flex-1 py-1.5 text-xs font-medium rounded transition-colors ${
                    form.scope === s ? 'bg-white text-ink shadow-sm' : 'text-muted hover:text-ink'
                  }`}>
                  {s === 'global' ? 'Global' : s === 'tenant' ? 'Tenant' : 'User'}
                </button>
              ))}
            </div>
          </div>

          {/* Target — autocomplete dari data nyata (bukan input bebas) */}
          {form.scope !== 'global' && (
            <div className="pt-1 pb-2">
              <label className="block text-sm font-medium text-ink mb-1">
                {form.scope === 'tenant' ? 'Cabang Terhubung' : 'User (role user)'}
              </label>
              <TargetPicker
                value={form.target_id}
                onChange={(v) => setForm({ ...form, target_id: v })}
                options={targetOptions}
                placeholder={form.scope === 'tenant' ? 'Pilih cabang...' : 'Pilih user...'}
              />
              {targetOptions.length === 0 && (
                <p className="text-xs text-muted mt-1">
                  {form.scope === 'tenant'
                    ? 'Belum ada cabang terhubung database — hubungkan dulu di menu Database & Tenant.'
                    : 'Belum ada user role "user" terdaftar.'}
                </p>
              )}
            </div>
          )}

          {/* Provider & API Type */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-ink mb-1">Nama Provider</label>
              <input type="text" value={form.provider} onChange={(e) => setForm({ ...form, provider: e.target.value })}
                placeholder="OpenAI / AgentRouter"
                className="w-full text-sm px-3 py-2 border border-hairline rounded-md bg-canvas focus:ring-2 focus:ring-primary/30" />
            </div>
            <div>
              <label className="block text-sm font-medium text-ink mb-1">Tipe API</label>
              <div className="flex gap-2 border border-hairline rounded-md p-1 bg-surface-soft">
                <button type="button" onClick={() => setForm({ ...form, api_type: 'openai', model: '' })}
                  className={`flex-1 py-1.5 text-xs font-medium rounded transition-colors flex items-center justify-center gap-1 ${
                    form.api_type === 'openai' ? 'bg-primary text-white shadow-sm' : 'text-muted hover:text-ink'
                  }`}>
                  <Zap size={14} /> OpenAI
                </button>
                <button type="button" onClick={() => setForm({ ...form, api_type: 'anthropic', model: '' })}
                  className={`flex-1 py-1.5 text-xs font-medium rounded transition-colors flex items-center justify-center gap-1 ${
                    form.api_type === 'anthropic' ? 'bg-primary text-white shadow-sm' : 'text-muted hover:text-ink'
                  }`}>
                  <Cpu size={14} /> Anthropic
                </button>
              </div>
            </div>
          </div>

          {/* Base URL & API Key */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-ink mb-1">Base URL</label>
              <input type="text" value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })}
                placeholder="https://provider-kamu.com/v1"
                className="w-full px-3 py-2 border border-hairline rounded-md bg-canvas focus:ring-2 focus:ring-primary/30 h-9 text-sm" />
              <p className="text-[11px] text-muted mt-1">
                Harus cocok dengan provider API key-mu (contoh Groq: <code>https://api.groq.com/openai/v1</code>).
                Salah kombinasi = gagal test &amp; fetch model.
              </p>
            </div>
            <div>
              <label className="block text-sm font-medium text-ink mb-1">API Key</label>
              <div className="flex gap-1 items-center w-full">
                <div className="relative flex-1 min-w-0">
                  <input type={showPass ? 'text' : 'password'} value={form.api_key}
                    onChange={(e) => setForm({ ...form, api_key: e.target.value })}
                    className="w-full px-3 py-2 border border-hairline rounded-md bg-canvas focus:ring-2 focus:ring-primary/30 text-sm h-9"
                    placeholder={'sk-...'}
                    title={isEdit ? 'Kosongkan jika tidak ingin mengubah' : null} />
                  <button type="button" onClick={() => setShowPass(!showPass)} className="absolute right-1.5 top-1/2 -translate-y-1/2 text-muted hover:text-ink">
                    {showPass ? <EyeOff size={14} /> : <Eye size={14} />}
                  </button>
                </div>
                <button type="button" onClick={handleFetchModels} disabled={fetchingModels || form.api_type === 'anthropic'}
                  className="h-9 w-9 flex items-center justify-center bg-surface-soft text-ink rounded-md border border-hairline hover:bg-hairline transition-colors disabled:opacity-50"
                  title="Refresh Model">
                  {fetchingModels ? <RefreshCw className="animate-spin" size={14} /> : <RefreshCw size={14} />}
                </button>
                <button type="button" onClick={handleTestDraft} disabled={isTesting}
                  className="h-9 w-9 flex items-center justify-center bg-surface-soft text-ink rounded-md border border-hairline hover:bg-hairline transition-colors disabled:opacity-50"
                  title="Uji Koneksi">
                  {isTesting ? <Loader2 className="animate-spin" size={14} /> : <Wifi size={14} />}
                </button>
              </div>
              {testResult && (
                <div className={`text-xs mt-1 flex items-center gap-1 ${testResult.status === 'connected' ? 'text-success' : 'text-error'}`}>
                  {testResult.status === 'connected' ? <CheckCircle size={12} /> : <XCircle size={12} />}
                  {testResult.message}
                </div>
              )}
            </div>
          </div>

          {/* Model & Temperature */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-ink mb-1">Model</label>
              <button type="button" onClick={() => setIsModelPickerOpen(true)}
                className="w-full px-3 py-2 border border-hairline rounded-md bg-canvas text-sm text-left hover:bg-surface-soft transition-colors flex justify-between items-center">
                <span className={`${form.model ? 'text-ink' : 'text-muted'}`}>
                  {form.model || 'Klik untuk pilih model'}
                </span>
                <span className="text-muted text-xs">⌄</span>
              </button>
              <ModelPickerModal isOpen={isModelPickerOpen} onClose={() => setIsModelPickerOpen(false)}
                onSelect={(modelId) => { setForm({ ...form, model: modelId }); setIsModelPickerOpen(false); }}
                models={models} />
            </div>
            <div>
              <div className="flex items-center gap-2 mb-1">
                <label className="block text-sm font-medium text-ink">Temperature</label>
                <span className="cursor-help text-muted hover:text-ink text-sm"
                  title="Semakin rendah (0.1-0.3), AI semakin logis dan presisi. Semakin tinggi (0.7+), AI semakin kreatif tapi kurang akurat. Disarankan 0.1-0.3.">
                  <Info size={14} />
                </span>
              </div>
              <input type="number" step="0.1" min="0" max="1" value={form.temperature}
                onChange={(e) => {
                  const v = parseFloat(e.target.value);
                  setForm({ ...form, temperature: Number.isNaN(v) ? 0 : Math.min(1, Math.max(0, v)) });
                }}
                className="w-full px-3 py-2 border border-hairline rounded-md bg-canvas focus:ring-2 focus:ring-primary/30" />
            </div>
          </div>

          <div className="flex justify-end gap-2 pt-3 border-t border-hairline mt-4">
            <button type="button" onClick={onClose} className="px-4 py-2 border border-hairline rounded-md text-sm hover:bg-surface-soft">Batal</button>
            <button type="submit" className="px-4 py-2 bg-primary text-white rounded-md text-sm hover:bg-primary-active">
              {isEdit ? 'Update Config AI' : 'Simpan Config AI'}
            </button>
          </div>
        </form>
      </motion.div>
    </div>
  );
}
