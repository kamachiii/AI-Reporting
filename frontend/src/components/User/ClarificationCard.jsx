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
    <div className="bg-white border border-hairline rounded-xl p-5 shadow-xs space-y-4 max-w-2xl">
      {/* Header Status */}
      <div className="flex items-center justify-between gap-2 border-b border-hairline pb-3">
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-md text-xs font-medium bg-amber-50 text-amber-900 border border-amber-200">
            <HelpCircle size={13} className="text-amber-700" />
            Perlu Klarifikasi Parameter
          </span>
        </div>
        {answer?.duration_ms !== undefined && (
          <span className="text-[11px] text-muted font-mono tabular-nums">
            {answer.duration_ms < 10 ? '< 10 ms' : `${answer.duration_ms} ms`}
          </span>
        )}
      </div>

      {/* Pertanyaan Klarifikasi */}
      <p className="text-sm text-ink font-serif italic leading-relaxed">
        &ldquo;{message}&rdquo;
      </p>

      {/* Daftar Pilihan Opsi */}
      <div className="space-y-2 pt-1">
        <div className="text-[11px] font-semibold text-muted uppercase tracking-wider">
          Pilih salah satu divisi/kategori untuk melanjutkan eksplorasi:
        </div>
        <div className="grid grid-cols-1 gap-2">
          {options.map((opt) => {
            const IconComp = ICON_MAP[opt.icon] || HelpCircle;
            return (
              <button
                key={opt.id}
                type="button"
                onClick={() => onAsk && onAsk(opt.prompt)}
                className="w-full group text-left p-3 rounded-lg border border-hairline bg-surface-soft/40 hover:bg-white hover:border-primary/60 hover:shadow-2xs transition-all flex items-center justify-between gap-3 cursor-pointer"
              >
                <div className="flex items-start gap-3 min-w-0">
                  <div className="w-8 h-8 rounded-md bg-white border border-hairline text-ink flex items-center justify-center shrink-0 group-hover:border-primary/40 group-hover:text-primary transition-colors">
                    <IconComp size={15} />
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm font-semibold text-ink group-hover:text-primary transition-colors">
                      {opt.label}
                    </div>
                    {opt.deskripsi && (
                      <div className="text-xs text-muted mt-0.5 line-clamp-1">
                        {opt.deskripsi}
                      </div>
                    )}
                  </div>
                </div>
                <div className="text-muted/60 group-hover:text-primary group-hover:translate-x-0.5 transition-all shrink-0">
                  <ArrowRight size={15} />
                </div>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
