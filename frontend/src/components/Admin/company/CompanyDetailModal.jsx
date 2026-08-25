import { motion } from 'framer-motion';
import { X, Building2, CheckCircle, XCircle, MinusCircle } from 'lucide-react';

/**
 * Modal detail informasi perusahaan: identitas + ringkasan cabang
 * di bawahnya (termasuk status koneksi DB tiap cabang).
 * Semua data dari props (frontend sudah memilikinya via useCompanyBranchData).
 */
export default function CompanyDetailModal({ isOpen, onClose, company, branches, connectionStatus }) {
  if (!isOpen || !company) return null;

  const companyBranches = branches.filter(b => b.company_code === company.code);
  const activeCount = companyBranches.filter(b => b.is_active).length;
  const connectedCount = companyBranches.filter(b => connectionStatus[b.code] === 'connected').length;

  const Row = ({ label, children }) => (
    <div className="flex justify-between gap-4 py-2 border-b border-hairline last:border-b-0">
      <span className="text-xs text-muted shrink-0 w-32">{label}</span>
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
        <div className="p-6 pb-4 flex items-start gap-3">
          <span className="w-10 h-10 rounded-full bg-primary/10 text-primary flex items-center justify-center shrink-0">
            <Building2 size={20} />
          </span>
          <div>
            <h3 className="font-serif text-lg text-ink leading-snug">{company.name}</h3>
            <span className="text-xs text-muted">Kode: {company.code}</span>
          </div>
        </div>

        {/* Identitas */}
        <div className="px-6">
          <Row label="Status">
            {company.is_active
              ? <span className="inline-flex items-center gap-1.5 text-success font-medium"><span className="w-1.5 h-1.5 rounded-full bg-success" /> Aktif</span>
              : <span className="inline-flex items-center gap-1.5 text-error font-medium"><span className="w-1.5 h-1.5 rounded-full bg-error" /> Nonaktif</span>}
          </Row>
          <Row label="Alamat">{company.address || '-'}</Row>
          <Row label="Jumlah Cabang">{companyBranches.length} cabang ({activeCount} aktif)</Row>
          <Row label="DB Terhubung">{connectedCount} dari {companyBranches.length}</Row>
        </div>

        {/* Daftar cabang */}
        <div className="p-6 pt-4">
          <p className="text-xs font-medium text-muted uppercase tracking-wide mb-2">Cabang</p>
          {companyBranches.length === 0 ? (
            <p className="text-sm text-muted italic">Belum ada cabang terdaftar.</p>
          ) : (
            <ul className="space-y-1.5">
              {companyBranches.map((b) => {
                const st = connectionStatus[b.code];
                return (
                  <li key={b.code} className="flex items-center justify-between text-sm bg-surface-soft rounded-md px-3 py-2">
                    <span className="text-body"><strong className="text-ink">{b.code}</strong> · {b.name}</span>
                    {st === 'connected' ? (
                      <CheckCircle size={15} className="text-success shrink-0" />
                    ) : st === 'checking' ? (
                      <MinusCircle size={15} className="text-muted shrink-0" />
                    ) : (
                      <XCircle size={15} className="text-hairline text-muted shrink-0 opacity-50" />
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </motion.div>
    </div>
  );
}
