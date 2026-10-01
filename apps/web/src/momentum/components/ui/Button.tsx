import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';
import { Loader2 } from 'lucide-react';
import { forwardRef, type ButtonHTMLAttributes } from 'react';
import { cn } from '@/lib/cn';
import { Icon } from './Icon';

export const buttonVariants = cva(
  // DESIGN.md: every button answers within 100 ms: hover one step, press scales to 0.97, focus is
  // a 2 px lime-deep ring (base.css), loading keeps the width and shows a spinner
  'inline-flex select-none items-center justify-center gap-1.5 whitespace-nowrap rounded-md font-semibold transition-[background-color,color,border-color,transform,box-shadow] duration-100 ease-out active:scale-[0.97] disabled:pointer-events-none disabled:opacity-50 aria-busy:cursor-progress',
  {
    variants: {
      variant: {
        primary: 'bg-accent text-on-accent shadow-raise hover:bg-accent-hover',
        /** Only for buttons that run an AI action (amber = AI). */
        ai: 'bg-amber-2 text-amber-ink border border-dashed border-amber hover:bg-amber-hi/40',
        ghost:
          'border border-hairline bg-surface text-ink shadow-raise hover:border-muted-2/60 hover:bg-surface-2',
        text: 'text-ink-2 hover:bg-surface-2 hover:text-ink',
        danger: 'bg-crit text-surface hover:opacity-90',
        /** Buttons placed on the graphite rail (sidebar). */
        sidebar: 'bg-sidebar-hover text-sidebar-ink hover:bg-sidebar-active',
      },
      size: {
        sm: 'h-7 px-2.5 text-[13px]',
        md: 'h-8 px-3 text-sm',
        icon: 'h-8 w-8 p-0',
        'icon-sm': 'h-7 w-7 p-0',
      },
    },
    defaultVariants: { variant: 'ghost', size: 'md' },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant, size, asChild, loading, disabled, children, type, ...props },
  ref,
) {
  const Comp = asChild ? Slot : 'button';
  return (
    <Comp
      ref={ref}
      type={asChild ? undefined : (type ?? 'button')}
      className={cn(buttonVariants({ variant, size }), className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {asChild ? (
        children // Slot needs exactly one child element (e.g. a Link styled as a button)
      ) : (
        <>
          {loading ? <Icon icon={Loader2} className="animate-spin" /> : null}
          {children}
        </>
      )}
    </Comp>
  );
});
