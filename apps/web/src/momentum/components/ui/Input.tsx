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
        'h-8 w-full rounded-md border border-hairline bg-paper-2 px-2.5 text-sm placeholder:text-muted-2 focus:border-focus focus:outline-none',
        className,
      )}
      {...props}
    />
  );
});
