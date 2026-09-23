import { useDraggable, useDroppable } from '@dnd-kit/core';
import { CalendarDays, MoreHorizontal, Trash2, UserRound } from 'lucide-react';
import {
  forwardRef,
  memo,
  useCallback,
  useEffect,
  useRef,
  useState,
  type ComponentProps,
  type KeyboardEvent,
  type MouseEvent,
} from 'react';
import { CompleteCheck } from '@/components/common/CompleteCheck';
import { DueText } from '@/components/common/DueText';
import { Avatar } from '@/components/ui/Avatar';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu';
import { Icon } from '@/components/ui/Icon';
import { IconButton } from '@/components/ui/IconButton';
import { cn } from '@/lib/cn';
import { formatDue } from '@/lib/dates';
import type { Person } from '@/features/people';
import { AssigneePicker } from './AssigneePicker';
import { DatePicker } from './DatePicker';
import { isTemp, type Task, type TaskPatch } from './queries';
import type { DropPlacement, Modifiers } from './selection';

type Picker = 'assignee' | 'due' | null;

export interface TaskRowProps {
  task: Task;
  canEdit: boolean;
  fading?: boolean;
  assignee?: Person;
  meId?: string;
  selected?: boolean;
  /** Whether the row can be dragged (off while sorted or grouped). */
  draggable?: boolean;
  /** Part of the set being dragged (dimmed). */
  dragging?: boolean;
  dropIndicator?: DropPlacement | null;
  /** Row clicks (plain / shift / ⌘) drive the selection. */
  onSelectClick?: (task: Task, mods: Modifiers) => void;
  onFocusRow?: (task: Task) => void;
  onUpdate: (task: Task, patch: TaskPatch, message?: string) => void;
  onToggle: (task: Task) => void;
  onRename: (task: Task, title: string) => void;
  onEnter: (task: Task) => void;
  onDelete: (task: Task) => void;
}

