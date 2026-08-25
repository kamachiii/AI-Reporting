import { useEffect } from 'react';

/**
 * Keyboard shortcuts standar untuk tab admin:
 * - Esc  : tutup modal/dialog paling atas (guard: tidak menutup saat proses berjalan)
 * - "/"  : fokus ke input pencarian (id element dikirim via searchInputId)
 *
 * Pemakaian:
 *   useAdminShortcuts({
 *     onEscape: () => { ... },
 *     isBusy: saving || processing,
 *     searchInputId: 'tenant-search',
 *   });
 */
export default function useAdminShortcuts({ onEscape, isBusy = false, searchInputId }) {
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') {
        if (isBusy) return; // jangan tutup saat proses async berjalan
        onEscape?.();
      } else if (e.key === '/' && searchInputId) {
        const tag = document.activeElement?.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA') return;
        e.preventDefault();
        document.getElementById(searchInputId)?.focus();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onEscape, isBusy, searchInputId]);
}
