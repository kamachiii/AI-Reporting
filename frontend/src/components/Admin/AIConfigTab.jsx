import { useState, useEffect, useMemo } from 'react';
import { motion } from 'framer-motion';
import { api } from '../../services/api';
import {
  Plus, X, CheckCircle, XCircle,
  RefreshCw, Trash2, Pencil, Search
} from 'lucide-react';
import toast from 'react-hot-toast';
import EmptyState from './common/EmptyState';
import ConfirmationDialog from './common/ConfirmationDialog';
import SkeletonTable from './common/SkeletonTable';
import AIConfigModal from './ai/AIConfigModal';
import useDebounce from '../../hooks/useDebounce';
import useAdminShortcuts from '../../hooks/useAdminShortcuts';

export default function AIConfigTab() {
  const [configs, setConfigs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const debouncedSearch = useDebounce(searchTerm, 300);
  const [statusMap, setStatusMap] = useState({});
  const [showModal, setShowModal] = useState(false);
  const [editing, setEditing] = useState(null); // object config saat edit
  const [saving, setSaving] = useState(false);
  const [configToDelete, setConfigToDelete] = useState(null);

  useEffect(() => {
    fetchConfigs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Keyboard: Esc menutup modal paling atas; "/" fokus pencarian
  useAdminShortcuts({
    onEscape: () => {
      if (configToDelete) setConfigToDelete(null);
      else if (showModal) setShowModal(false);
    },
    isBusy: saving,
    searchInputId: 'aiconfig-search',
  });

  const fetchConfigs = async () => {
    setLoading(true);
    try {
      const data = await api.getAIConfigs();
      setConfigs(data || []);
      testAllStatus(data || []);
    } catch {
      toast.error('Gagal memuat konfigurasi AI');
    } finally {
      setLoading(false);
    }
  };

  const testAllStatus = (configList) => {
    configList.forEach(async (c) => {
      setStatusMap(prev => ({ ...prev, [c.id]: 'checking' }));
      try {
        const result = await api.testAIConfig(c.id);
        setStatusMap(prev => ({ ...prev, [c.id]: result.status }));
      } catch {
        setStatusMap(prev => ({ ...prev, [c.id]: 'disconnected' }));
      }
    });
  };

  const handleTestSingle = async (id) => {
    setStatusMap(prev => ({ ...prev, [id]: 'checking' }));
    try {
      const result = await api.testAIConfig(id);
      setStatusMap(prev => ({ ...prev, [id]: result.status }));
      if (result.status === 'connected') toast.success('Koneksi AI berhasil!');
      else toast.error(`Koneksi gagal: ${result.message || ''}`);
    } catch {
      setStatusMap(prev => ({ ...prev, [id]: 'disconnected' }));
      toast.error('Gagal melakukan test koneksi');
    }
  };

  const handleSaveConfig = async (payload) => {
    setSaving(true);
    try {
      if (editing) {
        await api.updateAIConfig(editing.id, payload);
        toast.success('Konfigurasi AI berhasil diperbarui!');
      } else {
        await api.createAIConfig(payload);
        toast.success('Konfigurasi AI berhasil disimpan!');
      }
      setShowModal(false);
      setEditing(null);
      await fetchConfigs();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Gagal menyimpan konfigurasi');
    } finally {
      setSaving(false);
    }
  };

  const confirmDelete = async () => {
    if (!configToDelete) return;
    try {
      await api.deleteAIConfig(configToDelete);
      toast.success('Konfigurasi berhasil dihapus');
      setConfigToDelete(null);
      await fetchConfigs();
    } catch {
      toast.error('Gagal menghapus konfigurasi');
    }
  };

  const filteredConfigs = useMemo(() => {
    if (!debouncedSearch) return configs;
    const lower = debouncedSearch.toLowerCase();
    return configs.filter(c =>
      (c.provider || '').toLowerCase().includes(lower) ||
      (c.model || '').toLowerCase().includes(lower)
    );
  }, [configs, debouncedSearch]);

  if (loading) return <SkeletonTable rows={4} columns={5} />;

  return (
    <div className="space-y-6">
      {/* Search + Tambah */}
<div className="flex items-center gap-4 flex-wrap">
        <div className="relative w-full sm:w-64">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" size={16} />
          <input
            id="aiconfig-search"
            type="text"
            placeholder="Cari provider atau model...  ( / )"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full pl-9 pr-8 py-2 border border-hairline rounded-md bg-canvas text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
          />
          {searchTerm && (
            <button type="button" onClick={() => setSearchTerm('')} aria-label="Bersihkan pencarian" className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted hover:text-ink">
              <X size={14} />
            </button>
          )}
        </div>

        <button
          onClick={() => { setEditing(null); setShowModal(true); }}
          className="ml-auto flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-md text-sm hover:bg-primary-active shadow-sm whitespace-nowrap"
        >
          <Plus size={16} /> Tambah Config AI
        </button>
      </div>

      {filteredConfigs.length === 0 ? (
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
          <div className="overflow-auto max-h-[420px]">
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
                    transition={{ delay: Math.min(idx * 0.05, 0.3) }}
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
                      {(statusMap[c.id] === 'loading' || statusMap[c.id] === 'checking') ? (
                        <span className="text-muted text-xs animate-pulse">Menguji…</span>
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
                      <button onClick={() => { setEditing(c); setShowModal(true); }} className="text-muted hover:text-ink transition-colors" title="Edit">
                        <Pencil size={16} />
                      </button>
                      <button onClick={() => handleTestSingle(c.id)} className="text-muted hover:text-primary transition-colors ml-1" title="Test">
                        <RefreshCw size={14} />
                      </button>
                      <button onClick={() => setConfigToDelete(c.id)} className="text-muted hover:text-error transition-colors ml-1" title="Hapus">
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

      {/* Confirm delete */}
      {configToDelete && (
        <ConfirmationDialog
          key="aiConfirm"
          isOpen={!!configToDelete}
          onClose={() => setConfigToDelete(null)}
          onConfirm={confirmDelete}
          title="Hapus Konfigurasi?"
          message="Tindakan ini tidak dapat dibatalkan. Konfigurasi AI akan dihapus dari sistem."
          isLoading={false}
        />
      )}

      {/* Create/Edit */}
      {showModal && (
        <AIConfigModal
          key={editing?.id || 'new'}
          isOpen={showModal}
          onClose={() => { setShowModal(false); setEditing(null); }}
          onSave={handleSaveConfig}
          editing={editing}
        />
      )}
    </div>
  );
}
