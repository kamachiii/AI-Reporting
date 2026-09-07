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
    <div className="bg-surface-card border border-hairline rounded-lg p-5 shadow-2xs space-y-4 max-w-2xl">
      {/* Header Status */}
      <div className="flex items-center justify-between gap-2 border-b border-hairline pb-3">
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-md text-xs font-mono bg-canvas border border-hairline text-ink">
            <HelpCircle size={12} className="text-primary" />
            <span>Klarifikasi Parameter Diperlukan</span>
          </span>
        </div>
        {answer?.duration_ms !== undefined && (
          <span className="text-[11px] text-muted font-mono tabular-nums">
            {answer.duration_ms < 10 ? '< 10 ms' : `${answer.duration_ms} ms`}
          </span>
        )}
      </div>

      {/* Pertanyaan Klarifikasi */}
      <p className="text-[15px] text-ink font-serif italic leading-relaxed">
        &ldquo;{message}&rdquo;
      </p>

      {/* Daftar Pilihan Opsi */}
      <div className="space-y-2 pt-1">
        <div className="text-[10px] font-mono text-muted-soft uppercase tracking-widest font-medium">
          Pilih salah satu domain data untuk melanjutkan:
        </div>
        <div className="grid grid-cols-1 gap-2">
          {options.map((opt) => {
            const IconComp = ICON_MAP[opt.icon] || HelpCircle;
            return (
              <button
                key={opt.id}
                type="button"
                onClick={() => onAsk && onAsk(opt.prompt)}
                className="w-full group text-left p-3.5 rounded-md border border-hairline bg-canvas hover:bg-surface-cream-strong hover:border-primary/50 transition-all flex items-center justify-between gap-3 cursor-pointer shadow-2xs hover:shadow-xs"
              >
                <div className="flex items-start gap-3 min-w-0">
                  <div className="w-8 h-8 rounded-md bg-surface-card border border-hairline text-ink flex items-center justify-center shrink-0 group-hover:border-primary/40 group-hover:text-primary transition-colors">
                    <IconComp size={15} />
                  </div>
                  <div className="min-w-0">
                    <div className="text-xs font-medium text-ink group-hover:text-primary transition-colors font-sans">
                      {opt.label}
                    </div>
                    {opt.deskripsi && (
                      <div className="text-[11px] text-muted mt-0.5 line-clamp-1">
                        {opt.deskripsi}
                      </div>
                    )}
                  </div>
                </div>
                <div className="text-muted group-hover:text-primary group-hover:translate-x-0.5 transition-all shrink-0">
                  <ArrowRight size={14} />
                </div>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
