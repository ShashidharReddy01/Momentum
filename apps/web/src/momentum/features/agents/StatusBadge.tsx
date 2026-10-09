import { Icon } from '@/components/ui/Icon';
import { cn } from '@/lib/cn';
import { RUN_STATUS } from './runMeta';

export function StatusBadge({ status }: { status: string }) {
  const s = RUN_STATUS[status] ?? RUN_STATUS.queued!;
  return (
    <span className={cn('inline-flex items-center gap-1 text-sm font-medium', s.className)}>
      <Icon
        icon={s.icon}
        size={15}
        className={status === 'running' ? 'animate-spin motion-reduce:animate-none' : undefined}
      />
      {s.label}
    </span>
  );
}
