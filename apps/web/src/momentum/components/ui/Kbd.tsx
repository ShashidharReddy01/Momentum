import { formatCombo } from '@/lib/keyboard';
import { cn } from '@/lib/cn';

export function Kbd({ combo, inverted }: { combo: string; inverted?: boolean }) {
  return (
    <span className="inline-flex gap-0.5" aria-label={`Shortcut ${formatCombo(combo).join(' ')}`}>
      {formatCombo(combo).map((k, i) => (
        <kbd
          key={i}
          className={cn(
            'min-w-[18px] rounded-sm border px-1 text-center font-mono text-[10.5px] leading-[16px]',
            inverted ? 'border-muted text-cream-2' : 'border-hairline bg-paper-2 text-muted',
          )}
        >
          {k}
        </kbd>
      ))}
    </span>
  );
}
