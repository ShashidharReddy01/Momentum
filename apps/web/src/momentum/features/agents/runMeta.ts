import { AlertTriangle, Ban, CheckCircle2, Clock, Loader2, Wallet, type LucideIcon } from 'lucide-react';

export const RUN_STATUS: Record<string, { label: string; icon: LucideIcon; className: string }> = {
  queued: { label: 'Queued', icon: Clock, className: 'text-muted' },
  running: { label: 'Running', icon: Loader2, className: 'text-muted' },
  succeeded: { label: 'Done', icon: CheckCircle2, className: 'text-ok' },
  failed: { label: 'Failed', icon: AlertTriangle, className: 'text-crit' },
  cancelled: { label: 'Cancelled', icon: Ban, className: 'text-muted' },
  budget_exceeded: { label: 'Budget used up', icon: Wallet, className: 'text-warn' },
};

export const TRIGGER_LABEL: Record<string, string> = {
  assigned: 'Assigned a task',
  mentioned: 'Mentioned',
  manual: 'Run by hand',
  event: 'Event',
  schedule: 'Schedule',
};

export const STEP_LABEL: Record<string, string> = {
  trigger: 'Started',
  tool: 'Looked up / previewed',
  policy: 'Policy',
  proposal: 'Proposed',
  applied: 'Applied',
  suggestion: 'Suggested',
  comment: 'Replied',
  skipped: 'Skipped',
  limit: 'Limit',
  error: 'Error',
};

export const AUTONOMY_LABEL: Record<string, string> = {
  suggest: 'Suggests only',
  confirm: 'Asks before changing',
  auto: 'Acts on low-risk changes',
};

export function money(value: string | number): string {
  const n = typeof value === 'string' ? Number(value) : value;
  return n === 0 ? '$0' : n < 0.01 ? '<$0.01' : `$${n.toFixed(2)}`;
}

export function when(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString() : '—';
}
