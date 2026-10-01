import * as T from '@radix-ui/react-tooltip';
import type { ReactNode } from 'react';
import { usePortalContainer } from '@/providers/portal';
import { Kbd } from './Kbd';

export const TooltipProvider = T.Provider;

export function Tooltip({
  content,
  shortcut,
  side,
  children,
}: {
  content: ReactNode;
  shortcut?: string;
  side?: 'top' | 'right' | 'bottom' | 'left';
  children: ReactNode;
}) {
  const container = usePortalContainer();
  return (
    <T.Root delayDuration={400}>
      <T.Trigger asChild>{children}</T.Trigger>
      <T.Portal container={container}>
        <T.Content
          side={side}
          sideOffset={6}
          className="z-50 flex items-center gap-2 rounded-md bg-ink px-2 py-1 text-xs font-semibold text-surface shadow-pop data-[state=delayed-open]:animate-[m-fade-in_var(--dur-2)_var(--ease)]"
        >
          {content}
          {shortcut ? <Kbd combo={shortcut} inverted /> : null}
        </T.Content>
      </T.Portal>
    </T.Root>
  );
}
