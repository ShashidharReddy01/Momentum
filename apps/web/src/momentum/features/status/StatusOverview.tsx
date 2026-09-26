import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { AIBadge, AICallout } from '@/components/common/AI';
import { MoMark } from '@/components/common/MoMark';
import { EmptyState, ErrorState } from '@/components/common/States';
import { Button } from '@/components/ui/Button';
import { Skeleton } from '@/components/ui/Skeleton';
import { errorText, MoText, type Citation } from '@/features/ai';
import { usePeople } from '@/features/people';
import { cn } from '@/lib/cn';
import { useMomentumConfig } from '@/lib/config';
import { formatRelative } from '@/lib/dates';
import { useUndoToast } from '@/lib/undo';
import {
  usePostStatus,
  useStatusDraft,
  useStatusUpdates,
  type Status,
  type StatusUpdate,
  type StatusUpdateIn,
} from './queries';

export const STATUS_LABEL: Record<Status, string> = {
  on_track: 'On track',
  at_risk: 'At risk',
  off_track: 'Off track',
  on_hold: 'On hold',
  complete: 'Complete',
};
const STATUS_TONE: Record<Status, string> = {
  on_track: 'bg-ok-tint text-ok',
  at_risk: 'bg-warn-tint text-warn',
  off_track: 'bg-crit-tint text-crit',
  on_hold: 'bg-surface-2 text-muted',
  complete: 'bg-ok-tint text-ok',
};
const SECTIONS = [
  ['completed', 'Completed'],
  ['slipped', 'Slipped'],
  ['blockers', 'Blockers'],
  ['next', 'Next'],
] as const;
type SectionKey = (typeof SECTIONS)[number][0];

export function StatusChip({ status }: { status: Status }) {
  return (
    <span className={cn('rounded-full px-2 py-0.5 text-xs font-medium', STATUS_TONE[status])}>
      {STATUS_LABEL[status]}
    </span>
  );
}

/**
 * The project's Overview (S3.4.3 part; the rest of Overview is Phase 6): status update history,
 * "Post update", and "Draft with Mo" — Mo drafts from the project's recent activity (every claim
 * cites a task), the user edits it here and posts it (undoable), or discards it.
 */