export const TaskRow = memo(function TaskRow({
  task,
  canEdit,
  fading,
  assignee,
  meId,
  selected = false,
  draggable = true,
  dragging = false,
  dropIndicator = null,
  onSelectClick,
  onFocusRow,
  onUpdate,
  onToggle,
  onRename,
  onEnter,
  onDelete,
}: TaskRowProps) {
  const [editing, setEditing] = useState(false);
  const [picker, setPicker] = useState<Picker>(null);
  const row = useRef<HTMLDivElement | null>(null);
  const drag = useDraggable({
    id: task.id,
    data: { kind: 'task', sectionId: task.section_id },
    disabled: !canEdit || !draggable || editing || picker !== null || isTemp(task.id),
  });
  const drop = useDroppable({
    id: `row:${task.id}`,
    data: { kind: 'task', taskId: task.id, sectionId: task.section_id },
  });
  const { setNodeRef: setDragRef } = drag;
  const { setNodeRef: setDropRef } = drop;
  const setRefs = useCallback(
    (node: HTMLDivElement | null) => {
      row.current = node;
      setDragRef(node);
      setDropRef(node);
    },
    [setDragRef, setDropRef],
  );
  // Pointer drags only: Enter/Space on a row are editing keys, not keyboard-drag keys.
  const onPointerDown = drag.listeners?.onPointerDown as ((e: unknown) => void) | undefined;
  const onClickCapture = (e: MouseEvent) => {
    const mods = { shift: e.shiftKey, meta: e.metaKey || e.ctrlKey };
    if (mods.shift || mods.meta) {
      e.preventDefault();
      e.stopPropagation();
      if (mods.shift) window.getSelection()?.removeAllRanges();
      onSelectClick?.(task, mods);
      row.current?.focus();
    } else {
      onSelectClick?.(task, {});
    }
  };
  const [draft, setDraft] = useState(task.title);
  const input = useRef<HTMLInputElement>(null);
  const done = !!task.completed_at;

  useEffect(() => {
    if (!editing) setDraft(task.title);
  }, [task.title, editing]);
  useEffect(() => {
    if (editing) input.current?.focus();
  }, [editing]);

  const commit = () => {
    setEditing(false);
    const title = draft.trim().replace(/\s+/g, ' ');
    if (title && title !== task.title) onRename(task, title);
    else setDraft(task.title);
  };
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      commit();
      onEnter(task);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      setDraft(task.title);
      setEditing(false);
    }
  };

  const assign = (id: string | null, name?: string) =>
    onUpdate(task, { assignee_id: id }, id ? `Assigned to ${name ?? 'you'}` : 'Unassigned');
  const closePicker = (open: boolean) => {
    if (!open) {
      setPicker(null);
      requestAnimationFrame(() => row.current?.focus());
    }
  };
  // Row shortcuts (ux-specs §keyboard): A assign, M assign to me, D due date
  const onRowKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.target !== e.currentTarget || !canEdit || e.metaKey || e.ctrlKey || e.altKey) return;
    const k = e.key.toLowerCase();
    if (k === 'a') setPicker('assignee');
    else if (k === 'd') setPicker('due');
    else if (k === 'm' && meId && task.assignee_id !== meId) assign(meId);
    else if (e.key === 'Enter') setEditing(true);
    else return;
    e.preventDefault();
  };

  return (
    // Rows are keyboard targets (A/M/D/Enter); S1.2.4 adds roving focus + selection.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <div
      ref={setRefs}
      role="listitem"
      aria-label={task.title}
      data-selected={selected || undefined}
      data-task-id={task.id}
      data-section-id={task.section_id}
      onPointerDown={onPointerDown}
      onClickCapture={onClickCapture}
      onFocus={(e) => e.target === e.currentTarget && onFocusRow?.(task)}
      // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
      tabIndex={0}
      onKeyDown={onRowKey}
      className={cn(
        'group/row relative flex h-9 items-center gap-2.5 border-b border-hair-soft px-2 transition-opacity duration-300 outline-none hover:bg-surface-2 focus-visible:bg-surface-2 focus-visible:shadow-[inset_2px_0_0_var(--focus)]',
        (done || fading) && 'text-muted',
        fading && 'opacity-60',
        selected && 'bg-selection hover:bg-selection focus-visible:bg-selection',
        dragging && 'opacity-40',
      )}
    >
      {selected ? <span className="sr-only">Selected</span> : null}
      {dropIndicator ? (
        <span
          aria-hidden
          data-drop={dropIndicator}
          className={cn(
            'pointer-events-none absolute right-0 left-0 z-10 h-0.5 rounded-full bg-focus',
            dropIndicator === 'before' ? '-top-px' : '-bottom-px',
          )}
        />
      ) : null}
      <CompleteCheck
        checked={done}
        disabled={!canEdit}
        label={done ? `Mark ${task.title} incomplete` : `Complete ${task.title}`}
        onChange={() => onToggle(task)}
      />
      {editing ? (
        <input
          ref={input}
          aria-label="Task name"
          value={draft}
          maxLength={500}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={onKey}
          className="h-7 min-w-0 flex-1 rounded-sm border border-focus bg-surface px-1 text-[13.5px] outline-none"
        />
      ) : (
        <button
          type="button"
          disabled={!canEdit}
          onClick={() => setEditing(true)}
          className={cn(
            'min-w-0 flex-1 cursor-text truncate text-left text-[13.5px] disabled:cursor-default',
            done && 'line-through decoration-muted-2',
          )}
        >
          {task.title}
        </button>
      )}
      <span className="w-14 shrink-0 text-right font-mono text-[11px] text-muted-2 opacity-0 group-hover/row:opacity-100">
        {isTemp(task.id) ? '…' : task.key}
      </span>
      <AssigneePicker
        open={picker === 'assignee'}
        onOpenChange={(o) => (o ? setPicker('assignee') : closePicker(false))}
        assigneeId={task.assignee_id}
        onChange={(u) => assign(u?.id ?? null, u?.id === meId ? 'you' : u?.name)}
      >
        <Cell
          disabled={!canEdit}
          className="w-36"
          aria-label={assignee ? `Assignee: ${assignee.name}` : 'Assign'}
          aria-keyshortcuts="A"
        >
          {assignee ? (
            <>
              <Avatar name={assignee.name} src={assignee.avatar_url} size={20} />
              <span className="truncate text-[12.5px] text-ink-2">{assignee.name.split(' ')[0]}</span>
            </>
          ) : (
            <Placeholder icon={UserRound} show={canEdit} />
          )}
        </Cell>
      </AssigneePicker>
      <DatePicker
        open={picker === 'due'}
        onOpenChange={(o) => (o ? setPicker('due') : closePicker(false))}
        dueOn={task.due_on}
        dueAt={task.due_at}
        onChange={(v) =>
          onUpdate(
            task,
            v ? { due_on: v.date, due_at: v.at } : { due_on: null, due_at: null },
            v ? `Due date set: ${formatDue(v.date, v.at)}` : 'Due date removed',
          )
        }
      >
        <Cell
          disabled={!canEdit}
          className="w-32"
          aria-label={task.due_on ? `Due ${formatDue(task.due_on, task.due_at)}` : 'Set due date'}
          aria-keyshortcuts="D"
        >
          {task.due_on ? (
            <DueText dueOn={task.due_on} dueAt={task.due_at} startOn={task.start_on} done={done} />
          ) : (
            <Placeholder icon={CalendarDays} show={canEdit} />
          )}
        </Cell>
      </DatePicker>
      {canEdit ? (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <IconButton
              icon={MoreHorizontal}
              label={`Actions for ${task.title}`}
              size="icon-sm"
              className="opacity-0 group-hover/row:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100"
            />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem className="text-crit" onSelect={() => onDelete(task)}>
              <Icon icon={Trash2} /> Delete task
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      ) : (
        <span className="w-7" />
      )}
    </div>
  );
});

