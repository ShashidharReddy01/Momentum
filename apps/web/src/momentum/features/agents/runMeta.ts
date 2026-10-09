import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  Clock,
  Hourglass,
  Loader2,
  PauseCircle,
  TimerOff,
  Wallet,
  type LucideIcon,
} from 'lucide-react';

export const RUN_STATUS: Record<string, { label: string; icon: LucideIcon; className: string }> = {
  queued: { label: 'Queued', icon: Clock, className: 'text-muted' },
  running: { label: 'Running', icon: Loader2, className: 'text-muted' },
  succeeded: { label: 'Done', icon: CheckCircle2, className: 'text-ok' },
  failed: { label: 'Failed', icon: AlertTriangle, className: 'text-crit' },
  cancelled: { label: 'Cancelled', icon: Ban, className: 'text-muted' },
  budget_exceeded: { label: 'Budget used up', icon: Wallet, className: 'text-warn' },
  // Phase 7.6 durable jobs
  waiting: { label: 'Waiting', icon: Hourglass, className: 'text-amber-ink' },
  paused: { label: 'Paused', icon: PauseCircle, className: 'text-muted' },
  expired: { label: 'Expired', icon: TimerOff, className: 'text-warn' },
};

/** Step kinds of a durable job (spec §4.6). */
export const JOB_STEP_KIND: Record<string, string> = {
  step: 'Step',
  llm: 'Model call',
  tool: 'Tool',
  ask: 'Question',
  spawn: 'Started sub-jobs',
  gather: 'Collected sub-jobs',
  consult: 'Consulted an agent',
  effect: 'Change',
  now: 'Clock',
  sleep: 'Wait',
  event: 'Wait for event',
};

export const DATA_CLASS: Record<string, { label: string; className: string }> = {
  public: { label: 'Public data', className: 'border-hairline text-muted' },
  internal: { label: 'Internal data', className: 'border-hairline text-ink-2' },
  financial: { label: 'Financial data', className: 'border-warn/50 text-warn' },
  personal: { label: 'Personal data', className: 'border-crit/40 text-crit' },
};

export function pct(n: number | null | undefined): string {
  return n == null ? '—' : `${Math.round(n * 100)}%`;
}

export function duration(seconds: number | null | undefined): string {
  if (seconds == null) return '—';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  if (seconds < 86_400) return `${(seconds / 3600).toFixed(1)} h`;
  return `${(seconds / 86_400).toFixed(1)} days`;
}

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
