import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import { ApiError } from '@/lib/api/errors';
import { Button } from '../ui/Button';
import { Icon } from '../ui/Icon';

export function EmptyState({
  icon,
  title,
  children,
  action,
}: {
  icon?: LucideIcon;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="mx-auto flex max-w-sm flex-col items-center gap-2 px-4 py-10 text-center">
      {icon ? <Icon icon={icon} size={28} className="text-muted-2" /> : null}
      <p className="font-medium">{title}</p>
      {children ? <p className="text-sm text-muted">{children}</p> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const requestId = error instanceof ApiError ? error.problem.request_id : undefined;
  const message = error instanceof Error ? error.message : 'Something went wrong';
  return (
    <div role="alert" className="mx-auto flex max-w-md flex-col items-center gap-2 px-4 py-10 text-center">
      <p className="font-medium">We couldn't load this</p>
      <p className="text-sm text-muted">{message}</p>
      {requestId ? <p className="font-mono text-xs text-muted-2 select-all">request {requestId}</p> : null}
      {onRetry ? (
        <Button className="mt-2" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </div>
  );
}
