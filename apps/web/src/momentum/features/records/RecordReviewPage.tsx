import { AlertTriangle, CheckCircle2, Info, XCircle } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Link, useParams } from 'react-router';
import { ErrorState } from '@/components/common/States';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { Skeleton } from '@/components/ui/Skeleton';
import { usePeople } from '@/features/people';
import { ApiError } from '@/lib/api/errors';
import { cn } from '@/lib/cn';
import { formatRelative } from '@/lib/dates';
import { toastError } from '@/lib/toast';
import { useUndoToast } from '@/lib/undo';
import { applyOps, formSpec, humanize, pushOp, type Display, type FieldSpec, type Prov } from './model';
import { PageViewer, type Highlight } from './PageViewer';
import {
  useEntity,
  usePatchRecord,
  useRecord,
  useRecordTypes,
  type RecordDetail,
  type RecordOp,
} from './queries';
import { fieldId, RecordForm } from './RecordForm';
import { RecordStatus } from './RecordStatus';

/** `/records/:recordId`: the review screen (Phase 7.6 S76-08, spec §12.4). */
export function RecordReviewPage() {
  const { recordId = '' } = useParams();
  const record = useRecord(recordId);
  const types = useRecordTypes(null);
  if (record.isPending || types.isPending)
    return (
      <div className="grid gap-4 p-6 lg:grid-cols-2">
        <Skeleton className="h-[70vh]" />
        <Skeleton className="h-[70vh]" />
      </div>
    );
  if (record.isError) return <ErrorState error={record.error} onRetry={() => void record.refetch()} />;
  const type = types.data?.find((t) => t.key === record.data.type);
  return (
    <Review
      key={record.data.id}
      record={record.data}
      schema={type?.schema ?? {}}
      display={type?.display ?? {}}
    />
  );
}

type Check = {
  id?: string;
  severity?: string;
  passed?: boolean;
  title?: string;
  detail?: string;
  fields?: string[];
};

