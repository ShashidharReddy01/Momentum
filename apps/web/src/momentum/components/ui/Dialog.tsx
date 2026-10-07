import * as D from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';
import { usePortalContainer } from '@/providers/portal';
import { IconButton } from './IconButton';

export interface DialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  children: ReactNode;
  className?: string;
  hideTitle?: boolean;
  /** Where focus goes when the dialog closes (a dialog opened from a menu item: the menu's
   * button, since the item itself is gone). Default: back to what had focus before. */
  returnFocus?: { current: HTMLElement | null };
}

export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  className,
  hideTitle,
  returnFocus,
}: DialogProps) {
  const container = usePortalContainer();
  return (
    <D.Root open={open} onOpenChange={onOpenChange}>
      <D.Portal container={container}>
        <D.Overlay className="fixed inset-0 z-40 bg-ink/25 data-[state=open]:animate-[m-fade-in_var(--dur-2)_var(--ease)]" />
        <D.Content
          aria-describedby={description ? undefined : undefined}
          onCloseAutoFocus={(e) => {
            if (!returnFocus?.current) return;
            e.preventDefault();
            returnFocus.current.focus();
          }}
          className={cn(
            'fixed left-1/2 top-[14vh] z-50 max-h-[calc(100dvh-16vh)] w-[min(560px,calc(100vw-32px))] -translate-x-1/2 overflow-auto rounded-xl bg-surface shadow-pop data-[state=open]:animate-[m-sheet-in_var(--dur-3)_var(--ease)]',
            className,
          )}
        >
          {hideTitle ? (
            <D.Title className="sr-only">{title}</D.Title>
          ) : (
            <div className="flex items-start justify-between gap-4 border-b border-hair-soft px-5 py-4">
              <div>
                <D.Title className="text-[15px] font-semibold">{title}</D.Title>
                {description ? (
                  <D.Description className="text-sm text-muted">{description}</D.Description>
                ) : null}
              </div>
              <D.Close asChild>
                <IconButton icon={X} label="Close" size="icon-sm" />
              </D.Close>
            </div>
          )}
          {hideTitle && description ? <D.Description className="sr-only">{description}</D.Description> : null}
          {children}
        </D.Content>
      </D.Portal>
    </D.Root>
  );
}
