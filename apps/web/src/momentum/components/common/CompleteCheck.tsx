import { Check } from 'lucide-react';
import { cn } from '@/lib/cn';
import { Icon } from '../ui/Icon';

/** Completion checkbox (the task's primary control) — round for a regular task, a rotated
 * square ("diamond") for a milestone (S2.4.3), matching the diamond check icon convention. */
export function CompleteCheck({
  checked,
  onChange,
  label,
  disabled,
  size = 18,
  variant = 'round',
}: {
  checked: boolean;
  onChange: () => void;
  label: string;
  disabled?: boolean;
  size?: number;
  variant?: 'round' | 'diamond';
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
        'grid shrink-0 place-items-center border transition-colors duration-150',
        variant === 'diamond' ? 'rotate-45 rounded-[3px]' : 'rounded-full',
        checked
          ? 'border-ok bg-ok text-surface'
          : 'border-muted-2 text-transparent hover:border-ok hover:text-ok',
        disabled && 'cursor-default opacity-60 hover:border-muted-2 hover:text-transparent',
      )}
    >
      <Icon
        icon={Check}
        size={size - 6}
        strokeWidth={2.5}
        className={variant === 'diamond' ? '-rotate-45' : undefined}
      />
    </button>
  );
}
