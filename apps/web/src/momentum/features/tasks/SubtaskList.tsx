import { ArrowDown, ArrowUp, CornerLeftUp, MoreHorizontal, PanelRightOpen, Plus, Trash2 } from 'lucide-react';
import { useEffect, useState, type KeyboardEvent } from 'react';
import { CompleteCheck } from '@/components/common/CompleteCheck';
import { DueText } from '@/components/common/DueText';
import { InlineText } from '@/components/common/InlineText';
import { Avatar } from '@/components/ui/Avatar';
import { Button } from '@/components/ui/Button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu';
import { Icon } from '@/components/ui/Icon';
import { Skeleton } from '@/components/ui/Skeleton';
import { useMe } from '@/features/auth';
import { usePeople } from '@/features/people';
import { cn } from '@/lib/cn';
import { formatDue } from '@/lib/dates';
import { AssigneePicker } from './AssigneePicker';
import { DatePicker } from './DatePicker';
import type { Task } from './queries';
import { useSubtaskMutations, useSubtasks } from './subtasks';
import { DraftRow } from './TaskRow';

/**
 * A task's subtasks: complete, rename, assign, date, reorder (⌘↑/⌘↓ or menu), move out, delete,
 * and add more (Enter keeps adding). Used in the task pane and inline under list rows.
 */
export function SubtaskList({
  parentId,
  canEdit,
  onOpen,
  compact = false,
  startDraft = false,
  initialDraft,
  onDraftDone,
  onOutdentDraft,
}: {
  /** Text already typed in the row that became a subtask row. */
  initialDraft?: string;
  parentId: string;
  canEdit: boolean;
  onOpen?: (task: Task) => void;
  compact?: boolean;
  /** Start with an "add subtask" row open (Tab from a new list row). */
  startDraft?: boolean;
  onDraftDone?: () => void;
  /** Shift+Tab on the add row: the caller turns it back into a top-level task row. */
  onOutdentDraft?: (title: string) => void;
}) {
  const subs = useSubtasks(parentId);
  const m = useSubtaskMutations(parentId);
  const [drafting, setDrafting] = useState(startDraft);
  // Tab from a new list row while this list is already open: start the add row now
  useEffect(() => {
    if (startDraft) setDrafting(true);
  }, [startDraft]);
  const [draftKey, setDraftKey] = useState(0);
  const people = usePeople().data;
  const meId = useMe().data?.user.id;

  if (subs.isPending) return <Skeleton className="h-8" />;
  const list = subs.data ?? [];
  const done = list.filter((t) => t.completed_at).length;

  const moveBy = (t: Task, dir: 1 | -1) => {
    const i = list.findIndex((x) => x.id === t.id);
    const j = i + dir;
    if (j < 0 || j >= list.length) return;
    const other = list[j]!;
    m.reorder.mutate(
      dir === 1
        ? { id: t.id, afterId: other.id, beforeId: null }
        : { id: t.id, afterId: null, beforeId: other.id },
    );
  };

  return (
    <div className={cn(!compact && 'mt-6')}>
      {!compact ? (
        <h3 className="section-label mb-1 flex items-center gap-2">
          Subtasks
          {list.length ? (
            <span className="tabular font-normal normal-case text-muted-2">
              {done}/{list.length}
            </span>
          ) : null}
        </h3>
      ) : null}
      <div role="list" aria-label="Subtasks">
        {list.map((t, i) => (
          <SubtaskRow
            key={t.id}
            task={t}
            canEdit={canEdit}
            assigneeName={people?.find((p) => p.id === t.assignee_id)?.name}
            meId={meId}
            first={i === 0}
            last={i === list.length - 1}
            onToggle={() => m.setCompleted.mutate({ id: t.id, completed: !t.completed_at })}
            onRename={(title) => m.update.mutate({ id: t.id, patch: { title } })}
            onAssign={(u) =>
              m.update.mutate({
                id: t.id,
                patch: { assignee_id: u?.id ?? null },
                message: u ? `Assigned to ${u.id === meId ? 'you' : u.name}` : 'Unassigned',
              })
            }
            onDue={(v) =>
              m.update.mutate({
                id: t.id,
                patch: v ? { due_on: v.date, due_at: v.at } : { due_on: null, due_at: null },
              })
            }
            onMove={(dir) => moveBy(t, dir)}
            onOutdent={() => m.outdent.mutate(t.id)}
            onDelete={() => m.remove.mutate(t.id)}
            onOpen={onOpen && !t.id.startsWith('tmp-') ? () => onOpen(t) : undefined}
          />
        ))}
        {drafting ? (
          <DraftRow
            key={draftKey}
            placeholder="Subtask name"
            initialValue={draftKey === 0 ? initialDraft : undefined}
            onSubmit={(title) => {
              m.create.mutate({ title });
              setDraftKey((k) => k + 1);
            }}
            onPasteLines={(lines) => lines.forEach((title) => m.create.mutate({ title }))}
            onCancel={() => {
              setDrafting(false);
              onDraftDone?.();
            }}
            onShiftTab={
              onOutdentDraft
                ? (title) => {
                    setDrafting(false);
                    onOutdentDraft(title);
                  }
                : undefined
            }
          />
        ) : null}
      </div>
      {canEdit && !drafting ? (
        <Button variant="text" size="sm" className="mt-1 text-muted" onClick={() => setDrafting(true)}>
          <Icon icon={Plus} /> Add subtask
        </Button>
      ) : null}
    </div>
  );
}

