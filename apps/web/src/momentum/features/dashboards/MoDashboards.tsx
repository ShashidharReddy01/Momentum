import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router';
import { MoMark } from '@/components/common/MoMark';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { Skeleton } from '@/components/ui/Skeleton';
import { errorText } from '@/features/ai';
import type { components } from '@/lib/api/schema';
import { toastError } from '@/lib/toast';
import { useUndoToast } from '@/lib/undo';
import { useApi } from '@/providers/api';
import type { DashboardFilters } from './queries';

/** Phase 7.5 S75-10 (spec §8): Mo on dashboards. "New with Mo" drafts a dashboard from a
 * sentence and previews every widget with real numbers (counted as you; nothing saved until
 * Create); "Explain" on a widget explains its changes and outliers from its own numbers. */

export type DashboardDraft = components['schemas']['DashboardDraftOut'];
export type Explanation = components['schemas']['ExplainOut'];

type DraftWidget = components['schemas']['DraftWidgetOut'];

function headline(w: DraftWidget): string {
  const r = w.result;
  if (!r) return 'no numbers yet';
  if (r.value !== null && r.value !== undefined) return String(Math.round(r.value * 100) / 100);
  if (r.groups?.length) return `${r.groups.length} groups`;
  if (r.stages?.length) return `${r.stages.length} stages`;
  if (r.rows?.length) return `${r.rows.length} rows`;
  if (r.timeline?.length) return `${r.timeline.length} dates`;
  if (r.tasks?.length) return `${r.tasks.length} tasks`;
  return String(r.total);
}

export function NewWithMoDialog({
  open,
  onOpenChange,
  portfolioId = null,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  portfolioId?: string | null;
}) {
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="New dashboard with Mo"
      description="Say what you want to see. Mo picks widgets and shows them with your numbers; nothing is saved until you create it."
      className="w-[min(720px,calc(100vw-32px))]"
    >
      {open ? <NewWithMoBody portfolioId={portfolioId} onDone={() => onOpenChange(false)} /> : null}
    </Dialog>
  );
}