function Review({
  record,
  schema,
  display,
}: {
  record: RecordDetail;
  schema: Record<string, unknown>;
  display: Display;
}) {
  const spec = useMemo(() => formSpec(schema, display), [schema, display]);
  const [ops, setOps] = useState<RecordOp[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const [base, setBase] = useState(record);
  const patch = usePatchRecord(record.id);
  const detail = useRecord(record.id);
  const undoToast = useUndoToast();
  const data = useMemo(() => applyOps(base.data, ops), [base.data, ops]);
  const provenance = (base.provenance ?? {}) as Record<string, Prov>;
  const label = (path: string) =>
    spec.fields.find((f) => f.path === path)?.label ??
    humanize(path).concat(/\[(\d+)\]/.exec(path) ? `, row ${Number(/\[(\d+)\]/.exec(path)![1]) + 1}` : '');
  const highlights: Highlight[] = Object.entries(provenance)
    .filter(([, p]) => p && typeof p === 'object' && p.page)
    .map(([path, p]) => ({ path, label: label(path), prov: p }));
  const currency =
    (display.currency_field
      ? String(data[display.currency_field] ?? '')
      : (base.currency ?? '')
    ).toUpperCase() || null;

  // a newer version from elsewhere (another reviewer, the agent) replaces the base when nothing's pending
  if (detail.data && detail.data.version !== base.version && !ops.length && !conflict) setBase(detail.data);

  const pick = (path: string) => {
    setActive(path);
    requestAnimationFrame(() => document.getElementById(fieldId(path))?.focus());
  };

  const save = (extra: RecordOp[] = [], message = 'Saved') => {
    const all = [...ops, ...extra];
    if (!all.length) return;
    patch.mutate(
      { ops: all, expected_version: base.version },
      {
        onSuccess: (r) => {
          setOps([]);
          setConflict(false);
          setBase({ ...base, ...r });
          undoToast(message, { activity_id: r.activity_id });
        },
        onError: (e) => {
          if (e instanceof ApiError && e.status === 409) setConflict(true);
          else toastError(e, "Couldn't save the record");
        },
      },
    );
  };

  const reapply = async () => {
    const fresh = await detail.refetch();
    if (fresh.data) setBase(fresh.data);
    setConflict(false);
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-hair-soft px-6 py-3">
        <h1 className="page-title mr-1">{base.title}</h1>
        <RecordStatus status={base.status} />
        <span className="text-xs text-muted">
          {base.type_label} · version {base.version}
          {base.classification === 'financial' || base.classification === 'personal'
            ? ` · ${base.classification} data`
            : ''}
        </span>
        <span className="ml-auto flex gap-3 text-xs">
          {base.task_id ? (
            <Link to={`/task/${base.task_id}`} className="text-accent hover:underline">
              Open the task
            </Link>
          ) : null}
          {base.run_id ? (
            <Link to={`/agents/runs/${base.run_id}`} className="text-accent hover:underline">
              The run that made it
            </Link>
          ) : null}
        </span>
      </header>
      {conflict ? (
        <div
          role="alert"
          className="flex flex-wrap items-center gap-2 border-b border-warn/40 bg-warn-tint px-6 py-2 text-sm"
        >
          Someone else changed this record while you were editing.
          <Button size="sm" onClick={() => void reapply()}>
            Reload and reapply my changes
          </Button>
        </div>
      ) : null}
      {(record.duplicates ?? []).length ? (
        <p className="border-b border-hair-soft bg-warn-tint px-6 py-1.5 text-xs">
          Looks like a duplicate of{' '}
          {(record.duplicates ?? []).map((d, i) => (
            <span key={d}>
              {i ? ', ' : ''}
              <Link to={`/records/${d}`} className="text-accent underline">
                another record
              </Link>
            </span>
          ))}
          .
        </p>
      ) : null}
      <div className="grid min-h-0 flex-1 gap-4 overflow-hidden p-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="min-h-[40vh] overflow-auto">
          <PageViewer
            recordId={record.id}
            hasSource={!!record.source_attachment_id}
            highlights={highlights}
            active={active}
            onPick={pick}
          />
        </div>
        <div className="flex min-h-0 flex-col gap-5 overflow-auto pr-1">
          <RecordForm
            spec={spec}
            data={data}
            provenance={provenance}
            canEdit={record.can_edit}
            active={active}
            currency={currency}
            onActive={setActive}
            onSet={(path, value) => setOps((o) => pushOp(o, { op: 'set', path, value }))}
            onAdd={(array, columns: FieldSpec[]) =>
              setOps((o) => [
                ...o,
                {
                  op: 'add_item',
                  array,
                  item: Object.fromEntries(columns.map((c) => [c.path, c.kind === 'bool' ? false : null])),
                },
              ])
            }
            onRemove={(array, index) => setOps((o) => [...o, { op: 'remove_item', array, index }])}
            onMove={(array, from, to) => setOps((o) => [...o, { op: 'move_item', array, from, to }])}
          />
          {record.can_edit ? (
            <div className="sticky bottom-0 flex flex-wrap items-center gap-2 border-t border-hair-soft bg-surface py-2">
              <Button
                variant="primary"
                size="sm"
                disabled={!ops.length}
                loading={patch.isPending}
                onClick={() => save()}
              >
                Save{ops.length ? ` (${ops.length} change${ops.length === 1 ? '' : 's'})` : ''}
              </Button>
              {ops.length ? (
                <Button size="sm" variant="text" onClick={() => setOps([])}>
                  Discard changes
                </Button>
              ) : null}
              <span className="text-xs text-muted">Checks run again on the server when you save.</span>
            </div>
          ) : (
            <p className="text-xs text-muted">You can look at this record but not change it.</p>
          )}
          <Checks checks={base.checks as Check[]} onPick={pick} label={label} />
          <DecisionPanel
            record={base}
            canDecide={record.can_decide}
            blocked={record.decide_blocked ?? null}
            dirty={ops.length > 0}
            onDecide={(status, reason) =>
              save([{ op: 'set_status', status, reason }], status === 'approved' ? 'Approved' : 'Rejected')
            }
            pending={patch.isPending}
          />
          <EntityPanel ids={base.entity_ids} />
          <Versions record={detail.data ?? record} />
        </div>
      </div>
    </div>
  );
}

const SEVERITY: Record<string, { icon: typeof Info; className: string; label: string }> = {
  block: { icon: XCircle, className: 'text-crit', label: 'Blocks approval' },
  warn: { icon: AlertTriangle, className: 'text-warn', label: 'Warning' },
  info: { icon: Info, className: 'text-muted', label: 'Note' },
};

function Checks({
  checks,
  onPick,
  label,
}: {
  checks: Check[];
  onPick: (path: string) => void;
  label: (p: string) => string;
}) {
  if (!checks.length) return null;
  const failing = checks.filter((c) => !c.passed);
  return (
    <section aria-label="Checks" className="flex flex-col gap-1.5">
      <h3 className="section-label">
        Checks{' '}
        <span className="font-normal text-muted">
          ({failing.length ? `${failing.length} need attention` : 'all passed'})
        </span>
      </h3>
      <ul className="flex flex-col gap-1">
        {[...failing, ...checks.filter((c) => c.passed)].map((c, i) => {
          const sev = c.passed
            ? { icon: CheckCircle2, className: 'text-ok', label: 'Passed' }
            : (SEVERITY[c.severity ?? 'info'] ?? SEVERITY.info!);
          return (
            <li key={c.id ?? i} className="flex gap-2 text-sm">
              <Icon
                icon={sev.icon}
                size={15}
                className={cn('mt-0.5 shrink-0', sev.className)}
                aria-label={sev.label}
              />
              <span className="min-w-0">
                <span className={cn(!c.passed && 'font-medium')}>{c.title}</span>
                {c.detail && !c.passed ? <span className="block text-xs text-muted">{c.detail}</span> : null}
                {!c.passed && c.fields?.length ? (
                  <span className="flex flex-wrap gap-1.5 text-xs">
                    {c.fields.map((f) => (
                      <button
                        key={f}
                        type="button"
                        className="text-accent hover:underline"
                        onClick={() => onPick(f)}
                      >
                        {label(f)}
                      </button>
                    ))}
                  </span>
                ) : null}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function DecisionPanel({
  record,
  canDecide,
  blocked,
  dirty,
  pending,
  onDecide,
}: {
  record: RecordDetail;
  canDecide: boolean;
  blocked: string | null;
  dirty: boolean;
  pending: boolean;
  onDecide: (status: 'approved' | 'rejected', reason: string | null) => void;
}) {
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState('');
  const d = record.decision as { decision?: string; reason?: string } | null;
  const blocking = (record.checks as Check[]).some((c) => !c.passed && c.severity === 'block');
  return (
    <section aria-label="Decision" className="flex flex-col gap-1.5 rounded-lg border border-hairline p-3">
      <h3 className="section-label">Decision</h3>
      {d?.decision ? (
        <p className="text-sm">
          <span className="text-amber-ink">✦ The agent suggests: </span>
          <strong>{humanize(d.decision)}</strong>
          {d.reason ? <span className="text-ink-2"> · {d.reason}</span> : null}
        </p>
      ) : (
        <p className="text-sm text-muted">No decision suggested.</p>
      )}
      {canDecide ? (
        rejecting ? (
          <form
            className="flex flex-wrap gap-1.5"
            onSubmit={(e) => {
              e.preventDefault();
              if (reason.trim()) onDecide('rejected', reason.trim());
            }}
          >
            <input
              aria-label="Why reject it?"
              placeholder="Why reject it?"
              className="h-8 min-w-48 flex-1 rounded-md border border-hairline bg-surface px-2 text-sm"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
            <Button type="submit" size="sm" variant="danger" disabled={!reason.trim() || pending}>
              Reject
            </Button>
            <Button type="button" size="sm" variant="text" onClick={() => setRejecting(false)}>
              Cancel
            </Button>
          </form>
        ) : (
          <div className="flex flex-wrap items-center gap-1.5">
            <Button
              size="sm"
              variant="primary"
              disabled={pending || blocking}
              title={blocking ? 'A blocking check fails' : undefined}
              onClick={() => onDecide('approved', null)}
            >
              {dirty ? 'Save and approve' : 'Approve'}
            </Button>
            <Button size="sm" onClick={() => setRejecting(true)} disabled={pending}>
              Reject…
            </Button>
            {blocking ? <span className="text-xs text-crit">Fix the blocking checks first.</span> : null}
          </div>
        )
      ) : blocked ? (
        <p className="text-xs text-muted">{blocked}.</p>
      ) : null}
    </section>
  );
}

function EntityPanel({ ids }: { ids: string[] }) {
  const entity = useEntity(ids[0] ?? null);
  if (!ids.length) return null;
  const e = entity.data;
  return (
    <section
      aria-label="Linked entity"
      className="flex flex-col gap-1 rounded-lg border border-hairline p-3 text-sm"
    >
      <h3 className="section-label">{e ? humanize(e.type) : 'Linked to'}</h3>
      {e ? (
        <>
          <Link to={`/entities/${e.id}`} className="font-medium text-accent hover:underline">
            {e.name}
          </Link>
          {e.aliases.length ? (
            <span className="text-xs text-muted">Also known as {e.aliases.join(', ')}</span>
          ) : null}
          {typeof (e.attributes as { bank?: { display?: string } }).bank?.display === 'string' ? (
            <span className="text-xs text-muted">
              Bank account {(e.attributes as { bank: { display: string } }).bank.display}
            </span>
          ) : null}
        </>
      ) : (
        <Skeleton className="h-5 w-40" />
      )}
    </section>
  );
}

function Versions({ record }: { record: RecordDetail }) {
  const people = usePeople('', 'all').data ?? [];
  const name = (id: string | null | undefined) =>
    people.find((p) => p.id === id)?.name ?? (id ? 'Someone' : 'Momentum');
  return (
    <section aria-label="History" className="flex flex-col gap-1.5">
      <h3 className="section-label">History</h3>
      <ol className="flex flex-col gap-1.5 text-sm">
        {record.versions.map((v) => {
          const ops = (
            (
              v.change as {
                ops?: { op: string; path?: string; array?: string; status?: string; value?: unknown }[];
              }
            ).ops ?? []
          ).slice(0, 6);
          return (
            <li key={v.version} className="border-l border-hairline pl-3">
              <span className="font-medium">v{v.version}</span>{' '}
              <span className="text-xs text-muted">
                {v.via === 'agent' ? '✦ the agent' : name(v.changed_by)} · {v.via} ·{' '}
                {formatRelative(v.created_at)}
              </span>
              {ops.length ? (
                <ul className="text-xs text-ink-2">
                  {ops.map((o, i) => (
                    <li key={i}>
                      {o.op === 'set'
                        ? `${humanize(o.path ?? '')} → ${String(o.value ?? '(empty)')}`
                        : o.op === 'set_status'
                          ? `Status → ${humanize(o.status ?? '')}`
                          : o.op === 'add_item'
                            ? `Added a ${humanize(o.array ?? 'row')} row`
                            : o.op === 'remove_item'
                              ? `Removed a ${humanize(o.array ?? 'row')} row`
                              : o.op === 'move_item'
                                ? `Reordered ${humanize(o.array ?? 'rows')}`
                                : humanize(o.op)}
                    </li>
                  ))}
                </ul>
              ) : v.version === 1 ? (
                <p className="text-xs text-muted">Created</p>
              ) : null}
              {v.reason ? <p className="text-xs text-muted">“{v.reason}”</p> : null}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
