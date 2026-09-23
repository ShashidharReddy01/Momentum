import * as P from '@radix-ui/react-popover';
import type { ComponentProps } from 'react';
import { cn } from '@/lib/cn';
import { usePortalContainer } from '@/providers/portal';

export const Popover = P.Root;
export const PopoverTrigger = P.Trigger;
export const PopoverAnchor = P.Anchor;
export const PopoverClose = P.Close;

export function PopoverContent({ className, align = 'start', ...props }: ComponentProps<typeof P.Content>) {
  const container = usePortalContainer();
  return (
    <P.Portal container={container}>
      <P.Content
        align={align}
        sideOffset={6}
        className={cn('z-50 rounded-lg bg-surface p-1 shadow-pop outline-none', className)}
        {...props}
      />
    </P.Portal>
  );
}
