import { Check } from 'lucide-react';
import { cn } from '@/lib/cn';
import { Icon } from '../ui/Icon';

/** Circular completion checkbox (the task's primary control). */
export function CompleteCheck({
  checked,
  onChange,
  label,
  disabled,
  size = 18,
}: {
  checked: boolean;
  onChange: () => void;
  label: string;
  disabled?: boolean;
  size?: number;
}) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={(e) => {
        e.stopPropagation();
        onChange();
      }}
      style={{ width: size, height: size }}
      className={cn(
        'grid shrink-0 place-items-center rounded-full border transition-colors duration-150',
        checked
          ? 'border-ok bg-ok text-surface'
          : 'border-muted-2 text-transparent hover:border-ok hover:text-ok',
        disabled && 'cursor-default opacity-60 hover:border-muted-2 hover:text-transparent',
      )}
    >
      <Icon icon={Check} size={size - 6} strokeWidth={2.5} />
    </button>
  );
}
