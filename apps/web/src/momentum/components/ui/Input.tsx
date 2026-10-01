import { forwardRef, type InputHTMLAttributes } from 'react';
import { cn } from '@/lib/cn';

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...props },
  ref,
) {
  return (
    <input
      ref={ref}
      className={cn(
        'h-8 w-full rounded-md border border-hairline bg-surface px-2.5 text-sm shadow-raise transition-[border-color,box-shadow] duration-100 placeholder:text-muted-2 hover:border-muted-2/60 focus:border-focus focus:outline-none focus:ring-2 focus:ring-focus/25 aria-[invalid=true]:border-crit',
        className,
      )}
      {...props}
    />
  );
});
