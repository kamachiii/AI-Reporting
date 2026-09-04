import { HelpCircle, Car, Wrench, Layers, ArrowRight } from 'lucide-react';

const ICON_MAP = {
  Car,
  Wrench,
  Layers,
};

/**
 * Komponen kartu dialog interaktif saat kueri pengguna terdeteksi ambigu
 * (Interactive Clarification Loop).
 */
export default function ClarificationCard({ answer, onAsk }) {
  const options = answer?.options || [];
  const message = answer?.clarification_message || answer?.ringkasan || 'Silakan pilih opsi yang sesuai:';

  return (
    <div className="bg-white border border-hairline rounded-2xl p-5 shadow-sm space-y-4 max-w-2xl">
      {/* Header Status */}
      <div className="flex items-center justify-between gap-2 border-b border-hairline pb-3">
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-amber-50 text-amber-800 border border-amber-200/80">
            <HelpCircle size={14} className="text-amber-600" />
            Perlu Klarifikasi
          </span>
          <span className="inline-flex items-center gap-1 text-[11px] text-text-subtle bg-surface-soft px-2 py-0.5 rounded-full border border-hairline">
            Klarifikasi Instan (0-Token)
          </span>
        </div>
        {answer?.duration_ms !== undefined && (
          <span className="text-[11px] text-text-subtle">
            {answer.duration_ms < 10 ? '< 10 ms' : `${answer.duration_ms} ms`}
          </span>
        )}
      </div>

      {/* Pertanyaan Klarifikasi */}
      <p className="text-sm text-text-main font-serif italic leading-relaxed">
        &ldquo;{message}&rdquo;
      </p>

      {/* Daftar Pilihan Opsi */}
      <div className="space-y-2 pt-1">
        <div className="text-[11px] font-semibold text-text-subtle uppercase tracking-wider">
          Pilih salah satu divisi/kategori untuk melanjutkan:
        </div>
        <div className="grid grid-cols-1 gap-2.5">
          {options.map((opt) => {
            const IconComp = ICON_MAP[opt.icon] || HelpCircle;
            return (
              <button
                key={opt.id}
                type="button"
                onClick={() => onAsk && onAsk(opt.prompt)}
                className="w-full group text-left p-3.5 rounded-xl border border-hairline bg-canvas hover:border-primary/60 hover:bg-primary/5 hover:shadow-xs transition-all flex items-center justify-between gap-3 cursor-pointer"
              >
                <div className="flex items-start gap-3 min-w-0">
                  <div className="w-8 h-8 rounded-lg bg-primary/10 text-primary flex items-center justify-center shrink-0 group-hover:scale-105 group-hover:bg-primary group-hover:text-white transition-all">
                    <IconComp size={16} />
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm font-semibold text-text-main group-hover:text-primary transition-colors">
                      {opt.label}
                    </div>
                    {opt.deskripsi && (
                      <div className="text-xs text-text-subtle mt-0.5 line-clamp-1">
                        {opt.deskripsi}
                      </div>
                    )}
                  </div>
                </div>
                <div className="text-text-subtle/50 group-hover:text-primary group-hover:translate-x-0.5 transition-all shrink-0">
                  <ArrowRight size={16} />
                </div>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
