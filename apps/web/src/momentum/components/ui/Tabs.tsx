import * as T from '@radix-ui/react-tabs';
import type { ComponentProps } from 'react';
import { cn } from '@/lib/cn';

/** Underline tabs: used for project views. */
export const Tabs = T.Root;

export function TabsList({ className, ...p }: ComponentProps<typeof T.List>) {
  return <T.List className={cn('flex gap-4 border-b border-hair-soft', className)} {...p} />;
}

export function TabsTrigger({ className, ...p }: ComponentProps<typeof T.Trigger>) {
  return (
    <T.Trigger
      className={cn(
        '-mb-px border-b-2 border-transparent pb-2 text-sm text-muted hover:text-ink data-[state=active]:border-ink data-[state=active]:text-ink',
        className,
      )}
      {...p}
    />
  );
}

export const TabsContent = T.Content;

/** Segmented control: used for sub-modes inside a view (never for top-level views). */
export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string }[];
  label: string;
}) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className="inline-flex rounded-md border border-hairline bg-surface-2 p-0.5"
    >
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            'rounded-[5px] px-2.5 py-0.5 text-[13px] text-muted',
            value === o.value && 'bg-surface text-ink shadow-[0_0_0_1px_var(--hairline)]',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
