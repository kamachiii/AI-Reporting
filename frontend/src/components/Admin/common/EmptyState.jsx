import { motion } from 'framer-motion';

/**
 * Empty state ilustratif (CSS-only, tanpa aset) — mengikuti palet warm
 * terracotta aplikasi. Dipakai di semua tab admin agar konsisten.
 *
 * variant: 'box'  -> dokumen + kaca pembesar (pencarian tak menemukan apa pun)
 *          'bot'  -> kepala robot ramah (belum ada konfigurasi AI)
 *          'plug' -> colokan terputus (belum ada database/tenant)
 */
const ICONS = {
  box: (
    <>
      <rect x="42" y="30" width="76" height="88" rx="8" fill="var(--color-surface-soft)" stroke="var(--color-hairline)" strokeWidth="2.5" />
      <line x1="56" y1="50" x2="104" y2="50" stroke="var(--color-hairline)" strokeWidth="4" strokeLinecap="round" />
      <line x1="56" y1="66" x2="96" y2="66" stroke="var(--color-hairline)" strokeWidth="4" strokeLinecap="round" />
      <line x1="56" y1="82" x2="100" y2="82" stroke="var(--color-hairline)" strokeWidth="4" strokeLinecap="round" />
      <circle cx="98" cy="94" r="22" fill="var(--color-canvas)" stroke="var(--color-primary)" strokeWidth="3.5" />
      <line x1="114" y1="110" x2="126" y2="122" stroke="var(--color-primary)" strokeWidth="5" strokeLinecap="round" />
    </>
  ),
  bot: (
    <>
      <rect x="38" y="46" width="84" height="64" rx="16" fill="var(--color-surface-soft)" stroke="var(--color-hairline)" strokeWidth="2.5" />
      <circle cx="62" cy="74" r="7" fill="var(--color-primary)" />
      <circle cx="98" cy="74" r="7" fill="var(--color-primary)" />
      <path d="M 66 92 Q 80 102 94 92" fill="none" stroke="var(--color-muted)" strokeWidth="3.5" strokeLinecap="round" />
      <line x1="80" y1="46" x2="80" y2="32" stroke="var(--color-hairline)" strokeWidth="4" strokeLinecap="round" />
      <circle cx="80" cy="26" r="6" fill="var(--color-success)" />
    </>
  ),
  plug: (
    <>
      <rect x="34" y="52" width="52" height="40" rx="10" transform="rotate(-18 60 72)" fill="var(--color-surface-soft)" stroke="var(--color-hairline)" strokeWidth="2.5" />
      <line x1="86" y1="58" x2="102" y2="52" stroke="var(--color-muted)" strokeWidth="4" strokeLinecap="round" />
      <line x1="84" y1="74" x2="100" y2="68" stroke="var(--color-muted)" strokeWidth="4" strokeLinecap="round" />
      <rect x="106" y="70" width="24" height="20" rx="5" transform="rotate(12 118 80)" fill="var(--color-surface-card)" stroke="var(--color-hairline)" strokeWidth="2.5" />
      <path d="M 96 108 Q 120 116 142 100" fill="none" stroke="var(--color-primary)" strokeWidth="4" strokeLinecap="round" strokeDasharray="1 9" />
    </>
  ),
};

export default function EmptyState({ icon: Icon, variant = 'box', title, description }) {
  return (
    <div className="bg-white rounded-xl border border-hairline p-12 flex flex-col items-center justify-center text-center text-muted select-none">
      {Icon ? (
        <Icon className="w-12 h-12 mb-3 text-hairline" />
      ) : (
        <motion.svg
          width="160"
          height="140"
          viewBox="0 0 160 140"
          fill="none"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: [0, -4, 0] }}
          transition={{
            opacity: { duration: 0.35 },
            y: { duration: 4, repeat: Infinity, ease: 'easeInOut' },
          }}
        >
          {ICONS[variant] || ICONS.box}
        </motion.svg>
      )}
      {title && <p className="font-medium text-ink mt-2">{title}</p>}
      {description && <p className="text-sm mt-1 max-w-xs">{description}</p>}
    </div>
  );
}
