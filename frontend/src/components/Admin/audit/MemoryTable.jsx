import { useCallback, useEffect, useState } from 'react';
import { Trash2, Search, Brain, RotateCcw } from 'lucide-react';
import { api } from '../../../services/api';
import { notify } from '../../../utils/notification';
import EmptyState from '../common/EmptyState';
import PaginationBar from '../common/PaginationBar';
import SkeletonTable from '../common/SkeletonTable';
import ConfirmationDialog from '../common/ConfirmationDialog';

const PAGE_SIZE = 15;
const STATUS_LIST = ['', 'pending', 'approved', 'rejected', 'stale'];

const BADGE_STATUS = {
  pending: 'bg-amber-50 text-amber-700 border-amber-200',
  approved: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  rejected: 'bg-rose-50 text-rose-700 border-rose-200',
  stale: 'bg-slate-100 text-slate-600 border-slate-200',
};

/**
 * Kelola SQL Memory (QA2-01): kurasi jawaban tersimpan per cabang.
 * Hapus permanen entri salah yang telanjur approved (remediasi yang tidak
 * bisa dilakukan tombol chat "Jawaban salah").
 * Pulihkan entri stale (anti false-stale K1) kembali ke pending agar wajib
 * dikonfirmasi ulang sebelum approved.
 */
