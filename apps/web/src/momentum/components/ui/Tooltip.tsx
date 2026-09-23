import * as T from '@radix-ui/react-tooltip';
import type { ReactNode } from 'react';
import { usePortalContainer } from '@/providers/portal';
import { Kbd } from './Kbd';

export const TooltipProvider = T.Provider;

export function Tooltip({
  content,
  shortcut,
  children,
}: {
  content: ReactNode;
  shortcut?: string;
  children: ReactNode;
}) {
  const container = usePortalContainer();
  return (
    <T.Root delayDuration={400}>
      <T.Trigger asChild>{children}</T.Trigger>
      <T.Portal container={container}>
        <T.Content
          sideOffset={6}
          className="z-50 flex items-center gap-2 rounded-md bg-ink px-2 py-1 text-xs text-paper shadow-pop"
        >
          {content}
          {shortcut ? <Kbd combo={shortcut} inverted /> : null}
        </T.Content>
      </T.Portal>
    </T.Root>
  );
}