function SubtaskRow({
  task,
  canEdit,
  assigneeName,
  meId,
  first,
  last,
  onToggle,
  onRename,
  onAssign,
  onDue,
  onMove,
  onOutdent,
  onDelete,
  onOpen,
}: {
  task: Task;
  canEdit: boolean;
  assigneeName?: string;
  meId?: string;
  first: boolean;
  last: boolean;
  onToggle: () => void;
  onRename: (title: string) => void;
  onAssign: (u: { id: string; name: string } | null) => void;
  onDue: (v: { date: string; at: string | null } | null) => void;
  onMove: (dir: 1 | -1) => void;
  onOutdent: () => void;
  onDelete: () => void;
  onOpen?: () => void;
}) {
  const [picker, setPicker] = useState<'assignee' | 'due' | null>(null);
  const done = !!task.completed_at;
  const temp = task.id.startsWith('tmp-');
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.target !== e.currentTarget || !canEdit) return;
    const mod = e.metaKey || e.ctrlKey;
    if (mod && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
      e.preventDefault();
      onMove(e.key === 'ArrowDown' ? 1 : -1);
    } else if (mod && e.key === 'Enter') {
      e.preventDefault();
      onToggle();
    } else if (!mod && e.key.toLowerCase() === 'm' && meId) {
      e.preventDefault();
      onAssign({ id: meId, name: 'you' });
    } else if (e.key === ' ' && onOpen) {
      e.preventDefault();
      onOpen();
    }
  };
  return (
    // Keyboard shortcuts on the focused subtask row (⌘↑/⌘↓, ⌘Enter, M, Space).
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <div
      role="listitem"
      aria-label={task.title}
      data-subtask-id={task.id}
      // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
      tabIndex={0}
      onKeyDown={onKeyDown}
      className="group/sub flex h-9 items-center gap-2 border-b border-hair-soft px-1 outline-none focus-visible:bg-surface-2 hover:bg-surface-2"
    >
      <CompleteCheck
        checked={done}
        disabled={!canEdit || temp}
        size={16}
        label={done ? `Mark ${task.title} incomplete` : `Complete ${task.title}`}
        onChange={onToggle}
      />
      <div className={cn('min-w-0 flex-1 text-[13.5px]', done && 'text-muted line-through')}>
        <InlineText
          aria-label="Subtask name"
          value={task.title}
          disabled={!canEdit || temp}
          onCommit={onRename}
        />
      </div>
      {task.subtask_count ? (
        <span className="tabular text-xs text-muted-2" title="Subtasks">
          ↳ {task.completed_subtask_count}/{task.subtask_count}
        </span>
      ) : null}
      <AssigneePicker
        open={picker === 'assignee'}
        onOpenChange={(o) => setPicker(o ? 'assignee' : null)}
        assigneeId={task.assignee_id}
        onChange={onAssign}
      >
        <button
          type="button"
          disabled={!canEdit || temp}
          aria-label={assigneeName ? `Assignee: ${assigneeName}` : 'Assign subtask'}
          className="grid h-7 w-7 place-items-center rounded-md hover:bg-surface disabled:pointer-events-none"
        >
          {assigneeName ? (
            <Avatar name={assigneeName} size={20} />
          ) : (
            <span className="h-5 w-5 rounded-full border border-dashed border-muted-2 opacity-0 group-hover/sub:opacity-100" />
          )}
        </button>
      </AssigneePicker>
      <DatePicker
        open={picker === 'due'}
        onOpenChange={(o) => setPicker(o ? 'due' : null)}
        dueOn={task.due_on}
        dueAt={task.due_at}
        onChange={onDue}
      >
        <button
          type="button"
          disabled={!canEdit || temp}
          aria-label={task.due_on ? `Due ${formatDue(task.due_on, task.due_at)}` : 'Set subtask due date'}
          className="flex h-7 min-w-7 items-center rounded-md px-1 hover:bg-surface disabled:pointer-events-none"
        >
          {task.due_on ? (
            <DueText dueOn={task.due_on} dueAt={task.due_at} done={done} />
          ) : (
            <span className="h-5 w-5 rounded-full border border-dashed border-muted-2 opacity-0 group-hover/sub:opacity-100" />
          )}
        </button>
      </DatePicker>
      {onOpen ? (
        <button
          type="button"
          aria-label={`Open ${task.title}`}
          title="Open"
          onClick={onOpen}
          className="grid h-7 w-7 place-items-center rounded-md text-muted opacity-0 group-hover/sub:opacity-100 hover:bg-surface hover:text-ink focus-visible:opacity-100"
        >
          <Icon icon={PanelRightOpen} size={15} />
        </button>
      ) : null}
      {canEdit && !temp ? (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              aria-label={`Actions for ${task.title}`}
              className="grid h-7 w-7 place-items-center rounded-md text-muted opacity-0 group-hover/sub:opacity-100 hover:bg-surface hover:text-ink focus-visible:opacity-100 data-[state=open]:opacity-100"
            >
              <Icon icon={MoreHorizontal} size={15} />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem disabled={first} onSelect={() => onMove(-1)}>
              <Icon icon={ArrowUp} /> Move up
            </DropdownMenuItem>
            <DropdownMenuItem disabled={last} onSelect={() => onMove(1)}>
              <Icon icon={ArrowDown} /> Move down
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={onOutdent}>
              <Icon icon={CornerLeftUp} /> Move out of parent
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem className="text-crit" onSelect={onDelete}>
              <Icon icon={Trash2} /> Delete subtask
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      ) : null}
    </div>
  );
}
