import { Download, FileText } from 'lucide-react';
import { useMutation } from '@tanstack/react-query';
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { toast } from 'sonner';
import { MoMark } from '@/components/common/MoMark';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { Icon } from '@/components/ui/Icon';
import { Skeleton } from '@/components/ui/Skeleton';
import { Segmented } from '@/components/ui/Tabs';
import { usePostStatus } from '@/features/status';
import { useUndoToast } from '@/lib/undo';
import { useApi } from '@/providers/api';
import {
  FORMAT_LABELS,
  KINDS,
  NARRATIVE_KINDS,
  useCreateReport,
  useReportJob,
  useReportPreview,
  type ReportFormat,
  type ReportKind,
  type ReportRun,
  type ReportSpec,
} from './queries';

export interface ReportScope {
  projectId?: string;
  portfolioId?: string;
  dashboardId?: string;
}

const PERIODS: [string, string][] = [
  ['7', 'Last 7 days'],
  ['14', 'Last 14 days'],
  ['30', 'Last 30 days'],
  ['90', 'Last 90 days'],
];

function kindsFor(scope: ReportScope): ReportKind[] {
  if (scope.projectId) return ['project_status', 'customer_status', 'closeout', 'task_export'];
  if (scope.portfolioId) return ['portfolio_status', 'task_export'];
  return ['dashboard'];
}

function isoDaysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n + 1);
  return d.toLocaleDateString('sv-SE'); // YYYY-MM-DD in local time
}

/**
 * Phase 7.5 (spec §6.3): "Create report" on a project, portfolio or dashboard. Pick what kind,
 * the period, the format and who it's for; the outline previews what the file will hold (built as
 * you, no file yet). Creating runs it as a job; a toast says when it's ready, with Undo.
 */
export function ReportDialog({
  open,
  onOpenChange,
  scope,
  name,
  initialKind,
  returnFocus,
}: {
  returnFocus?: { current: HTMLElement | null };
  open: boolean;
  onOpenChange: (open: boolean) => void;
  scope: ReportScope;
  name: string;
  /** S75-12: open on this kind (the close-out report offered on complete / archive) */
  initialKind?: ReportKind;
}) {
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={`Create a report: ${name}`}
      returnFocus={returnFocus}
      className="top-[8vh] w-[min(820px,calc(100vw-32px))]"
    >
      {open ? (
        <ReportBody scope={scope} initialKind={initialKind} onDone={() => onOpenChange(false)} />
      ) : null}
    </Dialog>
  );
}

