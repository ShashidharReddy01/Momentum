import { cn } from '@/lib/cn';

export const RECORD_STATUS: Record<string, { label: string; className: string }> = {
  draft: { label: 'Draft', className: 'border-hairline text-muted' },
  needs_review: { label: 'Needs review', className: 'border-warn/50 bg-warn-tint text-warn' },
  ready: { label: 'Ready to approve', className: 'border-info/40 bg-info-tint text-info' },
  approved: { label: 'Approved', className: 'border-ok/40 bg-ok-tint text-ok' },
  rejected: { label: 'Rejected', className: 'border-crit/40 bg-crit-tint text-crit' },
  void: { label: 'Void', className: 'border-hairline text-muted-2 line-through' },
  superseded: { label: 'Replaced', className: 'border-hairline text-muted-2' },
};

/** A record's status pill (review screen, Records tab, the task's record panel). */
export function RecordStatus({ status }: { status: string }) {
  const s = RECORD_STATUS[status] ?? { label: status, className: 'border-hairline text-muted' };
  return (
    <span className={cn('inline-flex rounded-full border px-2 py-0.5 text-[11px] font-medium', s.className)}>
      {s.label}
    </span>
  );
}