export function StatusOverview({
  projectId,
  canEdit,
  startDraft = false,
}: {
  projectId: string;
  canEdit: boolean;
  startDraft?: boolean;
}) {
  const aiEnabled = useMomentumConfig().ai_enabled;
  const list = useStatusUpdates(projectId);
  const draft = useStatusDraft(projectId);
  const [editing, setEditing] = useState<{ value: StatusUpdateIn; fromAi: boolean } | null>(null);
  const askMo = useCallback(
    () =>
      draft.mutate(undefined, {
        onSuccess: (d) => setEditing({ value: d.draft, fromAi: true }),
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [draft.mutate],
  );
  // "Draft status" in the project header lands here with the draft already requested
  const started = useRef(false);
  useEffect(() => {
    if (startDraft && !started.current && canEdit && aiEnabled) {
      started.current = true;
      askMo();
    }
  }, [startDraft, canEdit, aiEnabled, askMo]);

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="flex-1 text-[15px] font-semibold">Status updates</h2>
        {canEdit && !editing ? (
          <>
            {aiEnabled ? (
              <Button size="sm" variant="ghost" loading={draft.isPending} onClick={askMo}>
                <MoMark size={13} /> Draft with Mo
              </Button>
            ) : null}
            <Button
              size="sm"
              onClick={() =>
                setEditing({
                  value: { status: 'on_track', title: '', summary: '', sections: {} } as StatusUpdateIn,
                  fromAi: false,
                })
              }
            >
              Post update
            </Button>
          </>
        ) : null}
      </div>
      {draft.isError && !editing ? (
        <p role="alert" className="text-sm text-crit">
          {errorText(draft.error)}
        </p>
      ) : null}
      {editing ? (
        <StatusEditor
          projectId={projectId}
          initial={editing.value}
          fromAi={editing.fromAi}
          notes={editing.fromAi ? (draft.data?.notes ?? []) : []}
          onDone={() => {
            setEditing(null);
            draft.reset();
          }}
        />
      ) : null}
      {list.isPending ? <Skeleton className="h-24" /> : null}
      {list.isError ? <ErrorState error={list.error} onRetry={() => void list.refetch()} /> : null}
      {list.data?.length === 0 && !editing ? (
        <EmptyState title="No status updates yet">
          {canEdit ? 'Post one to tell everyone how the project is going.' : 'Nothing has been posted.'}
        </EmptyState>
      ) : null}
      <ol aria-label="Status history" className="space-y-4">
        {list.data?.map((u) => (
          <li key={u.id}>
            <UpdateCard update={u} />
          </li>
        ))}
      </ol>
    </div>
  );
}

function UpdateCard({ update: u }: { update: StatusUpdate }) {
  const people = usePeople().data;
  const author = people?.find((p) => p.id === u.author_id)?.name ?? 'Former member';
  const citations = u.citations as Citation[];
  return (
    <article aria-label={`Status: ${u.title}`} className="rounded-lg border border-hair-soft p-4">
      <header className="mb-2 flex flex-wrap items-center gap-2">
        <StatusChip status={u.status} />
        <h3 className="flex-1 font-medium">{u.title}</h3>
        {u.generated_by_ai ? <AIBadge title="Drafted by Mo, edited and posted by a person" /> : null}
        <span className="text-xs text-muted">
          {author} · {formatRelative(u.created_at)}
        </span>
      </header>
      {u.summary ? <MoText text={u.summary} citations={citations} /> : null}
      {SECTIONS.map(([key, label]) =>
        u.sections[key]?.length ? (
          <section key={key} className="mt-2" aria-label={label}>
            <h4 className="section-label">{label}</h4>
            <MoText text={u.sections[key]!.map((i) => `- ${i.text}`).join('\n')} citations={citations} />
          </section>
        ) : null,
      )}
    </article>
  );
}

const lines = (text: string) =>
  text
    .split('\n')
    .map((l) => l.replace(/^\s*[-*•]\s*/, '').trim())
    .filter(Boolean)
    .map((t) => ({ text: t }));

function StatusEditor({
  projectId,
  initial,
  fromAi,
  notes,
  onDone,
}: {
  projectId: string;
  initial: StatusUpdateIn;
  fromAi: boolean;
  notes: string[];
  onDone: () => void;
}) {
  const post = usePostStatus(projectId);
  const notify = useUndoToast();
  const [status, setStatus] = useState<Status>(initial.status);
  const [title, setTitle] = useState(initial.title);
  const [summary, setSummary] = useState(initial.summary ?? '');
  const [sections, setSections] = useState<Record<SectionKey, string>>(() => ({
    completed: (initial.sections?.completed ?? []).map((i) => i.text).join('\n'),
    slipped: (initial.sections?.slipped ?? []).map((i) => i.text).join('\n'),
    blockers: (initial.sections?.blockers ?? []).map((i) => i.text).join('\n'),
    next: (initial.sections?.next ?? []).map((i) => i.text).join('\n'),
  }));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    post.mutate(
      {
        status,
        title: title.trim(),
        summary: summary.trim(),
        sections: {
          completed: lines(sections.completed),
          slipped: lines(sections.slipped),
          blockers: lines(sections.blockers),
          next: lines(sections.next),
        },
        generated_by_ai: fromAi,
      },
      {
        onSuccess: (r) => {
          notify('Status update posted', r.meta);
          onDone();
        },
      },
    );
  };
  const form = (
    <form onSubmit={submit} aria-label="Status update" className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <label className="flex items-center gap-2 text-sm">
          Status
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value as Status)}
            className="h-8 rounded-md border border-hairline bg-surface px-2 text-sm"
          >
            {Object.entries(STATUS_LABEL).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <input
          aria-label="Headline"
          placeholder="Headline, e.g. Beta on track"
          value={title}
          maxLength={200}
          onChange={(e) => setTitle(e.target.value)}
          className="h-8 min-w-0 flex-1 rounded-md border border-hairline bg-surface px-2 text-sm outline-none focus:border-focus"
        />
      </div>
      <textarea
        aria-label="Summary"
        placeholder="Summary"
        value={summary}
        maxLength={4000}
        rows={2}
        onChange={(e) => setSummary(e.target.value)}
        className="w-full rounded-md border border-hairline bg-surface p-2 text-sm outline-none focus:border-focus"
      />
      {SECTIONS.map(([key, label]) => (
        <label key={key} className="block text-sm">
          <span className="section-label">{label}</span>
          <textarea
            aria-label={label}
            placeholder="One item per line"
            value={sections[key]}
            rows={2}
            onChange={(e) => setSections((s) => ({ ...s, [key]: e.target.value }))}
            className="mt-1 w-full rounded-md border border-hairline bg-surface p-2 text-sm outline-none focus:border-focus"
          />
        </label>
      ))}
      <div className="flex gap-2">
        <Button type="submit" size="sm" loading={post.isPending} disabled={!title.trim()}>
          Post update
        </Button>
        <Button size="sm" variant="ghost" onClick={onDone}>
          Discard
        </Button>
      </div>
    </form>
  );
  if (!fromAi) return <div className="rounded-lg border border-hair-soft p-4">{form}</div>;
  return (
    <AICallout label="Mo’s draft">
      <p className="mb-2 text-xs text-muted">
        Drafted from the last 7 days of activity. Edit anything before posting; it is posted as yours, marked
        as drafted by Mo.
      </p>
      {notes.length ? (
        <ul aria-label="Mo left out" className="mb-2 list-disc space-y-0.5 pl-5 text-xs text-muted">
          {notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      ) : null}
      {form}
    </AICallout>
  );
}