function NewWithMoBody({ portfolioId, onDone }: { portfolioId: string | null; onDone: () => void }) {
  const api = useApi();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const undoToast = useUndoToast();
  const [text, setText] = useState('');
  const [prompt, setPrompt] = useState('');
  const draft = useMutation({
    mutationFn: async (t: string) =>
      (await api.POST('/api/v1/ai/dashboards/draft', { body: { text: t, portfolio_id: portfolioId } })).data!,
  });
  const create = useMutation({
    mutationFn: async (d: DashboardDraft) =>
      (
        await api.POST('/api/v1/dashboards/from-draft', {
          body: {
            name: d.name,
            description: d.description || null,
            filters: d.filters ?? {},
            widgets: (d.widgets ?? []).map((w) => ({
              kind: w.kind,
              title: w.title,
              query_spec: w.query_spec,
              viz: w.viz,
            })),
            prompt,
          },
        })
      ).data!,
    onSuccess: (res) => {
      void qc.invalidateQueries({ queryKey: ['dashboards'] });
      undoToast(`Created “${res.data.name}”`, res.meta);
      onDone();
      void navigate(`/dashboards/${res.data.id}`);
    },
    onError: (e) => toastError(e, "Couldn't create the dashboard"),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const t = text.trim();
    if (!t) return;
    setPrompt(t);
    draft.mutate(t);
  };
  const d = draft.data;
  return (
    <div className="max-h-[75vh] space-y-4 overflow-auto p-5">
      <form onSubmit={submit} className="space-y-2">
        <label htmlFor="mo-dashboard-text" className="text-xs font-medium text-muted">
          What should it show?
        </label>
        <textarea
          id="mo-dashboard-text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          maxLength={400}
          rows={3}
          placeholder="A dashboard for my implementations: go-lives next 90 days, slipping projects, waiting on customer, RAID by severity"
          className="w-full rounded-md border border-hairline bg-surface px-2.5 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-focus/25"
        />
        <div className="flex justify-end">
          <Button type="submit" variant="ai" loading={draft.isPending} disabled={!text.trim()}>
            <MoMark size={12} /> Draft it
          </Button>
        </div>
      </form>
      {draft.isError ? (
        <p role="alert" className="text-sm text-crit">
          {errorText(draft.error)}
        </p>
      ) : null}
      {d?.question ? (
        <p role="status" className="text-sm text-amber-ink">
          {d.question}
          {d.options?.length ? (
            <span className="block text-xs text-muted">Options: {d.options.join(', ')}</span>
          ) : null}
        </p>
      ) : null}
      {d && !d.question ? (
        <section aria-label="Draft dashboard" className="space-y-3">
          <p className="flex items-center gap-2 text-sm font-semibold">
            <MoMark size={13} /> {d.name}
            {d.portfolio ? <span className="font-normal text-muted">· reads {d.portfolio}</span> : null}
          </p>
          <ul className="grid gap-2 sm:grid-cols-2">
            {(d.widgets ?? []).map((w, i) => (
              <li key={i} className="rounded-md border border-hairline p-2.5">
                <p className="truncate text-sm font-medium">{w.title}</p>
                <p className="text-xs text-muted">
                  {w.kind.replace('_', ' ')} · <span className="tabular-nums text-ink">{headline(w)}</span>
                </p>
              </li>
            ))}
          </ul>
          {[...(d.notes ?? []), ...(d.left_out ?? []).map((x) => `Not shown: ${x} (no widget fits).`)].map(
            (n, i) => (
              <p key={i} className="text-xs text-muted">
                {n}
              </p>
            ),
          )}
          <div className="flex justify-end gap-2">
            <Button variant="text" onClick={onDone}>
              Cancel
            </Button>
            <Button variant="primary" loading={create.isPending} onClick={() => create.mutate(d)}>
              Create dashboard
            </Button>
          </div>
        </section>
      ) : null}
    </div>
  );
}

export function ExplainDialog({
  widgetId,
  title,
  filters,
  onOpenTask,
  onClose,
}: {
  widgetId: string;
  title: string;
  filters: DashboardFilters | null;
  onOpenTask: (taskId: string) => void;
  onClose: () => void;
}) {
  const api = useApi();
  const explain = useMutation({
    mutationFn: async () =>
      (
        await api.POST('/api/v1/ai/dashboards/widgets/{widget_id}/explain', {
          params: { path: { widget_id: widgetId } },
          body: { filters },
        })
      ).data!,
  });
  const run = explain.mutate;
  useEffect(() => run(), [run]);
  const e = explain.data;
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={`Explain: ${title}`}>
      <div className="space-y-3 p-5">
        {explain.isError ? (
          <p role="alert" className="text-sm text-crit">
            {errorText(explain.error)}
          </p>
        ) : !e ? (
          <Skeleton className="h-28" />
        ) : (
          <>
            {e.paragraphs.length ? (
              e.paragraphs.map((p, i) => (
                <p key={i} className={e.ai ? 'flex items-start gap-1.5 text-sm text-amber-ink' : 'text-sm'}>
                  {e.ai ? <MoMark size={12} className="mt-1 shrink-0" /> : null}
                  {p.text}
                </p>
              ))
            ) : (
              <p className="text-sm text-muted">Mo had nothing it could back with this chart’s numbers.</p>
            )}
            {e.links.length ? (
              <div>
                <p className="text-xs font-medium text-muted">
                  Open the {e.links[0]!.kind === 'task' ? 'tasks' : 'projects'}
                  {e.sample_label ? ` (${e.sample_label})` : ''}
                </p>
                <ul className="mt-1 space-y-0.5 text-sm">
                  {e.links.map((l) => (
                    <li key={l.id}>
                      {l.kind === 'task' ? (
                        <button
                          type="button"
                          className="text-left hover:underline"
                          onClick={() => onOpenTask(l.id)}
                        >
                          {l.label}
                        </button>
                      ) : (
                        <Link to={`/projects/${l.id}/overview`} className="hover:underline">
                          {l.label}
                        </Link>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </>
        )}
        <div className="flex justify-end">
          <Button variant="text" onClick={onClose}>
            Done
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
