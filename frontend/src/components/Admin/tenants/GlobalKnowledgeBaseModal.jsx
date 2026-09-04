import { useState, useEffect, useCallback, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  X,
  Plus,
  Search,
  RefreshCw,
  Edit2,
  Trash2,
  BookOpen,
  Code2,
  FileText,
  Loader2,
  ChevronLeft,
  ChevronRight,
  Database,
  CheckCircle2,
} from 'lucide-react';
import { notify } from '../../../utils/notification';
import { api } from '../../../services/api';
import SortIcon from '../common/SortIcon';

const PAGE_SIZE = 15;

export default function GlobalKnowledgeBaseModal({ isOpen, onClose }) {
  // State data list & stats
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState({ total: 0, text: 0, example: 0 });
  const [loading, setLoading] = useState(true);
  const [statsLoading, setStatsLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);

  // Filters & Pagination
  const [search, setSearch] = useState('');
  const [kindFilter, setKindFilter] = useState(''); // '' | 'text' | 'example'
  const [page, setPage] = useState(1);

  // State Sub-modal Form Create / Edit
  const [showItemForm, setShowItemForm] = useState(false);
  const [editingItem, setEditingItem] = useState(null);
  const [formSaving, setFormSaving] = useState(false);
  const [formValues, setFormValues] = useState({
    kind: 'text',
    content: '',
    question: '',
    sql_example: '',
  });

  // State Delete Confirmation
  const [deletingId, setDeletingId] = useState(null);

  const [sortConfig, setSortConfig] = useState({ key: 'id', direction: 'desc' });

  const handleSort = (key) => {
    let direction = 'asc';
    if (sortConfig.key === key && sortConfig.direction === 'asc') direction = 'desc';
    setSortConfig({ key, direction });
  };

  const sortedItems = useMemo(() => {
    const sorted = [...items];
    return sorted.sort((a, b) => {
      let aVal = a[sortConfig.key] ?? '';
      let bVal = b[sortConfig.key] ?? '';

      if (sortConfig.key === 'id') {
        const av = Number(a.id) || 0;
        const bv = Number(b.id) || 0;
        return sortConfig.direction === 'asc' ? av - bv : bv - av;
      }

      if (typeof aVal === 'string') aVal = aVal.toLowerCase();
      if (typeof bVal === 'string') bVal = bVal.toLowerCase();

      if (aVal < bVal) return sortConfig.direction === 'asc' ? -1 : 1;
      if (aVal > bVal) return sortConfig.direction === 'asc' ? 1 : -1;
      return 0;
    });
  }, [items, sortConfig]);

  const loadData = useCallback(async () => {
    setLoading(true);
    setStatsLoading(true);
    try {
      const [s, itemsData] = await Promise.all([
        api.getGlobalKBStats(),
        api.getGlobalKBItems({
          kind: kindFilter || undefined,
          q: search || undefined,
          limit: PAGE_SIZE,
          offset: (page - 1) * PAGE_SIZE,
        }),
      ]);
      setStats(s);
      setItems(itemsData.items || []);
      setTotal(itemsData.total || 0);
    } catch (e) {
      notify.error(e.response?.data?.detail || 'Gagal memuat item Global KB');
    } finally {
      setLoading(false);
      setStatsLoading(false);
    }
  }, [page, kindFilter, search]);

  useEffect(() => {
    if (isOpen) {
      let cancelled = false;
      api.getGlobalKBStats().then((s) => {
        if (!cancelled) setStats(s);
      }).catch(() => {});

      api.getGlobalKBItems({
        kind: kindFilter || undefined,
        q: search || undefined,
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
      }).then((itemsData) => {
        if (!cancelled) {
          setItems(itemsData.items || []);
          setTotal(itemsData.total || 0);
          setLoading(false);
        }
      }).catch((e) => {
        if (!cancelled) {
          notify.error(e.response?.data?.detail || 'Gagal memuat item Global KB');
          setLoading(false);
        }
      });

      return () => { cancelled = true; };
    }
  }, [isOpen, page, kindFilter, search]);

  // Handle Search submit
  const handleSearchSubmit = (e) => {
    e.preventDefault();
    setPage(1);
    loadData();
  };

  // Handle Trigger Sinkronisasi Kamus Skema
  const handleSync = async () => {
    setSyncing(true);
    try {
      const res = await api.syncGlobalKB();
      notify.success(res.message || 'Sinkronisasi Kamus Skema berhasil');
      await loadData();
    } catch (e) {
      notify.error(e.response?.data?.detail || 'Gagal melakukan sinkronisasi kamus skema');
    } finally {
      setSyncing(false);
    }
  };

  // Open Form Create
  const handleOpenCreate = () => {
    setEditingItem(null);
    setFormValues({
      kind: 'text',
      content: '',
      question: '',
      sql_example: '',
    });
    setShowItemForm(true);
  };

  // Open Form Edit
  const handleOpenEdit = (item) => {
    setEditingItem(item);
    setFormValues({
      kind: item.kind || 'text',
      content: item.content || '',
      question: item.question || '',
      sql_example: item.sql_example || '',
    });
    setShowItemForm(true);
  };

  // Submit Save Create / Edit
  const handleSaveItem = async (e) => {
    e.preventDefault();
    if (!formValues.content.trim()) {
      notify.error('Konten tidak boleh kosong');
      return;
    }
    if (formValues.kind === 'example' && !formValues.question?.trim()) {
      notify.error('Pertanyaan wajib diisi untuk jenis Example');
      return;
    }
    if (formValues.kind === 'example' && !formValues.sql_example?.trim()) {
      notify.error('Contoh SQL wajib diisi untuk jenis Example');
      return;
    }

    setFormSaving(true);
    try {
      const payload = {
        kind: formValues.kind,
        content: formValues.content.trim(),
        question: formValues.kind === 'example' ? formValues.question.trim() : null,
        sql_example: formValues.kind === 'example' ? formValues.sql_example.trim() : null,
      };

      if (editingItem) {
        await api.updateGlobalKBItem(editingItem.id, payload);
        notify.success(`Item #${editingItem.id} berhasil diperbarui`);
      } else {
        await api.createGlobalKBItem(payload);
        notify.success('Item Global KB baru berhasil dibuat');
      }

      setShowItemForm(false);
      setEditingItem(null);
      await loadData();
    } catch (err) {
      notify.error(err.response?.data?.detail || 'Gagal menyimpan item Global KB');
    } finally {
      setFormSaving(false);
    }
  };

  // Handle Delete
  const handleDeleteItem = async (id) => {
    try {
      await api.deleteGlobalKBItem(id);
      notify.success(`Item #${id} berhasil dihapus`);
      setDeletingId(null);
      await loadData();
    } catch (e) {
      notify.error(e.response?.data?.detail || 'Gagal menghapus item');
    }
  };

  if (!isOpen) return null;

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div
      className="fixed inset-0 bg-black/50 backdrop-blur-xs flex items-center justify-center z-50 p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget && !showItemForm) onClose();
      }}
    >
      <motion.div
        initial={{ scale: 0.95, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        exit={{ scale: 0.95, opacity: 0 }}
        className="bg-white rounded-xl shadow-2xl w-full max-w-5xl h-[88vh] flex flex-col overflow-hidden border border-hairline"
      >
        {/* ================= HEADER ================= */}
        <div className="px-6 py-4 border-b border-hairline flex items-center justify-between bg-surface-soft/40">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center text-primary">
              <BookOpen size={20} />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-base font-semibold text-ink">Global Knowledge Base</h2>
                <span className="px-2 py-0.5 rounded text-[11px] font-medium bg-emerald-50 text-emerald-700 border border-emerald-200 flex items-center gap-1">
                  <CheckCircle2 size={12} /> Permanen (SSOT)
                </span>
              </div>
              <p className="text-xs text-muted">
                Pengetahuan bisnis, kamus skema, dan contoh SQL yang berlaku lintas-tenant
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={handleSync}
              disabled={syncing}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium border border-hairline rounded-md text-muted hover:text-ink hover:bg-surface-soft transition-colors disabled:opacity-50 cursor-pointer"
              title="Sinkronisasi ulang kamus skema dan aturan bisnis sistem"
            >
              <RefreshCw size={13} className={syncing ? 'animate-spin text-primary' : ''} />
              {syncing ? 'Menyinkronkan...' : 'Sinkronisasi Skema'}
            </button>
            <button
              onClick={handleOpenCreate}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-primary text-white rounded-md hover:bg-primary-active transition-colors shadow-xs cursor-pointer"
            >
              <Plus size={14} /> Tambah Item
            </button>
            <button
              onClick={onClose}
              className="p-1.5 text-muted hover:text-ink rounded-md hover:bg-surface-soft transition-colors ml-2 cursor-pointer"
              aria-label="Tutup modal"
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {/* ================= STATS & FILTER BAR ================= */}
        <div className="p-4 border-b border-hairline bg-canvas/60 flex flex-wrap items-center justify-between gap-3">
          {/* Stats Badges */}
          <div className="flex items-center gap-2 text-xs">
            <span className="px-2.5 py-1 bg-white border border-hairline rounded-md text-muted font-medium flex items-center gap-1.5">
              <Database size={13} className="text-primary" /> Total:{' '}
              <strong className="text-ink">{statsLoading ? '...' : stats.total?.toLocaleString('id-ID')}</strong>
            </span>
            <span className="px-2.5 py-1 bg-white border border-hairline rounded-md text-muted font-medium flex items-center gap-1.5">
              <FileText size={13} className="text-blue-600" /> Teks/Aturan:{' '}
              <strong className="text-ink">{statsLoading ? '...' : stats.text?.toLocaleString('id-ID')}</strong>
            </span>
            <span className="px-2.5 py-1 bg-white border border-hairline rounded-md text-muted font-medium flex items-center gap-1.5">
              <Code2 size={13} className="text-emerald-600" /> Contoh SQL:{' '}
              <strong className="text-ink">{statsLoading ? '...' : stats.example?.toLocaleString('id-ID')}</strong>
            </span>
          </div>

          {/* Search & Kind Filters */}
          <div className="flex items-center gap-2">
            {/* Filter Pills */}
            <div className="flex rounded-md border border-hairline bg-surface-soft p-0.5 text-xs">
              <button
                onClick={() => {
                  setKindFilter('');
                  setPage(1);
                }}
                className={`px-2.5 py-1 rounded font-medium transition-colors cursor-pointer ${
                  kindFilter === '' ? 'bg-white text-primary shadow-xs' : 'text-muted hover:text-ink'
                }`}
              >
                Semua
              </button>
              <button
                onClick={() => {
                  setKindFilter('text');
                  setPage(1);
                }}
                className={`px-2.5 py-1 rounded font-medium transition-colors cursor-pointer ${
                  kindFilter === 'text' ? 'bg-white text-primary shadow-xs' : 'text-muted hover:text-ink'
                }`}
              >
                Teks
              </button>
              <button
                onClick={() => {
                  setKindFilter('example');
                  setPage(1);
                }}
                className={`px-2.5 py-1 rounded font-medium transition-colors cursor-pointer ${
                  kindFilter === 'example' ? 'bg-white text-primary shadow-xs' : 'text-muted hover:text-ink'
                }`}
              >
                Contoh SQL
              </button>
            </div>

            {/* Search Bar */}
            <form onSubmit={handleSearchSubmit} className="relative w-56">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted" size={14} />
              <input
                type="text"
                placeholder="Cari kata kunci..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full pl-8 pr-7 py-1 text-xs border border-hairline rounded-md bg-white focus:outline-none focus:ring-1 focus:ring-primary/40"
              />
              {search && (
                <button
                  type="button"
                  onClick={() => {
                    setSearch('');
                    setPage(1);
                  }}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-muted hover:text-ink cursor-pointer"
                >
                  <X size={12} />
                </button>
              )}
            </form>
          </div>
        </div>

        {/* ================= ITEMS TABLE ================= */}
        <div className="flex-1 overflow-y-auto p-4 space-y-2">
          {loading ? (
            <div className="h-full flex flex-col items-center justify-center text-muted gap-2">
              <Loader2 size={24} className="animate-spin text-primary" />
              <p className="text-xs">Memuat data Global KB...</p>
            </div>
          ) : items.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-muted gap-2 border border-dashed border-hairline rounded-lg p-8">
              <BookOpen size={32} className="text-muted/60" />
              <p className="text-sm font-medium text-ink">Tidak ada item ditemukan</p>
              <p className="text-xs">
                {search || kindFilter
                  ? 'Coba ganti kata kunci pencarian atau filter'
                  : 'Klik tombol "+ Tambah Item" atau "Sinkronisasi Skema" untuk mengisi KB'}
              </p>
            </div>
          ) : (
            <div className="border border-hairline rounded-lg overflow-hidden bg-white shadow-xs">
              <table className="w-full text-left text-xs border-collapse">
                <thead>
                  <tr className="bg-surface-soft/60 border-b border-hairline text-muted font-medium">
                    <th className="py-2.5 px-3 w-20 cursor-pointer select-none hover:text-ink" onClick={() => handleSort('id')}>
                      ID <SortIcon columnKey="id" sortConfig={sortConfig} />
                    </th>
                    <th className="py-2.5 px-3 w-32 cursor-pointer select-none hover:text-ink" onClick={() => handleSort('kind')}>
                      Jenis <SortIcon columnKey="kind" sortConfig={sortConfig} />
                    </th>
                    <th className="py-2.5 px-3 cursor-pointer select-none hover:text-ink" onClick={() => handleSort('content')}>
                      Konten / Aturan / Contoh SQL <SortIcon columnKey="content" sortConfig={sortConfig} />
                    </th>
                    <th className="py-2.5 px-3 w-24 text-right">Aksi</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-hairline">
                  {sortedItems.map((item) => (
                    <tr key={item.id} className="hover:bg-surface-soft/30 transition-colors group">
                      {/* ID */}
                      <td className="py-2.5 px-3 text-muted font-mono text-[11px]">
                        #{item.id}
                      </td>

                      {/* Kind Badge */}
                      <td className="py-2.5 px-3">
                        {item.kind === 'example' ? (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                            <Code2 size={11} /> Example
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-blue-50 text-blue-700 border border-blue-200">
                            <FileText size={11} /> Text/Rule
                          </span>
                        )}
                      </td>

                      {/* Content / Question / SQL */}
                      <td className="py-2.5 px-3">
                        {item.kind === 'example' ? (
                          <div className="space-y-1">
                            {item.question && (
                              <p className="font-medium text-ink text-xs flex items-center gap-1.5">
                                <span className="text-emerald-600 font-semibold">Q:</span> {item.question}
                              </p>
                            )}
                            {item.sql_example && (
                              <pre className="p-1.5 bg-slate-900 text-slate-100 rounded text-[11px] font-mono overflow-x-auto max-h-24 whitespace-pre-wrap">
                                {item.sql_example}
                              </pre>
                            )}
                            {item.content && (
                              <p className="text-muted text-[11px] line-clamp-1">{item.content}</p>
                            )}
                          </div>
                        ) : (
                          <div>
                            <p className="text-ink text-xs whitespace-pre-wrap line-clamp-3 leading-relaxed">
                              {item.content}
                            </p>
                          </div>
                        )}
                      </td>

                      {/* Actions */}
                      <td className="py-2.5 px-3 text-right">
                        <div className="flex items-center justify-end gap-1 opacity-80 group-hover:opacity-100 transition-opacity">
                          <button
                            onClick={() => handleOpenEdit(item)}
                            className="p-1.5 text-muted hover:text-primary hover:bg-primary/10 rounded transition-colors cursor-pointer"
                            title="Edit Item"
                            aria-label={`Edit item #${item.id}`}
                          >
                            <Edit2 size={13} />
                          </button>
                          <button
                            onClick={() => setDeletingId(item.id)}
                            className="p-1.5 text-muted hover:text-red-600 hover:bg-red-50 rounded transition-colors cursor-pointer"
                            title="Hapus Item"
                            aria-label={`Hapus item #${item.id}`}
                          >
                            <Trash2 size={13} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* ================= PAGINATION FOOTER ================= */}
        <div className="px-6 py-3 border-t border-hairline bg-surface-soft/40 flex items-center justify-between text-xs text-muted">
          <span>
            Menampilkan{' '}
            <strong className="text-ink">
              {total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1}
            </strong>
            -
            <strong className="text-ink">
              {Math.min(page * PAGE_SIZE, total)}
            </strong>{' '}
            dari <strong className="text-ink">{total.toLocaleString('id-ID')}</strong> item
          </span>

          <div className="flex items-center gap-1">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="p-1.5 border border-hairline rounded bg-white text-muted hover:text-ink disabled:opacity-40 transition-colors cursor-pointer"
              aria-label="Halaman sebelumnya"
            >
              <ChevronLeft size={14} />
            </button>
            <span className="px-3 py-1 font-medium text-ink bg-white border border-hairline rounded">
              {page} / {totalPages}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="p-1.5 border border-hairline rounded bg-white text-muted hover:text-ink disabled:opacity-40 transition-colors cursor-pointer"
              aria-label="Halaman berikutnya"
            >
              <ChevronRight size={14} />
            </button>
          </div>
        </div>

        {/* ================= SUB-MODAL FORM (CREATE / EDIT) ================= */}
        <AnimatePresence>
          {showItemForm && (
            <div
              className="fixed inset-0 bg-black/60 backdrop-blur-xs flex items-center justify-center z-60 p-4"
              onClick={(e) => {
                if (e.target === e.currentTarget && !formSaving) setShowItemForm(false);
              }}
            >
              <motion.div
                initial={{ scale: 0.95, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: 0.95, opacity: 0 }}
                className="bg-white rounded-xl shadow-2xl w-full max-w-lg overflow-hidden border border-hairline flex flex-col"
              >
                <div className="px-5 py-3.5 border-b border-hairline flex items-center justify-between bg-surface-soft/50">
                  <h3 className="text-sm font-semibold text-ink">
                    {editingItem ? `Edit Item Global KB #${editingItem.id}` : 'Tambah Item Global KB Baru'}
                  </h3>
                  <button
                    onClick={() => setShowItemForm(false)}
                    disabled={formSaving}
                    className="p-1 text-muted hover:text-ink rounded cursor-pointer"
                  >
                    <X size={16} />
                  </button>
                </div>

                <form onSubmit={handleSaveItem} className="p-5 space-y-4 text-xs">
                  {/* Jenis Item */}
                  <div>
                    <label className="block font-medium text-ink mb-1">Jenis Item (Kind)</label>
                    <div className="grid grid-cols-2 gap-2">
                      <button
                        type="button"
                        onClick={() => setFormValues((v) => ({ ...v, kind: 'text' }))}
                        className={`flex items-center justify-center gap-2 p-2.5 rounded-lg border font-medium transition-colors cursor-pointer ${
                          formValues.kind === 'text'
                            ? 'border-blue-500 bg-blue-50/50 text-blue-700 ring-1 ring-blue-500/20'
                            : 'border-hairline text-muted hover:bg-surface-soft'
                        }`}
                      >
                        <FileText size={15} /> Teks / Aturan Bisnis
                      </button>
                      <button
                        type="button"
                        onClick={() => setFormValues((v) => ({ ...v, kind: 'example' }))}
                        className={`flex items-center justify-center gap-2 p-2.5 rounded-lg border font-medium transition-colors cursor-pointer ${
                          formValues.kind === 'example'
                            ? 'border-emerald-500 bg-emerald-50/50 text-emerald-700 ring-1 ring-emerald-500/20'
                            : 'border-hairline text-muted hover:bg-surface-soft'
                        }`}
                      >
                        <Code2 size={15} /> Contoh Q → SQL
                      </button>
                    </div>
                  </div>

                  {/* Field jika kind === example */}
                  {formValues.kind === 'example' && (
                    <>
                      <div>
                        <label className="block font-medium text-ink mb-1">
                          Pertanyaan Pengguna (Question) <span className="text-red-500">*</span>
                        </label>
                        <input
                          type="text"
                          placeholder="mis. Berapa total omzet dealer bulan ini?"
                          value={formValues.question}
                          onChange={(e) =>
                            setFormValues((v) => ({ ...v, question: e.target.value }))
                          }
                          className="w-full px-3 py-2 border border-hairline rounded-md bg-canvas text-xs focus:ring-2 focus:ring-primary/30 outline-none"
                          required
                        />
                      </div>

                      <div>
                        <label className="block font-medium text-ink mb-1">
                          Contoh Query SQL <span className="text-red-500">*</span>
                        </label>
                        <textarea
                          rows={4}
                          placeholder="SELECT SUM(total_harga) AS total_omzet FROM penjualan WHERE ..."
                          value={formValues.sql_example}
                          onChange={(e) =>
                            setFormValues((v) => ({ ...v, sql_example: e.target.value }))
                          }
                          className="w-full p-2.5 border border-hairline rounded-md bg-slate-950 text-slate-100 font-mono text-[11px] focus:ring-2 focus:ring-primary/30 outline-none"
                          required
                        />
                      </div>
                    </>
                  )}

                  {/* Content (Deskripsi / Aturan) */}
                  <div>
                    <label className="block font-medium text-ink mb-1">
                      {formValues.kind === 'text' ? 'Isi Teks / Penjelasan Bisnis' : 'Keterangan Tambahan (Content)'}{' '}
                      <span className="text-red-500">*</span>
                    </label>
                    <textarea
                      rows={formValues.kind === 'text' ? 5 : 2}
                      placeholder={
                        formValues.kind === 'text'
                          ? 'Tuliskan aturan bisnis, kamus istilah, atau relasi tabel...'
                          : 'Deskripsi ringkas contoh ini...'
                      }
                      value={formValues.content}
                      onChange={(e) =>
                        setFormValues((v) => ({ ...v, content: e.target.value }))
                      }
                      className="w-full p-2.5 border border-hairline rounded-md bg-canvas text-xs focus:ring-2 focus:ring-primary/30 outline-none"
                      required
                    />
                  </div>

                  {/* Form Footer */}
                  <div className="pt-3 border-t border-hairline flex items-center justify-end gap-2">
                    <button
                      type="button"
                      onClick={() => setShowItemForm(false)}
                      disabled={formSaving}
                      className="px-3 py-1.5 border border-hairline rounded-md text-muted hover:text-ink font-medium cursor-pointer"
                    >
                      Batal
                    </button>
                    <button
                      type="submit"
                      disabled={formSaving}
                      className="flex items-center gap-1.5 px-4 py-1.5 bg-primary text-white rounded-md hover:bg-primary-active font-medium disabled:opacity-50 cursor-pointer"
                    >
                      {formSaving && <Loader2 size={13} className="animate-spin" />}
                      {editingItem ? 'Simpan Perubahan' : 'Buat Item'}
                    </button>
                  </div>
                </form>
              </motion.div>
            </div>
          )}
        </AnimatePresence>

        {/* ================= DELETE CONFIRMATION DIALOG ================= */}
        <AnimatePresence>
          {deletingId && (
            <div
              className="fixed inset-0 bg-black/60 backdrop-blur-xs flex items-center justify-center z-70 p-4"
              onClick={() => setDeletingId(null)}
            >
              <motion.div
                initial={{ scale: 0.95, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: 0.95, opacity: 0 }}
                className="bg-white rounded-xl p-5 shadow-2xl max-w-sm w-full border border-hairline text-xs space-y-3"
              >
                <div className="flex items-center gap-2.5 text-red-600 font-semibold text-sm">
                  <Trash2 size={18} />
                  <span>Hapus Item #{deletingId}?</span>
                </div>
                <p className="text-muted leading-relaxed">
                  Item ini akan dihapus permanen dari Global Knowledge Base. Aksi ini tidak dapat dibatalkan.
                </p>
                <div className="flex items-center justify-end gap-2 pt-2">
                  <button
                    onClick={() => setDeletingId(null)}
                    className="px-3 py-1.5 border border-hairline rounded-md text-muted hover:text-ink font-medium cursor-pointer"
                  >
                    Batal
                  </button>
                  <button
                    onClick={() => handleDeleteItem(deletingId)}
                    className="px-3 py-1.5 bg-red-600 text-white rounded-md hover:bg-red-700 font-medium cursor-pointer"
                  >
                    Ya, Hapus
                  </button>
                </div>
              </motion.div>
            </div>
          )}
        </AnimatePresence>
      </motion.div>
    </div>
  );
}
