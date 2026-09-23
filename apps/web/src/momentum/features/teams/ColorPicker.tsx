import { Check } from 'lucide-react';
import { Icon } from '@/components/ui/Icon';
import { cn } from '@/lib/cn';

export const COLOR_TOKENS = Array.from({ length: 12 }, (_, i) => `proj-${i + 1}`);

export function colorVar(token: string | null | undefined): string {
  return token ? `var(--${token})` : 'var(--muted-2)';
}

export function ColorPicker({
  value,
  onChange,
}: {
  value: string | null;
  onChange: (token: string) => void;
}) {
  return (
    <div role="radiogroup" aria-label="Color" className="flex flex-wrap gap-1.5">
      {COLOR_TOKENS.map((t) => (
        <button
          key={t}
          type="button"
          role="radio"
          aria-checked={value === t}
          aria-label={t}
          onClick={() => onChange(t)}
          className={cn(
            'grid h-6 w-6 place-items-center rounded-full',
            value === t && 'ring-2 ring-ink ring-offset-2 ring-offset-surface',
          )}
          style={{ background: colorVar(t) }}
        >
          {value === t ? <Icon icon={Check} size={13} className="text-surface" /> : null}
        </button>
      ))}
    </div>
  );
}
