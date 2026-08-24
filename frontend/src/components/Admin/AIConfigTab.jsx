import { useState, useEffect, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import ModelPickerModal from './ModelPickerModal';
import { api } from '../../services/api';
import {
  Plus, X, CheckCircle, Eye, EyeOff,
  RefreshCw, Trash2, Pencil, Info, Search, AlertTriangle, Loader2,
  Zap, Cpu, Wifi
} from 'lucide-react';
import toast from 'react-hot-toast';
import EmptyState from './common/EmptyState';
import useDebounce from '../../hooks/useDebounce';

export default function AIConfigTab() {
  const [configs, setConfigs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [showPass, setShowPass] = useState(false);
  const [fetchingModels, setFetchingModels] = useState(false);
  const [models, setModels] = useState([]);
  const [editingId, setEditingId] = useState(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [statusMap, setStatusMap] = useState({});
  const [testResult, setTestResult] = useState(null);
  const [isTesting, setIsTesting] = useState(false);
  const [configToDelete, setConfigToDelete] = useState(null);
  const [isModelPickerOpen, setIsModelPickerOpen] = useState(false);
  const debouncedSearch = useDebounce(searchTerm, 300);

  const [form, setForm] = useState({
    scope: 'global',
    target_id: '',
    provider: '',
    api_key: '',
    model: '',
    temperature: 0.7,
    api_type: 'openai',
    base_url: 'https://api.openai.com/v1',
  });

  useEffect(() => {
    fetchConfigs();
  }, []);

  const fetchConfigs = async () => {
    setLoading(true);
    try {
      const data = await api.getAIConfigs();
      setConfigs(data || []);
      await testAllStatus(data || []);
    } catch (e) {
      toast.error('Gagal memuat konfigurasi AI');
    } finally {
      setLoading(false);
    }
  };

  const testAllStatus = async (configList) => {
    const statuses = {};
    await Promise.all(configList.map(async (c) => {
      try {
        const result = await api.testAIConfig(c.id);
        statuses[c.id] = result.status;
      } catch (e) {
        statuses[c.id] = 'disconnected';
      }
    }));
    setStatusMap(statuses);
  };

  const handleTestSingle = async (id) => {
    setStatusMap(prev => ({ ...prev, [id]: 'loading' }));
    try {
      const result = await api.testAIConfig(id);
      setStatusMap(prev => ({ ...prev, [id]: result.status }));
      if (result.status === 'connected') toast.success('Koneksi AI berhasil!');
      else toast.error(`Koneksi gagal: ${result.message || ''}`);
    } catch (e) {
      setStatusMap(prev => ({ ...prev, [id]: 'disconnected' }));
      toast.error('Gagal melakukan test koneksi');
    }
  };

  // --- LOGIKA TEST DRAFT (dengan config_id) ---
  const handleTestDraft = async () => {
    if (!editingId && !form.api_key) { 
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
      const result = await api.testAIConfigDraft(
        form.api_type,
        form.base_url,
        form.api_key,
        editingId
      );
      setTestResult(result);
    } catch (e) {
      setTestResult({ status: 'disconnected', message: 'Gagal melakukan uji koneksi' });
    } finally {
      setIsTesting(false);
    }
  };

  // --- LOGIKA FETCH MODEL (dengan config_id) ---
  const handleFetchModels = async () => {
    if (!editingId && !form.api_key) { 
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
      const result = await api.fetchProviderModels(
        form.provider || 'Custom', 
        form.api_key,
        form.api_type, 
        form.base_url,
        editingId
      );
      setModels(result.models || []);
      if (result.models && result.models.length > 0) {
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

  // --- LOGIKA CRUD ---
  const handleSaveConfig = async (e) => {
    e.preventDefault();
    try {
      if (editingId) {
        await api.updateAIConfig(editingId, form);
        toast.success('Konfigurasi AI berhasil diperbarui!');
      } else {
        await api.createAIConfig(form);
        toast.success('Konfigurasi AI berhasil disimpan!');
      }
      setShowModal(false);
      resetForm();
      await fetchConfigs();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Gagal menyimpan konfigurasi');
    }
  };

  const handleDeleteClick = (id) => {
    setConfigToDelete(id);
  };

  const confirmDelete = async () => {
    if (!configToDelete) return;
    try {
      await api.deleteAIConfig(configToDelete);
      toast.success('Konfigurasi berhasil dihapus');
      setConfigToDelete(null);
      await fetchConfigs();
    } catch (e) {
      toast.error('Gagal menghapus konfigurasi');
    }
  };

  const resetForm = () => {
    setForm({
      scope: 'global', target_id: '', provider: '', api_key: '', 
      model: '', temperature: 0.7, api_type: 'openai', 
      base_url: 'https://api.openai.com/v1'
    });
    setEditingId(null);
    setModels([]);
    setShowPass(false);
    setTestResult(null);
  };

  const openEditModal = (config) => {
    setEditingId(config.id);
    setForm({
      scope: config.scope, target_id: config.target_id || '',
      provider: config.provider || '', api_key: '', // API Key tetap kosong saat edit
      model: config.model, temperature: config.temperature,
      api_type: config.api_type || 'openai', 
      base_url: config.base_url || 'https://api.openai.com/v1'
    });
    setTestResult(null);
    setShowModal(true);
  };

  const filteredConfigs = useMemo(() => {
    if (!debouncedSearch) return configs;
    const lower = debouncedSearch.toLowerCase();
    return configs.filter(c =>
      (c.provider || '').toLowerCase().includes(lower) ||
      (c.model || '').toLowerCase().includes(lower)
    );
  }, [configs, debouncedSearch]);

  // Keyboard: Esc menutup modal paling atas
  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== 'Escape') return;
      if (isTesting || fetchingModels) return; // jangan tutup saat proses berjalan
      if (configToDelete) setConfigToDelete(null);
      else if (isModelPickerOpen) setIsModelPickerOpen(false);
      else if (showModal) setShowModal(false);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [configToDelete, isModelPickerOpen, showModal, isTesting, fetchingModels]);

  // --- Skeleton Loader ---
  const SkeletonLoader = () => (
    <div className="bg-white rounded-xl border border-hairline overflow-hidden shadow-sm p-4 space-y-3 animate-pulse">
      <div className="h-8 bg-surface-soft rounded w-1/4 mb-4" />
      {[...Array(4)].map((_, i) => (
        <div key={i} className="flex gap-4">
          <div className="h-6 bg-surface-soft rounded w-1/6" />
          <div className="h-6 bg-surface-soft rounded w-1/4" />
          <div className="h-6 bg-surface-soft rounded w-1/4" />
          <div className="h-6 bg-surface-soft rounded w-1/6" />
          <div className="h-6 bg-surface-soft rounded w-1/6" />
        </div>
      ))}
    </div>
  );

  return (
    <div className="space-y-6">
      {/* Header & Search */}
      <div className="flex justify-between items-center gap-4 flex-wrap">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" size={16} />
          <input
            type="text"
            placeholder="Cari provider atau model..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full pl-9 pr-3 py-2 border border-hairline rounded-md bg-canvas text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
          />
        </div>
        <button
          onClick={() => { resetForm(); setShowModal(true); }}
          className="flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-md text-sm hover:bg-primary-active shadow-sm whitespace-nowrap"
        >
          <Plus size={16} /> Tambah Config AI
        </button>
      </div>

      {/* Table / Skeleton */}
      {loading ? (
        <SkeletonLoader />
      ) : filteredConfigs.length === 0 ? (
        <EmptyState
          variant="bot"
          title={configs.length === 0 ? 'Belum ada konfigurasi AI' : 'Tidak ada hasil pencarian'}
          description={
            configs.length === 0
              ? 'Klik "Tambah Config AI" untuk menghubungkan provider AI.'
              : 'Coba gunakan kata kunci lain.'
          }
        />
      ) : (
        <div className="bg-white rounded-xl border border-hairline overflow-hidden shadow-sm">
          <div className="max-h-96 overflow-y-auto">
            <table className="w-full text-left">
              <thead className="bg-surface-soft text-sm text-muted sticky top-0 z-10">
                <tr>
                  <th className="p-3">Scope</th>
                  <th className="p-3">Provider / Type</th>
                  <th className="p-3">Model</th>
                  <th className="p-3">Temp.</th>
                  <th className="p-3">Status</th>
                  <th className="p-3 w-20">Aksi</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-hairline">
                {filteredConfigs.map((c, idx) => (
                  <motion.tr 
                    key={c.id} 
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: idx * 0.05 }}
                    className="hover:bg-surface-soft/50 transition-colors"
                  >
                    <td className="p-3 text-sm">
                      {c.scope === 'global' ? 'Global' : c.scope === 'tenant' ? `Tenant: ${c.target_id}` : `User: ${c.target_id}`}
                    </td>
                    <td className="p-3 text-sm font-medium">
                      {c.provider || 'Custom'} 
                      <span className="ml-1 text-xs text-muted px-1.5 py-0.5 rounded-full bg-surface-soft">
                        {c.api_type === 'openai' ? 'OpenAI' : 'Anthropic'}
                      </span>
                    </td>
                    <td className="p-3 text-sm">{c.model}</td>
                    <td className="p-3 text-sm">{c.temperature}</td>
                    <td className="p-3">
                      {statusMap[c.id] === 'loading' ? (
                        <span className="text-muted text-xs animate-pulse">Loading...</span>
                      ) : statusMap[c.id] === 'connected' ? (
                        <span className="inline-flex items-center text-success text-xs">
                          <CheckCircle size={14} className="mr-1" /> Connected
                        </span>
                      ) : (
                        <span className="inline-flex items-center text-error text-xs">
                          <XCircle size={14} className="mr-1" /> Disconnected
                        </span>
                      )}
                    </td>
                    <td className="p-3 flex gap-1">
                      <button onClick={() => openEditModal(c)} className="text-muted hover:text-ink transition-colors">
                        <Pencil size={16} />
                      </button>
                      <button onClick={() => handleTestSingle(c.id)} className="text-muted hover:text-primary transition-colors ml-1">
                        <RefreshCw size={14} />
                      </button>
                      <button onClick={() => handleDeleteClick(c.id)} className="text-muted hover:text-error transition-colors ml-1">
                        <Trash2 size={16} />
                      </button>
                    </td>
                  </motion.tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Delete Modal */}
      <AnimatePresence>
        {configToDelete && (
          <motion.div 
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
          >
            <motion.div 
              initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.95, opacity: 0 }}
              className="bg-white rounded-xl p-6 max-w-sm w-full shadow-xl border border-hairline relative"
            >
              <div className="flex items-center gap-3 mb-4 text-error">
                <AlertTriangle size={24} />
                <h3 className="font-serif text-lg text-ink">Hapus Konfigurasi?</h3>
              </div>
              <p className="text-muted text-sm mb-6">
                Tindakan ini tidak dapat dibatalkan. Apakah Anda yakin ingin menghapus konfigurasi AI ini dari sistem?
              </p>
              <div className="flex justify-end gap-2">
                <button onClick={() => setConfigToDelete(null)} className="px-4 py-2 border border-hairline rounded-md text-sm hover:bg-surface-soft">Batal</button>
                <button onClick={confirmDelete} className="px-4 py-2 bg-error text-white rounded-md text-sm hover:bg-red-700">Hapus</button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Create/Edit Modal */}
      <AnimatePresence>
        {showModal && (
          <motion.div 
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
          >
            <motion.div 
              initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.95, opacity: 0 }}
              transition={{ type: 'spring', damping: 20, stiffness: 300 }}
              className="bg-white rounded-xl p-6 max-w-lg w-full shadow-xl border border-hairline relative"
            >
              <button onClick={() => setShowModal(false)} className="absolute right-4 top-4 text-muted hover:text-ink">
                <X size={20} />
              </button>
              <h3 className="font-serif text-lg text-ink mb-4">
                {editingId ? 'Edit Konfigurasi AI' : 'Tambah Konfigurasi AI'}
              </h3>
              <form onSubmit={handleSaveConfig} className="space-y-3">
                
                {/* Scope: Radio Tabs */}
                <div>
                  <label className="block text-sm font-medium text-ink mb-2">Scope</label>
                  <div className="flex gap-2 border border-hairline rounded-md p-1 bg-surface-soft">
                    {['global', 'tenant', 'user'].map((s) => (
                      <button
                        key={s}
                        type="button"
                        onClick={() => setForm({ ...form, scope: s, target_id: '' })}
                        className={`flex-1 py-1.5 text-xs font-medium rounded transition-colors ${
                          form.scope === s ? 'bg-white text-ink shadow-sm' : 'text-muted hover:text-ink'
                        }`}
                      >
                        {s === 'global' ? 'Global' : s === 'tenant' ? 'Tenant' : 'User'}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Target ID (slide down) */}
                <AnimatePresence>
                  {form.scope !== 'global' && (
                    <motion.div 
                      initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }}
                      className="overflow-hidden"
                    >
                      <div className="pt-1 pb-2">
                        <label className="block text-sm font-medium text-ink mb-1">Target ID</label>
                        <input
                          type="text"
                          required={form.scope !== 'global'}
                          value={form.target_id}
                          onChange={(e) => setForm({ ...form, target_id: e.target.value })}
                          className="w-full px-3 py-2 border border-hairline rounded-md bg-canvas focus:ring-2 focus:ring-primary/30"
                          placeholder="Kode Cabang / Username"
                        />
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>

                {/* Provider & API Type */}
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-sm font-medium text-ink mb-1">Nama Provider</label>
                    <input
                      type="text"
                      value={form.provider}
                      onChange={(e) => setForm({ ...form, provider: e.target.value })}
                      placeholder="OpenAI / AgentRouter"
                      className="w-full text-sm px-3 py-2 border border-hairline rounded-md bg-canvas focus:ring-2 focus:ring-primary/30"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-ink mb-1">Tipe API</label>
                    <div className="flex gap-2 border border-hairline rounded-md p-1 bg-surface-soft">
                      <button
                        type="button"
                        onClick={() => setForm({ ...form, api_type: 'openai', model: '' })}
                        className={`flex-1 py-1.5 text-xs font-medium rounded transition-colors flex items-center justify-center gap-1 ${
                          form.api_type === 'openai' ? 'bg-primary text-white shadow-sm' : 'text-muted hover:text-ink'
                        }`}
                      >
                        <Zap size={14} /> OpenAI
                      </button>
                      <button
                        type="button"
                        onClick={() => setForm({ ...form, api_type: 'anthropic', model: '' })}
                        className={`flex-1 py-1.5 text-xs font-medium rounded transition-colors flex items-center justify-center gap-1 ${
                          form.api_type === 'anthropic' ? 'bg-primary text-white shadow-sm' : 'text-muted hover:text-ink'
                        }`}
                      >
                        <Cpu size={14} /> Anthropic
                      </button>
                    </div>
                  </div>
                </div>

                {/* Base URL & API Key in one row */}
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-sm font-medium text-ink mb-1">Base URL</label>
                    <input
                      type="text"
                      value={form.base_url}
                      onChange={(e) => setForm({ ...form, base_url: e.target.value })}
                      placeholder="https://api.agentrouter.com/v1"
                      className="w-full px-3 py-2 border border-hairline rounded-md bg-canvas focus:ring-2 focus:ring-primary/30 h-9 text-sm"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-ink mb-1">API Key</label>
                    <div className="flex gap-1 items-center w-full">
                      <div className="relative flex-1 min-w-0">
                        <input
                          type={showPass ? 'text' : 'password'}
                          value={form.api_key}
                          onChange={(e) => setForm({ ...form, api_key: e.target.value })}
                          className="w-full px-3 py-2 border border-hairline rounded-md bg-canvas focus:ring-2 focus:ring-primary/30 text-sm h-9"
                          placeholder={'sk-...'}
                          title={editingId ? 'Kosongkan jika tidak ingin mengubah' : null}
                        />
                        <button type="button" onClick={() => setShowPass(!showPass)} className="absolute right-1.5 top-1/2 -translate-y-1/2 text-muted hover:text-ink">
                          {showPass ? <EyeOff size={14} /> : <Eye size={14} />}
                        </button>
                      </div>
                      <button
                        type="button"
                        onClick={handleFetchModels}
                        disabled={fetchingModels || form.api_type === 'anthropic'}
                        className="h-9 w-9 flex items-center justify-center bg-surface-soft text-ink rounded-md border border-hairline hover:bg-hairline transition-colors disabled:opacity-50"
                        title="Refresh Model"
                      >
                        {fetchingModels ? <RefreshCw className="animate-spin" size={14} /> : <RefreshCw size={14} />}
                      </button>
                      <button
                        type="button"
                        onClick={handleTestDraft}
                        disabled={isTesting}
                        className="h-9 w-9 flex items-center justify-center bg-surface-soft text-ink rounded-md border border-hairline hover:bg-hairline transition-colors disabled:opacity-50"
                        title="Uji Koneksi"
                      >
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

                {/* Model & Temperature in one row */}
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-sm font-medium text-ink mb-1">Model</label>
                    <button
                      type="button"
                      onClick={() => setIsModelPickerOpen(true)}
                      className="w-full px-3 py-2 border border-hairline rounded-md bg-canvas text-sm text-left hover:bg-surface-soft transition-colors flex justify-between items-center"
                    >
                      <span className={`${form.model ? 'text-ink' : 'text-muted'}`}>
                        {form.model || 'Klik untuk pilih model'}
                      </span>
                      <span className="text-muted text-xs">⌄</span>
                    </button>
  
                    {/* MODAL PICKER */}
                    <ModelPickerModal
                      isOpen={isModelPickerOpen}
                      onClose={() => setIsModelPickerOpen(false)}
                      onSelect={(modelId) => {
                        setForm({ ...form, model: modelId });
                        setIsModelPickerOpen(false);
                      }}
                      models={models}
                    />
                  </div>
                  
                  {/* TEMPERATURE */}
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <label className="block text-sm font-medium text-ink">Temperature</label>
                      <span 
                        className="cursor-help text-muted hover:text-ink text-sm" 
                        title="Semakin rendah (0.1-0.3), AI semakin logis dan presisi. Semakin tinggi (0.7+), AI semakin kreatif tapi kurang akurat. Disarankan 0.1-0.3."
                      >
                        <Info size={14} />
                      </span>
                    </div>
                    <input
                      type="number"
                      step="0.1"
                      min="0"
                      max="1"
                      value={form.temperature}
                      onChange={(e) => {
                        const v = parseFloat(e.target.value);
                        // Guard NaN (field dikosongkan) + clamp ke rentang valid 0-1
                        setForm({ ...form, temperature: Number.isNaN(v) ? 0 : Math.min(1, Math.max(0, v)) });
                      }}
                      className="w-full px-3 py-2 border border-hairline rounded-md bg-canvas focus:ring-2 focus:ring-primary/30"
                    />
                  </div>
                </div>

                <div className="flex justify-end gap-2 pt-3 border-t border-hairline mt-4">
                  <button type="button" onClick={() => setShowModal(false)} className="px-4 py-2 border border-hairline rounded-md text-sm hover:bg-surface-soft">Batal</button>
                  <button type="submit" className="px-4 py-2 bg-primary text-white rounded-md text-sm hover:bg-primary-active">
                    {editingId ? 'Update Config AI' : 'Simpan Config AI'}
                  </button>
                </div>
              </form>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}