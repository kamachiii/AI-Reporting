import { HelpCircle, Car, Wrench, Layers } from 'lucide-react';

const ICON_MAP = {
  Car,
  Wrench,
  Layers,
};

/**
 * Komponen dialog klarifikasi percakapan interaktif
 * (Multi-turn Conversational Clarification).
 * Mendukung balasan bebas via input chat maupun opsi chip cepat.
 */
export default function ClarificationCard({ answer, onAsk }) {
  const options = answer?.options || [];
  const message = answer?.clarification_message || answer?.ringkasan || 'Silakan sebutkan parameter data yang ingin Anda periksa:';

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

      {/* Pertanyaan Klarifikasi Alami (Sans-serif berorientasi keterbacaan tinggi) */}
      <p className="text-[14px] text-ink font-sans font-normal leading-relaxed">
        {message}
      </p>

      {/* Panduan Balas di Chat & Quick Action Chips */}
      {options.length > 0 && (
        <div className="space-y-2.5 pt-3 border-t border-hairline">
          <div className="text-xs text-muted font-sans font-medium flex items-center justify-between">
            <span>Ketik balasan Anda di kolom pesan di bawah, atau pilih opsi cepat:</span>
          </div>
          <div className="flex flex-wrap gap-2 pt-0.5">
            {options.map((opt) => {
              const IconComp = ICON_MAP[opt.icon] || HelpCircle;
              const displayLabel = (opt.label || '').replace(/\s*tahun\s*2025/gi, '').trim();
              const promptVal = opt.prompt ? opt.prompt.replace(/\s*tahun\s*2025/gi, '').trim() : displayLabel;
              return (
                <button
                  key={opt.id}
                  type="button"
                  onClick={() => onAsk && onAsk(promptVal)}
                  className="group inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full text-xs font-medium border border-hairline bg-canvas hover:bg-surface-cream-strong hover:border-primary/50 text-ink hover:text-primary transition-all cursor-pointer shadow-2xs hover:shadow-xs"
                >
                  <IconComp size={13} className="text-muted group-hover:text-primary transition-colors shrink-0" />
                  <span>{displayLabel}</span>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

