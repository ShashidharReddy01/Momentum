import { useState } from 'react';
import { toast } from 'sonner';
import { AICallout } from '@/components/common/AI';
import { ErrorState } from '@/components/common/States';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { Skeleton } from '@/components/ui/Skeleton';
import { cn } from '@/lib/cn';
import { useAiAction, useAiActionMutations, type AiAction, type DiffRow } from './queries';

const VERBS: Record<string, string> = {
  'task.created': 'New task',
  'task.updated': 'Edit',
  'task.completed': 'Complete',
  'task.uncompleted': 'Reopen',
  'task.deleted': 'Delete',
  'task.moved': 'Move',
  'task.added_to_project': 'Add to project',
  'task.removed_from_project': 'Remove from project',
  'comment.created': 'Comment',
  'project.created': 'New project',
  'section.created': 'New section',
  'section.renamed': 'Rename section',
};

const FIELDS: Record<string, string> = {
  title: 'Title',
  name: 'Name',
  assignee_id: 'Assignee',
  due_on: 'Due',
  due_at: 'Due time',
  start_on: 'Start',
  section_id: 'Section',
  project_id: 'Project',
  parent_id: 'Under',
  completed_at: 'Completed',
  description: 'Description',
  body: 'Comment',
  task_id: 'Task',
};

const RISK: Record<AiAction['risk'], { label: string; className: string }> = {
  low: { label: 'Low risk', className: 'bg-ok-tint text-ok' },
  medium: { label: 'Medium risk', className: 'bg-warn-tint text-warn' },
  high: { label: 'High risk', className: 'bg-crit-tint text-crit' },
};

const DONE: Partial<Record<AiAction['state'], string>> = {
  applied: 'Applied',
  rejected: 'Dismissed',
  expired: 'This suggestion expired. Ask Mo again.',
  undone: 'Undone',
  failed: 'Couldn’t apply these changes',
};

function show(field: string, value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (field === 'completed_at') return 'yes';
  return String(value);
}

/** Diff rows of all operations, grouped by the entity they touch (in first-seen order). */
export function groupDiff(action: AiAction): { label: string; rows: DiffRow[] }[] {
  const groups = new Map<string, { label: string; rows: DiffRow[] }>();
  for (const op of action.operations) {
    for (const row of op.diff) {
      const k = `${row.entity_type}:${row.entity_id}`;
      const g = groups.get(k) ?? { label: row.label, rows: [] };
      g.rows.push(row);
      groups.set(k, g);
    }
  }
  return [...groups.values()];
}

function Change({ row }: { row: DiffRow }) {
  const fields = Object.entries(row.display).filter(
    ([f]) => !(row.verb.endsWith('.created') && f === 'title'),
  );
  return (
    <li className="text-[13px]">
      <span className="font-medium text-ink">{VERBS[row.verb] ?? row.verb}</span>
      {fields.length ? (
        <ul className="ml-3 mt-0.5 space-y-0.5 text-ink-2">
          {fields.map(([f, pair]) => (
            <li key={f}>
              {row.verb.endsWith('.created')
                ? `${FIELDS[f] ?? f}: ${show(f, pair[1])}`
                : `${FIELDS[f] ?? f}: ${show(f, pair[0])} → ${show(f, pair[1])}`}
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

/**
 * A proposed AI action (S3.1.3): what would change, grouped by entity, with its risk. Apply runs
 * it (a high-risk action asks for confirmation first); Edit hands control back to where the
 * request came from (e.g. the ⌘K input); Cancel dismisses it. After applying, a toast offers
 * Undo for the whole action.
 */
export function PreviewCard({ actionId, onEdit }: { actionId: string; onEdit?: () => void }) {
  const q = useAiAction(actionId);
  const m = useAiActionMutations(actionId);
  const [confirming, setConfirming] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  if (q.isPending) return <Skeleton className="h-24 w-full" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  const action = q.data;
  const groups = groupDiff(action);
  const count = groups.length;
  const pending = action.state === 'proposed';

  const apply = (confirmed: boolean) => {
    setNotice(null);
    m.apply.mutate(confirmed, {
      onSuccess: (r) => {
        setConfirming(false);
        if (r.outcome === 'repreviewed') {
          setNotice('Something changed since this preview. Check the updated changes before applying.');
        } else if (r.outcome === 'applied') {
          toast.success(`Applied: ${r.data.summary}`, {
            duration: 8000,
            action: {
              label: 'Undo',
              onClick: () => m.undo.mutate(undefined, { onSuccess: () => toast('Undone') }),
            },
          });
        }
      },
    });
  };

  return (
    <AICallout
      label="Mo suggests"
      actions={
        pending ? (
          <>
            <Button
              variant="ai"
              size="sm"
              loading={m.apply.isPending}
              onClick={() => (action.risk === 'high' ? setConfirming(true) : apply(false))}
            >
              Apply
            </Button>
            {onEdit ? (
              <Button variant="text" size="sm" onClick={onEdit}>
                Edit
              </Button>
            ) : null}
            <Button variant="text" size="sm" loading={m.reject.isPending} onClick={() => m.reject.mutate()}>
              Cancel
            </Button>
          </>
        ) : undefined
      }
    >
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="font-medium text-ink">{action.summary}</span>
        <span className={cn('rounded px-1.5 py-0.5 text-[11px] font-medium', RISK[action.risk].className)}>
          {RISK[action.risk].label}
        </span>
      </div>
      {notice ? (
        <p role="status" className="mb-2 rounded bg-warn-tint px-2 py-1 text-[13px] text-warn">
          {notice}
        </p>
      ) : null}
      <ul aria-label="Proposed changes" className="space-y-2">
        {groups.map((g) => (
          <li key={g.label + g.rows[0]!.entity_id}>
            <div className="text-[13px] font-semibold text-ink">{g.label}</div>
            <ul className="mt-0.5 space-y-1 pl-2">
              {g.rows.map((row, i) => (
                <Change key={i} row={row} />
              ))}
            </ul>
          </li>
        ))}
      </ul>
      {!pending ? (
        <p role="status" className="mt-2 text-[13px] text-muted">
          {DONE[action.state] ?? action.state}
          {action.state === 'failed' && action.error ? `: ${action.error}` : null}
        </p>
      ) : null}
      <Dialog
        open={confirming}
        onOpenChange={setConfirming}
        title={`Apply ${count} change${count === 1 ? '' : 's'}?`}
        description="This is a high-risk change. You can undo it right after, but check it first."
      >
        <div className="px-5 py-4 text-sm text-ink-2">{action.summary}</div>
        <div className="flex justify-end gap-2 border-t border-hair-soft px-5 py-3">
          <Button variant="ghost" onClick={() => setConfirming(false)}>
            Go back
          </Button>
          <Button variant="danger" loading={m.apply.isPending} onClick={() => apply(true)}>
            Yes, apply
          </Button>
        </div>
      </Dialog>
    </AICallout>
  );
}
