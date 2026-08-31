import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { X, Loader2, CheckCircle, Save } from 'lucide-react';
import { notify } from '../../../utils/notification';
import { api } from '../../../services/api';

/**
 * Modal kelola Knowledge Base satu tenant (F2.0).
 * Isi KB diedit sebagai JSON di textarea; tombol "Validasi" memanggil
 * endpoint dry-run (TIDAK menyimpan), tombol "Simpan" memanggil PUT.
 * Error validasi ditampilkan per entri sesuai hasil dari backend.
 */
export default function KnowledgeBaseModal({ isOpen, onClose, branchCode }) {
  const [kbText, setKbText] = useState('');
  const [meta, setMeta] = useState(null);        // {sumber, updated_at} dari GET
  const [loading, setLoading] = useState(true);  // modal di-mount ulang per tenant
  const [validating, setValidating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState(null);    // null = belum validasi; [] = valid
  const [parseError, setParseError] = useState(null);

  useEffect(() => {
    let batal = false;
    (async () => {
      try {
        const data = await api.getTenantKnowledgeBase(branchCode);
        if (batal) return;
        setKbText(JSON.stringify(data.knowledge_base ?? {}, null, 2));
        setMeta(data);
      } catch (e) {
        if (!batal) notify.error(e.response?.data?.detail || 'Gagal memuat knowledge base');
      } finally {
        if (!batal) setLoading(false);
      }
    })();
    return () => { batal = true; };
  }, [branchCode]);

  if (!isOpen) return null;

  // Ambil objek KB dari textarea; return null + tampilkan parse error bila rusak.
  const ambilParsed = () => {
    try {
      const parsed = JSON.parse(kbText);
      setParseError(null);
      return parsed;
    } catch (e) {
      setParseError(e.message);
      return null;
    }
  };

  const handleValidate = async () => {
    const parsed = ambilParsed();
    if (parsed === null) return;
    setValidating(true);
    setErrors(null);
    try {
      const r = await api.validateTenantKnowledgeBase(branchCode, parsed);
      setErrors(r.errors || []);
      if (r.ok) notify.success('Knowledge base valid');
    } catch (e) {
      const detail = e.response?.data?.detail;
      setErrors(Array.isArray(detail?.errors)
        ? detail.errors
        : [typeof detail === 'string' ? detail : 'Gagal memvalidasi knowledge base']);
    } finally {
      setValidating(false);
    }
  };

  const handleSave = async () => {
    const parsed = ambilParsed();
    if (parsed === null) return;
    setSaving(true);
    setErrors(null);
    try {
      await api.saveTenantKnowledgeBase(branchCode, parsed);
      notify.success(`Knowledge base ${branchCode} berhasil disimpan`);
      onClose();
    } catch (e) {
      const detail = e.response?.data?.detail;
      if (Array.isArray(detail?.errors)) {
        setErrors(detail.errors); // 422: tampilkan error per entri di panel
      } else {
        notify.error(typeof detail === 'string' ? detail : 'Gagal menyimpan knowledge base');
      }
    } finally {
      setSaving(false);
    }
  };

  const field = "w-full px-3 py-2 border border-hairline rounded-md bg-canvas focus:ring-2 focus:ring-primary/30 text-sm";

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <motion.div
        initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}
        transition={{ type: 'spring', damping: 20, stiffness: 300 }}
        className="bg-white rounded-xl p-6 max-w-2xl w-full shadow-xl border border-hairline relative max-h-[90vh] overflow-y-auto"
      >
        <button onClick={onClose} aria-label="Tutup" className="absolute right-4 top-4 text-muted hover:text-ink">
          <X size={20} />
        </button>
        <h3 className="font-serif text-lg text-ink mb-1">
          Knowledge Base — {branchCode}
        </h3>
        <p className="text-xs text-muted mb-4">
          {loading
            ? 'Memuat…'
            : `Sumber: ${meta?.sumber || '-'}${meta?.updated_at ? ` · diperbarui ${new Date(meta.updated_at).toLocaleString('id-ID')}` : ''}`}
        </p>

        <label className="block text-sm font-medium text-ink mb-1" htmlFor="kb-json">
          Isi Knowledge Base (JSON)
        </label>
        <textarea
          id="kb-json"
          value={kbText}
          onChange={(e) => setKbText(e.target.value)}
          disabled={loading}
          rows={14}
          spellCheck={false}
          className={`${field} font-mono text-xs leading-relaxed`}
          placeholder='{ "glossary": [{ "istilah": "omzet", "arti": "SUM(penjualan.harga_deal)" }] }'
        />

        {/* Panel hasil validasi / parse: error per entri dari endpoint validasi */}
        {parseError && (
          <div className="mt-3 p-3 rounded-md bg-error/5 border border-error/20 text-error text-xs">
            <p className="font-medium mb-1">JSON tidak valid:</p>
            <p className="font-mono">{parseError}</p>
          </div>
        )}
        {errors !== null && !parseError && errors.length > 0 && (
          <div className="mt-3 p-3 rounded-md bg-error/5 border border-error/20 text-error text-xs">
            <p className="font-medium mb-1">Ditemukan {errors.length} masalah:</p>
            <ul className="list-disc list-inside space-y-0.5">
              {errors.map((err, i) => <li key={i} className="font-mono">{err}</li>)}
            </ul>
          </div>
        )}
        {errors !== null && !parseError && errors.length === 0 && (
          <div className="mt-3 p-3 rounded-md bg-success/5 border border-success/20 text-success text-xs font-medium">
            JSON valid sesuai struktur knowledge base.
          </div>
        )}

        <div className="flex justify-between items-center gap-2 pt-3 border-t border-hairline mt-4">
          <button type="button" onClick={handleValidate} disabled={loading || validating || saving}
            className="px-4 py-2 border border-hairline rounded-md text-sm hover:bg-surface-soft disabled:opacity-50 flex items-center gap-2">
            {validating ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle size={14} />}
            Validasi
          </button>
          <div className="flex gap-2">
            <button type="button" onClick={onClose}
              className="px-4 py-2 border border-hairline rounded-md text-sm hover:bg-surface-soft">Batal</button>
            <button type="button" onClick={handleSave} disabled={loading || validating || saving}
              className="px-4 py-2 bg-primary text-white rounded-md text-sm hover:bg-primary-active disabled:opacity-50 flex items-center gap-2">
              {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
              Simpan
            </button>
          </div>
        </div>
      </motion.div>
    </div>
  );
}
