import { useMutation, useQuery } from '@tanstack/react-query';
import { X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { MoMark } from '@/components/common/MoMark';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { IconButton } from '@/components/ui/IconButton';
import { Skeleton } from '@/components/ui/Skeleton';
import type { components } from '@/lib/api/schema';
import { useApi } from '@/providers/api';
import { errorText } from './errors';

/** Phase 7.5 (spec §9.1): "Catch me up". The visit beacon remembers when you last looked at Home,
 * a project or a portfolio; Catch me up says what other people changed since, "what needs you"
 * first. Nothing new means no AI at all: "Nothing changed since <date>". */

export type CatchUpScope = 'home' | 'project' | 'portfolio';
export type CatchUp = components['schemas']['CatchUpOut'];

const STAY_MS = 30_000;
const WRITE_EVERY_MS = 5 * 60_000;
const lastWrite = new Map<string, number>(); // per tab: at most one write per scope per 5 minutes

/** Mark the scope seen after 30 s on the page, and on leaving it. */
export function useVisitBeacon(scope: CatchUpScope, scopeId?: string | null) {
  const api = useApi();
  useEffect(() => {
    if (scope !== 'home' && !scopeId) return;
    const key = `${scope}:${scopeId ?? ''}`;
    const write = () => {
      const now = Date.now();
      if (now - (lastWrite.get(key) ?? 0) < WRITE_EVERY_MS) return;
      lastWrite.set(key, now);
      void api.PUT('/api/v1/visits', { body: { scope, scope_id: scopeId ?? null } }).catch(() => undefined); // best effort: a missed visit only widens the next catch-up
    };
    const timer = setTimeout(write, STAY_MS);
    return () => {
      clearTimeout(timer);
      write();
    };
  }, [api, scope, scopeId]);
}

function when(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
}

function CatchUpBody({
  scope,
  scopeId,
  onOpenTask,
}: {
  scope: CatchUpScope;
  scopeId?: string | null;
  onOpenTask?: (id: string) => void;
}) {
  const api = useApi();
  const navigate = useNavigate();
  const openTask = onOpenTask ?? ((id: string) => void navigate(`/task/${id}`));
  const run = useMutation({
    mutationFn: async () =>
      (await api.POST('/api/v1/ai/catch-up', { body: { scope, scope_id: scopeId ?? null } })).data!,
  });
  const go = run.mutate;
  useEffect(() => go(), [go]);
  if (run.isError)
    return (
      <p role="alert" className="text-sm text-crit">
        {errorText(run.error)}
      </p>
    );
  const c = run.data;
  if (!c) return <Skeleton className="h-28" />;
  if (c.nothing_changed) return <p className="text-sm text-muted">Nothing changed since {when(c.since)}.</p>;
  return (
    <div className="space-y-2">
      <p className="text-xs text-muted">
        Since {when(c.since)}: {c.total} {c.total === 1 ? 'change' : 'changes'} by others.
      </p>
      {c.lines.length ? (
        <ul className="space-y-1.5" aria-label="What changed">
          {c.lines.map((l, i) => (
            <li key={i} className="flex items-start gap-1.5 text-sm text-amber-ink">
              <MoMark size={12} className="mt-1 shrink-0" />
              <span>
                {l.text}
                {l.task_ids.length ? (
                  <button
                    type="button"
                    className="ml-1.5 text-xs text-muted underline-offset-2 hover:underline"
                    onClick={() => openTask(l.task_ids[0]!)}
                  >
                    Open
                  </button>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted">Mo couldn’t back a summary with the changes; see the activity.</p>
      )}
    </div>
  );
}

export function CatchUpDialog({
  scope,
  scopeId,
  title,
  onClose,
  onOpenTask,
}: {
  scope: CatchUpScope;
  scopeId?: string | null;
  title: string;
  onClose: () => void;
  onOpenTask?: (id: string) => void;
}) {
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={title}
      className="w-[min(560px,calc(100vw-32px))]"
    >
      <div className="space-y-4 p-5">
        <CatchUpBody scope={scope} scopeId={scopeId} onOpenTask={onOpenTask} />
        <div className="flex justify-end">
          <Button variant="text" onClick={onClose}>
            Done
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

/** A header button: "Catch me up" on a project or portfolio. */
export function CatchUpButton({
  scope,
  scopeId,
  name,
  onOpenTask,
}: {
  scope: 'project' | 'portfolio';
  scopeId: string;
  name: string;
  onOpenTask?: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button size="sm" variant="ai" onClick={() => setOpen(true)}>
        <MoMark size={13} /> Catch me up
      </Button>
      {open ? (
        <CatchUpDialog
          scope={scope}
          scopeId={scopeId}
          title={`Catch me up: ${name}`}
          onClose={() => setOpen(false)}
          onOpenTask={onOpenTask}
        />
      ) : null}
    </>
  );
}

const DISMISS_KEY = 'momentum.catchup.dismissed';

/** Home's "While you were away": shown when more than 3 things changed since the last visit to
 * Home; dismissible until something newer happens. */
export function WhileYouWereAway({ onOpenTask }: { onOpenTask?: (id: string) => void }) {
  const api = useApi();
  const pending = useQuery({
    queryKey: ['ai', 'catch-up', 'pending', 'home'],
    queryFn: async () =>
      (await api.GET('/api/v1/ai/catch-up/pending', { params: { query: { scope: 'home' } } })).data!,
    staleTime: 60_000,
    retry: false,
  });
  const dismissed = useRef<string | null>(null);
  const [, rerender] = useState(0);
  if (dismissed.current === null) {
    try {
      dismissed.current = localStorage.getItem(DISMISS_KEY) ?? '';
    } catch {
      dismissed.current = '';
    }
  }
  const [open, setOpen] = useState(false);
  const p = pending.data;
  if (!p?.show_card) return null;
  const stamp = `${p.since}:${p.total}`;
  if (dismissed.current === stamp && !open) return null;
  const summary = Object.entries(p.counts)
    .slice(0, 3)
    .map(([k, n]) => `${n} ${LABELS[k] ?? k}`)
    .join(', ');
  return (
    <section
      aria-label="While you were away"
      className="rounded-xl border border-dashed border-amber bg-amber-2/40 p-4"
    >
      <div className="flex items-start gap-2">
        <MoMark size={14} className="mt-0.5" />
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold">While you were away</h2>
          <p className="text-xs text-muted">
            {p.total} changes since {when(p.since)}
            {summary ? `: ${summary}` : ''}.
          </p>
        </div>
        <Button size="sm" variant="ai" onClick={() => setOpen(true)}>
          Catch me up
        </Button>
        <IconButton
          icon={X}
          label="Dismiss"
          size="icon-sm"
          onClick={() => {
            try {
              localStorage.setItem(DISMISS_KEY, stamp);
            } catch {
              /* a private window: dismissed for this page only */
            }
            dismissed.current = stamp;
            rerender((n) => n + 1);
          }}
        />
      </div>
      {open ? (
        <CatchUpDialog
          scope="home"
          title="While you were away"
          onClose={() => setOpen(false)}
          onOpenTask={onOpenTask}
        />
      ) : null}
    </section>
  );
}

const LABELS: Record<string, string> = {
  reassigned_to_me: 'reassigned to you',
  mentions: 'mentions',
  due_changes: 'due dates moved',
  blocked: 'blocked',
  completed: 'completed',
  new: 'new',
  unblocked: 'unblocked',
  comments: 'comments',
  status_updates: 'status updates',
  stage_changes: 'stage changes',
  files: 'files',
};