function ReportBody({
  scope,
  initialKind,
  onDone,
}: {
  scope: ReportScope;
  initialKind?: ReportKind;
  onDone: () => void;
}) {
  const kinds = kindsFor(scope);
  const first = initialKind && kinds.includes(initialKind) ? initialKind : kinds[0]!;
  const [kind, setKind] = useState<ReportKind>(first);
  const [format, setFormat] = useState<ReportFormat>(KINDS[first].formats[0]!);
  const [period, setPeriod] = useState('7');
  const [narrative, setNarrative] = useState(true);
  const [run, setRun] = useState<ReportRun | null>(null);
  const create = useCreateReport();
  const undoToast = useUndoToast();
  const job = useReportJob(run?.id ?? null, run);

  const withPeriod = kind !== 'closeout' && kind !== 'task_export' && kind !== 'dashboard';
  const canNarrate = NARRATIVE_KINDS.includes(kind);
  const spec = useMemo<ReportSpec>(() => {
    const s: Record<string, unknown> = {
      kind,
      format,
      scope: {
        project_id: scope.projectId ?? null,
        portfolio_id: scope.portfolioId ?? null,
        dashboard_id: scope.dashboardId ?? null,
      },
      audience: kind === 'customer_status' ? 'customer' : 'internal',
    };
    if (withPeriod) s.period = { from: isoDaysAgo(Number(period)), to: isoDaysAgo(1) };
    if (canNarrate) s.narrative = narrative;
    return s as unknown as ReportSpec;
  }, [kind, format, period, narrative, scope, withPeriod, canNarrate]);
  const preview = useReportPreview(run ? null : spec);

  const pickKind = (k: ReportKind) => {
    setKind(k);
    if (!KINDS[k].formats.includes(format)) setFormat(KINDS[k].formats[0]!);
  };

  // the job's end: a toast with what to do next (Undo deletes the file)
  const status = job.data?.status;
  useEffect(() => {
    const r = job.data;
    if (!r || (r.status !== 'done' && r.status !== 'failed')) return;
    toast.dismiss(`report-${r.id}`);
    if (r.status === 'failed') toast.error(r.error ?? "Couldn't make the report");
    else undoToast(`Report ready: ${r.filename ?? 'the file'}`, { activity_id: r.activity_id ?? null });
  }, [status, job.data, undoToast]);

  if (run && job.data) {
    const r = job.data;
    return (
      <div className="space-y-4 px-5 py-5" role="status" aria-live="polite">
        {r.status === 'done' && r.attachment_id ? (
          <>
            <p className="flex items-center gap-2 text-sm">
              <Icon icon={FileText} size={16} className="text-muted" /> Report ready:{' '}
              <span className="font-medium">{r.filename}</span>
            </p>
            <p className="text-sm text-muted">
              It’s in the {r.project_id ? 'project’s Files tab' : 'portfolio’s files'}.{' '}
              {canNarrate && narrative ? 'Paragraphs Mo drafted are marked: review them before sending.' : ''}
            </p>
            {kind === 'closeout' && scope.projectId ? <CloseoutStatus projectId={scope.projectId} /> : null}
            <div className="flex justify-end gap-2">
              <a
                href={`/api/v1/attachments/${r.attachment_id}/download`}
                className="inline-flex h-8 items-center gap-1.5 rounded-md border border-hairline px-3 text-sm hover:bg-surface-2"
              >
                <Icon icon={Download} size={14} /> Download
              </a>
              <Button variant="primary" onClick={onDone}>
                Done
              </Button>
            </div>
          </>
        ) : r.status === 'failed' ? (
          <>
            <p role="alert" className="text-sm text-crit">
              {r.error ?? "Couldn't make the report."}
            </p>
            <div className="flex justify-end">
              <Button onClick={() => setRun(null)}>Back</Button>
            </div>
          </>
        ) : (
          <p className="text-sm text-muted">
            Making the report… you can close this; a note says when it’s ready.
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="grid max-h-[78vh] grid-cols-1 overflow-auto md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <form
        className="space-y-4 border-hair-soft px-5 py-4 md:border-r"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate(spec, {
            onSuccess: (r) => {
              setRun(r);
              if (r.status === 'queued' || r.status === 'running')
                toast.loading('Making the report…', { id: `report-${r.id}` });
            },
          });
        }}
      >
        <fieldset>
          <legend className="mb-2 text-xs font-medium text-muted">Report</legend>
          <div className="grid gap-1.5 sm:grid-cols-2">
            {kinds.map((k) => (
              <button
                key={k}
                type="button"
                aria-pressed={kind === k}
                onClick={() => pickKind(k)}
                className={
                  'flex flex-col items-start rounded-lg border p-2.5 text-left ' +
                  (kind === k ? 'border-ink bg-surface-2' : 'border-hairline hover:bg-surface-2')
                }
              >
                <span className="text-sm font-medium">{KINDS[k].label}</span>
                <span className="text-xs text-muted">{KINDS[k].hint}</span>
              </button>
            ))}
          </div>
        </fieldset>
        <Segmented
          label="Format"
          value={format}
          onChange={setFormat}
          options={KINDS[kind].formats.map((f) => ({ value: f, label: FORMAT_LABELS[f] }))}
        />
        {withPeriod ? (
          <Field label="Period" id="report-period">
            <select
              id="report-period"
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
              className="h-8 w-full rounded-md border border-hairline bg-surface px-2 text-sm focus:outline-none focus:ring-2 focus:ring-focus/25"
            >
              {PERIODS.map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          </Field>
        ) : null}
        {canNarrate ? (
          <label htmlFor="report-narrative" className="flex items-start gap-2 text-sm">
            <input
              id="report-narrative"
              type="checkbox"
              aria-label="Add Mo’s summary"
              checked={narrative}
              onChange={(e) => setNarrative(e.target.checked)}
              className="mt-0.5"
            />
            <span>
              <span className="flex items-center gap-1 font-medium">
                <MoMark size={12} /> Add Mo’s summary
              </span>
              <span className="text-xs text-muted">
                Written only from the report’s own facts, each paragraph citing them, and marked “AI-drafted,
                review before sending”.
              </span>
            </span>
          </label>
        ) : null}
        {kind === 'customer_status' ? (
          <p className="rounded-md bg-surface-2 px-3 py-2 text-xs text-ink-2">
            For the customer: tasks tagged “internal” and team members’ names stay out.
          </p>
        ) : null}
        <div className="flex justify-end gap-2 pt-1">
          <Button type="button" variant="text" onClick={onDone}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" loading={create.isPending} disabled={preview.isError}>
            Create report
          </Button>
        </div>
      </form>
      <section aria-label="Report outline" className="bg-surface-2/40 px-5 py-4">
        <p className="mb-2 text-xs font-medium text-muted">What it will hold (with your numbers)</p>
        {preview.isPending ? (
          <Skeleton className="h-40" />
        ) : preview.isError ? (
          <p role="alert" className="text-sm text-muted">
            {(preview.error as { detail?: string }).detail ?? 'This report can’t be made here.'}
          </p>
        ) : (
          <div className="space-y-2">
            <p className="text-sm font-semibold">{preview.data.title}</p>
            <p className="text-xs text-muted">{preview.data.subtitle}</p>
            <ol className="space-y-1 text-sm">
              {preview.data.items.map((i, n) => (
                <li key={`${i.type}-${n}`} className="flex items-baseline gap-2">
                  <span className="w-16 shrink-0 text-xs text-muted">{OUTLINE[i.type]}</span>
                  <span className={i.type === 'narrative' ? 'text-amber-ink' : ''}>
                    {i.title}
                    {i.rows != null ? <span className="text-muted"> · {i.rows}</span> : null}
                  </span>
                </li>
              ))}
            </ol>
            <p className="text-xs text-muted">
              {preview.data.pages
                ? `About ${preview.data.pages} ${preview.data.pages === 1 ? 'page' : 'pages'}`
                : preview.data.sheets
                  ? `${preview.data.sheets} ${preview.data.sheets === 1 ? 'sheet' : 'sheets'}`
                  : ''}
            </p>
          </div>
        )}
      </section>
    </div>
  );
}

const OUTLINE: Record<string, string> = {
  heading: 'Section',
  kpis: 'Numbers',
  table: 'Table',
  tasks: 'Tasks',
  chart: 'Chart',
  narrative: 'Mo',
};

function Field({ label, id, children }: { label: string; id: string; children: ReactNode }) {
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-xs font-medium text-muted">
        {label}
      </label>
      {children}
    </div>
  );
}

/** S75-12 (spec §9.4): post the project's final status update from the close-out summary,
 * previewed first (Mo's paragraphs are cited and marked). */
function CloseoutStatus({ projectId }: { projectId: string }) {
  const api = useApi();
  const undoToast = useUndoToast();
  const draft = useMutation({
    mutationFn: async () =>
      (
        await api.POST('/api/v1/ai/projects/{project_id}/closeout-status', {
          params: { path: { project_id: projectId } },
        })
      ).data!,
  });
  const post = usePostStatus(projectId);
  const [posted, setPosted] = useState(false);
  if (posted) return <p className="text-sm text-muted">The close-out status update is posted.</p>;
  if (!draft.data)
    return (
      <div>
        <Button size="sm" loading={draft.isPending} onClick={() => draft.mutate()}>
          Post as status update…
        </Button>
        {draft.isError ? (
          <p role="alert" className="mt-1 text-sm text-crit">
            Couldn’t draft the update.
          </p>
        ) : null}
      </div>
    );
  const su = draft.data.status_update;
  return (
    <section
      aria-label="Close-out status update"
      className="space-y-2 rounded-md border border-hairline p-3 text-sm"
    >
      <p className="font-medium">{su.title}</p>
      <p className={draft.data.ai ? 'whitespace-pre-line text-amber-ink' : 'whitespace-pre-line text-ink-2'}>
        {su.summary}
      </p>
      {(su.sections?.slipped ?? []).length ? (
        <ul className="list-disc pl-5 text-ink-2">
          {su.sections!.slipped!.map((i, n) => (
            <li key={n}>{i.text}</li>
          ))}
        </ul>
      ) : null}
      <div className="flex justify-end">
        <Button
          size="sm"
          variant="primary"
          loading={post.isPending}
          onClick={() =>
            post.mutate(su, {
              onSuccess: (res) => {
                undoToast('Close-out status update posted', res.meta);
                setPosted(true);
              },
            })
          }
        >
          Post status update
        </Button>
      </div>
    </section>
  );
}
