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
}

export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  className,
  hideTitle,
}: DialogProps) {
  const container = usePortalContainer();
  return (
    <D.Root open={open} onOpenChange={onOpenChange}>
      <D.Portal container={container}>
        <D.Overlay className="fixed inset-0 z-40 bg-ink/20" />
        <D.Content
          aria-describedby={description ? undefined : undefined}
          className={cn(
            'fixed left-1/2 top-[14vh] z-50 w-[min(560px,calc(100vw-32px))] -translate-x-1/2 rounded-xl bg-surface shadow-pop',
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
