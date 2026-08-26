import { useState, useEffect, useMemo } from 'react';
import { motion } from 'framer-motion';
import { api } from '../../services/api';
import { notify } from '../../utils/notification';
import {
  Plus, Search, Loader2, Trash2, Pencil,
  ToggleRight, ToggleLeft, X
} from 'lucide-react';
import PaginationBar from './common/PaginationBar';
import EmptyState from './common/EmptyState';
import ConfirmationDialog from './common/ConfirmationDialog';
import SkeletonTable from './common/SkeletonTable';
import UserModal from './users/UserModal';
import useDebounce from '../../hooks/useDebounce';
import useAdminShortcuts from '../../hooks/useAdminShortcuts';

const PAGE_SIZE = 10;

export default function UsersTab() {
  const [users, setUsers] = useState([]);
  const [branches, setBranches] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const debouncedSearch = useDebounce(searchTerm, 300);
  const [page, setPage] = useState(1);

  const [showUserModal, setShowUserModal] = useState(false);
  const [editingUser, setEditingUser] = useState(null);
  const [saving, setSaving] = useState(false);
  const [processingId, setProcessingId] = useState(null);
  const [confirmState, setConfirmState] = useState(null);

  useEffect(() => {
    fetchData();
  }, []);

  // Esc menutup modal/dialog; "/" fokus pencarian
  useAdminShortcuts({
    onEscape: () => {
      if (confirmState) setConfirmState(null);
      else if (showUserModal) setShowUserModal(false);
    },
    isBusy: !!processingId || saving,
    searchInputId: 'user-search',
  });

  const fetchData = async () => {
    setLoading(true);
    try {
      const [usersData, branchesData] = await Promise.all([
        api.getUsers(),
        api.getBranches(),
      ]);
      setUsers(usersData || []);
      setBranches(branchesData || []);
    } catch {
      notify.error('Gagal memuat data user');
    } finally {
      setLoading(false);
    }
  };

  const filteredUsers = useMemo(() => {
    if (!debouncedSearch) return users;
    const lower = debouncedSearch.toLowerCase();
    return users.filter((u) =>
      u.username.toLowerCase().includes(lower) ||
      (u.email || '').toLowerCase().includes(lower) ||
      u.role.toLowerCase().includes(lower) ||
      (u.branches || []).some((b) => b.toLowerCase().includes(lower))
    );
  }, [users, debouncedSearch]);

  const totalPages = Math.max(1, Math.ceil(filteredUsers.length / PAGE_SIZE));
  const paginatedUsers = useMemo(() => {
    const start = (page - 1) * PAGE_SIZE;
    return filteredUsers.slice(start, start + PAGE_SIZE);
  }, [filteredUsers, page]);

  useEffect(() => setPage(1), [debouncedSearch]);
  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  const handleSaveUser = async (payload) => {
    setSaving(true);
    try {
      if (editingUser) {
        // username tidak ikut di-update (backend menerima tapi diabaikan utk edit)
        const { username, ...rest } = payload;
        await api.updateUser(editingUser.id, rest);
        notify.success(`User '${editingUser.username}' berhasil diperbarui`);
      } else {
        await api.createUser(payload);
        notify.success(`User '${payload.username}' berhasil dibuat`);
      }
      setShowUserModal(false);
      setEditingUser(null);
      await fetchData();
    } catch (e) {
      notify.error(e.response?.data?.detail || 'Gagal menyimpan user');
    } finally {
      setSaving(false);
    }
  };

  const handleToggleStatus = (u) => {
    setConfirmState({
      title: u.is_active ? 'Nonaktifkan User?' : 'Aktifkan User?',
      message: u.is_active
        ? `User ${u.username} tidak akan bisa login sampai diaktifkan kembali.`
        : `User ${u.username} akan dapat login kembali.`,
      danger: !!u.is_active,
      onConfirm: async () => {
        setProcessingId(u.id);
        try {
          await api.setUserStatus(u.id, !u.is_active);
          notify.success(`User '${u.username}' berhasil ${u.is_active ? 'dinonaktifkan' : 'diaktifkan'}`);
          await fetchData();
        } catch (e) {
          notify.error(e.response?.data?.detail || 'Gagal mengubah status user');
        } finally {
          setProcessingId(null);
          setConfirmState(null);
        }
      },
    });
  };

  const handleDeleteUser = (u) => {
    setConfirmState({
      title: 'Hapus User?',
      message: `User ${u.username} beserta akses cabangnya akan dihapus PERMANEN. Riwayat audit tetap tersimpan. Tindakan ini tidak bisa dibatalkan.`,
      danger: true,
      onConfirm: async () => {
        setProcessingId(u.id);
        try {
          await api.deleteUser(u.id);
          notify.success(`User '${u.username}' berhasil dihapus`);
          await fetchData();
        } catch (e) {
          notify.error(e.response?.data?.detail || 'Gagal menghapus user');
        } finally {
          setProcessingId(null);
          setConfirmState(null);
        }
      },
    });
  };

  if (loading) return <SkeletonTable rows={4} columns={4} />;

  return (
    <div className="space-y-6">
      {/* Search + Add */}
      <div className="flex items-center gap-4 flex-wrap">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" size={16} />
          <input
            id="user-search"
            type="text"
            placeholder="Cari username, email, role...  ( / )"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full pl-9 pr-8 py-2 border border-hairline rounded-md bg-canvas text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
          />
          {searchTerm && (
            <button type="button" onClick={() => setSearchTerm('')} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted hover:text-ink">
              <X size={14} />
            </button>
          )}
        </div>
        <button
          onClick={() => { setEditingUser(null); setShowUserModal(true); }}
          className="flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-md text-sm hover:bg-primary-active shadow-sm whitespace-nowrap"
        >
          <Plus size={16} /> Tambah User
        </button>
      </div>

      {filteredUsers.length === 0 ? (
        <EmptyState
          variant="box"
          title={users.length === 0 ? 'Belum ada user terdaftar' : 'Tidak ada hasil pencarian'}
          description={
            users.length === 0
              ? 'Klik "Tambah User" untuk membuat akun pertama.'
              : 'Coba gunakan kata kunci lain.'
          }
        />
      ) : (
        <div className="bg-white rounded-xl border border-hairline overflow-hidden shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead className="bg-surface-soft text-sm text-muted">
                <tr>
                  <th className="p-3">Username</th>
                  <th className="p-3">Email</th>
                  <th className="p-3 w-24">Role</th>
                  <th className="p-3">Akses Cabang</th>
                  <th className="p-3 w-28">Status</th>
                  <th className="p-3 w-24">Aksi</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-hairline">
                {paginatedUsers.map((u, idx) => (
                  <motion.tr
                    key={u.id}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: Math.min(idx * 0.03, 0.3) }}
                    className="hover:bg-surface-soft/50 transition-colors"
                  >
                    <td className="p-3 font-medium text-sm">{u.username}</td>
                    <td className="p-3 text-body text-sm">{u.email || '-'}</td>
                    <td className="p-3">
                      <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                        u.role === 'admin' ? 'bg-primary/10 text-primary' : 'bg-surface-soft text-muted'
                      }`}>
                        {u.role}
                      </span>
                    </td>
                    <td className="p-3">
                      {(u.branches || []).length === 0 ? (
                        <span className="text-muted text-xs italic">belum ada</span>
                      ) : (
                        <div className="flex flex-wrap gap-1 max-w-xs">
                          {u.branches.map((b) => (
                            <span key={b} className="text-xs bg-surface-soft text-body px-1.5 py-0.5 rounded-md">{b}</span>
                          ))}
                        </div>
                      )}
                    </td>
                    <td className="p-3">
                      <button
                        onClick={() => handleToggleStatus(u)}
                        disabled={processingId === u.id}
                        className="flex items-center gap-1 text-xs font-medium hover:opacity-80 disabled:opacity-50"
                      >
                        {processingId === u.id ? (
                          <Loader2 size={15} className="animate-spin" />
                        ) : u.is_active ? (
                          <><ToggleRight size={17} className="text-success" /> Aktif</>
                        ) : (
                          <><ToggleLeft size={17} className="text-error" /> Nonaktif</>
                        )}
                      </button>
                    </td>
                    <td className="p-3 flex gap-2">
                      <button
                        onClick={() => { setEditingUser(u); setShowUserModal(true); }}
                        className="text-muted hover:text-ink transition-colors" title="Edit"
                      >
                        <Pencil size={16} />
                      </button>
                      <button
                        onClick={() => handleDeleteUser(u)}
                        disabled={processingId === u.id}
                        className="text-muted hover:text-error transition-colors disabled:opacity-50" title="Hapus"
                      >
                        <Trash2 size={16} />
                      </button>
                    </td>
                  </motion.tr>
                ))}
              </tbody>
            </table>
          </div>
          <PaginationBar page={page} totalPages={totalPages} onChange={setPage} totalItems={filteredUsers.length} pageSize={PAGE_SIZE} />
        </div>
      )}

      {/* Modal create/edit */}
      {showUserModal && (
        <UserModal
          key={editingUser?.id || 'new'}
          isOpen={showUserModal}
          onClose={() => { setShowUserModal(false); setEditingUser(null); }}
          onSave={handleSaveUser}
          user={editingUser}
          branches={branches}
          isSaving={saving}
        />
      )}

      {/* Confirm dialog */}
      {confirmState && (
        <ConfirmationDialog
          key="userConfirm"
          isOpen={!!confirmState}
          onClose={() => setConfirmState(null)}
          onConfirm={confirmState.onConfirm}
          title={confirmState.title}
          message={confirmState.message}
          isLoading={!!processingId}
        />
      )}
    </div>
  );
}
