import { motion } from 'framer-motion';
import { X, CheckCircle, XCircle } from 'lucide-react';

/**
 * Modal detail informasi cabang: identitas + status koneksi database.
 * Data dari props (sudah tersedia di useCompanyBranchData).
 */
export default function BranchDetailModal({ isOpen, onClose, branch, companyName, tenantData, connectionStatus }) {
  if (!isOpen || !branch) return null;

  const tenant = tenantData[branch.code];
  const st = connectionStatus[branch.code];

  const Row = ({ label, children }) => (
    <div className="flex justify-between gap-4 py-2 border-b border-hairline last:border-b-0">
      <span className="text-xs text-muted shrink-0 w-36">{label}</span>
      <span className="text-sm text-body text-right flex-1">{children}</span>
    </div>
  );

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <motion.div
        initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}
        transition={{ type: 'spring', damping: 20, stiffness: 300 }}
        className="bg-white rounded-xl max-w-md w-full shadow-xl border border-hairline relative max-h-[85vh] overflow-y-auto"
      >
        <button onClick={onClose} aria-label="Tutup" className="absolute right-4 top-4 text-muted hover:text-ink">
          <X size={20} />
        </button>

        {/* Header */}
        <div className="p-6 pb-4">
          <h3 className="font-serif text-lg text-ink leading-snug">{branch.name}</h3>
          <span className="text-xs text-muted">Kode: {branch.code}</span>
        </div>

        <div className="px-6 pb-6">
          <Row label="Perusahaan">{companyName || branch.company_code}</Row>
          <Row label="Status Cabang">
            {branch.is_active
              ? <span className="inline-flex items-center gap-1.5 text-success font-medium"><span className="w-1.5 h-1.5 rounded-full bg-success" /> Aktif</span>
              : <span className="inline-flex items-center gap-1.5 text-error font-medium"><span className="w-1.5 h-1.5 rounded-full bg-error" /> Nonaktif</span>}
          </Row>
          <Row label="Alamat">{branch.address || '-'}</Row>

          <p className="text-xs font-medium text-muted uppercase tracking-wide mt-5 mb-1">Database (Tenant)</p>

          {tenant ? (
            <>
              <Row label="Status Koneksi">
                {st === 'connected' ? (
                  <span className="inline-flex items-center gap-1.5 text-success font-medium"><CheckCircle size={14} /> Connected</span>
                ) : st === 'checking' ? (
                  <span className="text-muted italic">Memeriksa…</span>
                ) : (
                  <span className="inline-flex items-center gap-1.5 text-error font-medium"><XCircle size={14} /> Disconnected</span>
                )}
              </Row>
              <Row label="Host">{tenant.db_host}</Row>
              <Row label="Port">{tenant.db_port}</Row>
              <Row label="Nama Database">{tenant.db_name}</Row>
              <Row label="Username DB">{tenant.db_username}</Row>
            </>
          ) : (
            <p className="text-sm text-muted italic mt-2">
              Belum ada database yang dihubungkan ke cabang ini.
            </p>
          )}
        </div>
      </motion.div>
    </div>
  );
}