/** A clickable list cell that opens a picker; forwards the Radix trigger props. */
const Cell = forwardRef<HTMLButtonElement, ComponentProps<'button'>>(function Cell(
  { className, children, ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      type="button"
      tabIndex={-1}
      className={cn(
        'flex h-7 shrink-0 items-center gap-1.5 rounded-md px-1.5 text-left hover:bg-surface disabled:pointer-events-none data-[state=open]:bg-surface',
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
});

function Placeholder({ icon, show }: { icon: typeof UserRound; show: boolean }) {
  return show ? (
    <span className="flex h-5 w-5 items-center justify-center rounded-full border border-dashed border-muted-2 text-muted-2 opacity-0 group-hover/row:opacity-100 group-focus-visible/row:opacity-100">
      <Icon icon={icon} size={12} />
    </span>
  ) : null;
}

export function DraftRow({
  onSubmit,
  onPasteLines,
  onCancel,
}: {
  onSubmit: (title: string) => void;
  onPasteLines: (lines: string[]) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState('');
  return (
    <div
      role="listitem"
      aria-label="New task"
      className="flex h-9 items-center gap-2.5 border-b border-hair-soft px-2"
    >
      <CompleteCheck checked={false} disabled label="New task" onChange={() => {}} />
      <input
        aria-label="New task name"
        placeholder="Write a task name"
        value={value}
        maxLength={500}
        // eslint-disable-next-line jsx-a11y/no-autofocus -- the user just asked for a new task row
        autoFocus
        onChange={(e) => setValue(e.target.value)}
        onBlur={() => {
          if (value.trim()) onSubmit(value.trim());
          onCancel();
        }}
        onPaste={(e) => {
          const lines = e.clipboardData
            .getData('text')
            .split(/\r?\n/)
            .map((l) => l.trim())
            .filter(Boolean);
          if (lines.length > 1) {
            e.preventDefault();
            onPasteLines(lines);
          }
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            const title = value.trim();
            if (!title) return onCancel();
            setValue('');
            onSubmit(title);
          } else if (e.key === 'Escape') {
            e.preventDefault();
            onCancel();
          }
        }}
        className="h-7 min-w-0 flex-1 rounded-sm bg-transparent px-1 text-[13.5px] outline-none placeholder:text-muted-2"
      />
    </div>
  );
}