export default function MemoryTable() {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [cabang, setCabang] = useState('');
  const [status, setStatus] = useState('');
  const [hapusId, setHapusId] = useState(null);
  const [menghapus, setMenghapus] = useState(false);
  const [pulihId, setPulihId] = useState(null);
  const [memulihkan, setMemulihkan] = useState(false);

  const muat = useCallback(async (hal = page, cab = cabang, st = status) => {
    setLoading(true);
    try {
      const data = await api.getMemories({
        branch_code: cab.trim() || undefined,
        status: st || undefined,
        limit: PAGE_SIZE,
        offset: (hal - 1) * PAGE_SIZE,
      });
      setItems(Array.isArray(data.items) ? data.items : []);
      setTotal(data.total || 0);
    } catch {
      notify.error('Gagal memuat SQL memory.');
      setItems([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [page, cabang, status]);

  useEffect(() => {
    let batal = false;
    Promise.resolve()
      .then(() => api.getMemories({ limit: PAGE_SIZE, offset: 0 }))
      .then((data) => {
        if (batal) return;
        setItems(Array.isArray(data.items) ? data.items : []);
        setTotal(data.total || 0);
        setLoading(false);
      })
      .catch(() => {
        if (batal) return;
        notify.error('Gagal memuat SQL memory.');
        setItems([]);
        setTotal(0);
        setLoading(false);
      });
    return () => {
      batal = true;
    };
  }, []);

  const terapkanFilter = () => {
    setPage(1);
    muat(1, cabang, status);
  };

  const gantiHalaman = (hal) => {
    setPage(hal);
    muat(hal, cabang, status);
  };

  const konfirmasiHapus = async () => {
    if (!hapusId) return;
    setMenghapus(true);
    try {
      await api.deleteMemory(hapusId);
      notify.success(`Memori #${hapusId} berhasil dihapus.`);
      setHapusId(null);
      const sisa = items.length - 1;
      if (sisa === 0 && page > 1) {
        gantiHalaman(page - 1);
      } else {
        muat(page, cabang, status);
      }
    } catch {
      notify.error('Gagal menghapus memori.');
    } finally {
      setMenghapus(false);
    }
  };

  const konfirmasiPulihkan = async () => {
    if (!pulihId) return;
    setMemulihkan(true);
    try {
      await api.restoreMemory(pulihId);
      notify.success(`Memori #${pulihId} dipulihkan ke pending.`);
      setPulihId(null);
      muat(page, cabang, status);
    } catch (e) {
      notify.error(e?.response?.data?.detail || 'Gagal memulihkan memori.');
    } finally {
      setMemulihkan(false);
    }
  };

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="space-y-4">
      <div className="bg-white border border-hairline rounded-xl p-4 shadow-xs">
        <h3 className="font-serif text-base text-ink">Kelola SQL Memory</h3>
        <p className="text-xs text-muted mt-0.5">
          Jawaban tersimpan yang me-replay tanpa token. Hapus permanen entri yang salah
          (mis. jawaban yang telanjur approved sebelum diverifikasi manusia).
          Pulihkan entri stale ke pending bila stale-nya akibat gangguan sesaat.
        </p>
        <div className="flex items-end gap-2 mt-3 flex-wrap">
          <label className="flex flex-col gap-1 text-xs font-medium text-body">
            Cabang
            <input
              value={cabang}
              onChange={(e) => setCabang(e.target.value)}
              placeholder="mis. TST_01"
              className="h-9 px-2.5 rounded-md bg-white border border-hairline text-ink text-sm font-mono focus:outline-none focus:border-primary"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs font-medium text-body">
            Status
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              className="h-9 px-2.5 rounded-md bg-white border border-hairline text-ink text-sm focus:outline-none focus:border-primary"
            >
              {STATUS_LIST.map((s) => (
                <option key={s} value={s}>{s === '' ? 'Semua' : s}</option>
              ))}
            </select>
          </label>
          <button
            type="button"
            onClick={terapkanFilter}
            disabled={loading}
            className="h-9 px-4 rounded-md bg-primary hover:bg-primary-active text-on-primary text-sm font-medium transition-colors disabled:opacity-50 cursor-pointer inline-flex items-center gap-1.5"
          >
            <Search size={14} />
            Tampilkan
          </button>
        </div>
      </div>

      <div className="bg-white border border-hairline rounded-xl overflow-hidden shadow-xs">
        {loading ? (
          <SkeletonTable />
        ) : items.length === 0 ? (
          <EmptyState
            icon={Brain}
            title="Tidak ada memori"
            description="Belum ada jawaban tersimpan untuk filter ini."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-surface-soft/60">
                <tr className="text-left text-xs uppercase tracking-wider text-muted border-b border-hairline">
                  <th className="px-4 py-3">ID</th>
                  <th className="px-4 py-3">Cabang</th>
                  <th className="px-4 py-3">Pertanyaan</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Dipakai</th>
                  <th className="px-4 py-3 text-right">Aksi</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-hairline">
                {items.map((m) => (
                  <tr key={m.id} className="hover:bg-surface-soft/40">
                    <td className="px-4 py-3 font-mono text-xs text-muted">#{m.id}</td>
                    <td className="px-4 py-3 font-mono text-xs text-ink">{m.branch_code}</td>
                    <td className="px-4 py-3 text-xs text-body max-w-xs truncate" title={m.pertanyaan}>
                      {m.pertanyaan}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex px-2 py-0.5 rounded-full text-[11px] font-medium border ${BADGE_STATUS[m.status] || BADGE_STATUS.stale}`}>
                        {m.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs tabular-nums text-muted">{m.times_used}x</td>
                    <td className="px-4 py-3 text-right">
                      {m.status === 'stale' && (
                        <button
                          type="button"
                          onClick={() => setPulihId(m.id)}
                          title={`Pulihkan memori #${m.id} ke pending`}
                          className="p-1.5 rounded-md text-muted hover:text-emerald-700 hover:bg-emerald-50 border border-transparent hover:border-emerald-200 transition-colors cursor-pointer mr-1"
                        >
                          <RotateCcw size={14} />
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => setHapusId(m.id)}
                        title={`Hapus memori #${m.id}`}
                        className="p-1.5 rounded-md text-muted hover:text-error hover:bg-rose-50 border border-transparent hover:border-rose-200 transition-colors cursor-pointer"
                      >
                        <Trash2 size={14} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {!loading && (
          <PaginationBar
            page={page}
            totalPages={totalPages}
            onChange={gantiHalaman}
            totalItems={total}
            pageSize={PAGE_SIZE}
          />
        )}
      </div>

      <ConfirmationDialog
        isOpen={hapusId !== null}
        onClose={() => { if (!menghapus) setHapusId(null); }}
        onConfirm={konfirmasiHapus}
        title={`Hapus memori #${hapusId}?`}
        message="Jawaban tersimpan dihapus permanen dan tercatat di audit. Pertanyaan yang sama akan dijawab ulang oleh AI."
        confirmText="Hapus"
        isLoading={menghapus}
      />

      <ConfirmationDialog
        isOpen={pulihId !== null}
        onClose={() => { if (!memulihkan) setPulihId(null); }}
        onConfirm={konfirmasiPulihkan}
        title={`Pulihkan memori #${pulihId}?`}
        message="Entri stale dikembalikan ke pending dan wajib dikonfirmasi ulang sebelum approved. Tercatat di audit."
        confirmText="Pulihkan"
        isLoading={memulihkan}
      />
    </div>
  );
}
