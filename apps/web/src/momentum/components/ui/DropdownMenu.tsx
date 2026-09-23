import * as M from '@radix-ui/react-dropdown-menu';
import type { ComponentProps, ReactNode } from 'react';
import { cn } from '@/lib/cn';
import { usePortalContainer } from '@/providers/portal';
import { Kbd } from './Kbd';

export const DropdownMenu = M.Root;
export const DropdownMenuTrigger = M.Trigger;

export function DropdownMenuContent({ className, ...props }: ComponentProps<typeof M.Content>) {
  const container = usePortalContainer();
  return (
    <M.Portal container={container}>
      <M.Content
        sideOffset={6}
        align="start"
        className={cn('z-50 min-w-[200px] rounded-lg bg-surface p-1 shadow-pop', className)}
        {...props}
      />
    </M.Portal>
  );
}

export function DropdownMenuItem({
  className,
  shortcut,
  hint,
  children,
  ...props
}: ComponentProps<typeof M.Item> & { shortcut?: string; hint?: ReactNode }) {
  return (
    <M.Item
      className={cn(
        'flex cursor-pointer select-none items-center gap-2 rounded-md px-2 py-1.5 text-sm outline-none data-[disabled]:cursor-default data-[disabled]:text-muted-2 data-[highlighted]:bg-surface-2',
        className,
      )}
      {...props}
    >
      <span className="flex flex-1 items-center gap-2">{children}</span>
      {hint ? <span className="text-xs text-muted-2">{hint}</span> : null}
      {shortcut ? <Kbd combo={shortcut} /> : null}
    </M.Item>
  );
}

export function DropdownMenuSeparator() {
  return <M.Separator className="my-1 h-px bg-hair-soft" />;
}

export function DropdownMenuLabel({ children }: { children: ReactNode }) {
  return <M.Label className="section-label px-2 pb-1 pt-2">{children}</M.Label>;
}
