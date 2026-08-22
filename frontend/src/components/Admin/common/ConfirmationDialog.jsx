import { motion, AnimatePresence } from 'framer-motion';
import { AlertTriangle, Loader2 } from 'lucide-react';

/**
 * Komponen reusable untuk konfirmasi tindakan.
 *
 * @param {boolean} isOpen
 * @param {function} onClose
 * @param {function} onConfirm
 * @param {string} title
 * @param {string} message
 * @param {boolean} isLoading
 */
export default function ConfirmationDialog({
  isOpen,
  onClose,
  onConfirm,
  title,
  message,
  isLoading = false,
}) {
  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 bg-black/50 flex items-center justify-center z-[60] p-4"
          onClick={(e) => {
            if (e.target === e.currentTarget && !isLoading) onClose();
          }}
        >
          <motion.div
            initial={{ scale: 0.95, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.95, opacity: 0 }}
            transition={{ type: 'spring', damping: 20, stiffness: 300 }}
            className="bg-white rounded-xl p-6 max-w-sm w-full shadow-xl border border-hairline"
          >
            <div className="flex items-start gap-3 mb-4">
              <AlertTriangle size={18} className="text-error mt-0.5" />
              <div>
                <h3 className="font-serif text-base text-ink">{title}</h3>
                <p className="text-sm text-muted mt-1">{message}</p>
              </div>
            </div>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={onClose}
                disabled={isLoading}
                className="px-4 py-2 border border-hairline rounded-md text-sm hover:bg-surface-soft disabled:opacity-50 transition-colors"
              >
                Batal
              </button>
              <button
                type="button"
                onClick={onConfirm}
                disabled={isLoading}
                className="flex items-center gap-2 px-4 py-2 bg-error text-white rounded-md text-sm hover:opacity-90 disabled:opacity-60 transition-opacity"
              >
                {isLoading && <Loader2 size={14} className="animate-spin" />}
                Hapus
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}