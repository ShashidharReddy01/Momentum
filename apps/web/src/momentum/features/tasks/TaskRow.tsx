import { useDraggable, useDroppable } from '@dnd-kit/core';
import { CalendarDays, MoreHorizontal, PanelRightOpen, Trash2, UserRound } from 'lucide-react';
import {
  forwardRef,
  memo,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ComponentProps,
  type KeyboardEvent,
  type MouseEvent,
  type RefObject,
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
import { cn } from '@/lib/cn';
import { formatDue } from '@/lib/dates';
import { FieldValueChip, type ProjectField as ProjectFieldT } from '@/features/fields';
import type { Person } from '@/features/people';
import { AssigneePicker } from './AssigneePicker';
import { DatePicker } from './DatePicker';
import { isTemp, type Task, type TaskPatch } from './queries';
import type { DropPlacement, Modifiers } from './selection';

type Picker = 'assignee' | 'due' | null;
const INTERACTIVE = 'button, input, textarea, a, [role="checkbox"], [role="menuitem"]';

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
  /** This task is open in the details pane. */
  isOpen?: boolean;
  /** Open (or toggle) the details pane. */
  onOpen?: (task: Task) => void;
  /** My Tasks: show which project the task is in, instead of the assignee. */
  project?: { id: string; name: string; color: string | null } | null;
  hideAssignee?: boolean;
  /** Custom fields visible in this view, and this task's own values — read-only chips (S2.3.2;
   * editing happens in the pane). Omitted where the project has none, so most rows pay nothing. */
  fields?: ProjectFieldT[];
  fieldValues?: Map<string, unknown>;
  /** Subtasks shown inline under the row. */
  expanded?: boolean;
  onToggleExpand?: (task: Task) => void;
  onFocusRow?: (task: Task) => void;
  onUpdate: (task: Task, patch: TaskPatch, message?: string) => void;
  onToggle: (task: Task) => void;
  onRename: (task: Task, title: string) => void;
  onEnter: (task: Task) => void;
  onDelete: (task: Task) => void;
}

/**
 * A list row. Split in two for performance: this thin shell owns the drag-and-drop hooks (dnd-kit
 * re-renders every hook user when any draggable/droppable registers, e.g. while scrolling a
 * virtualized list) and passes stable refs/handlers to the memoized {@link RowBody}, which only
 * re-renders when the task or its own props change.
 */
export const TaskRow = memo(function TaskRow(props: TaskRowProps) {
  const { task, canEdit, draggable = true } = props;
  const [busy, setBusy] = useState(false);
  const node = useRef<HTMLDivElement | null>(null);
  const drag = useDraggable({
    id: task.id,
    data: { kind: 'task', sectionId: task.section_id },
    disabled: !canEdit || !draggable || busy || isTemp(task.id),
  });
  const { setNodeRef: setDragRef } = drag;
  const setDndRef = useCallback(
    (el: HTMLDivElement | null) => {
      node.current = el;
      setDragRef(el);
    },
    [setDragRef],
  );
  // Pointer drags only: Enter/Space on a row are editing keys, not keyboard-drag keys.
  const onPointerDown = drag.listeners?.onPointerDown as ((e: unknown) => void) | undefined;
  return (
    <>
      {/* Drop targets exist only during a drag: registering one re-renders every dnd-kit hook,
          which made each row mounted while scrolling re-render all mounted rows. */}
      {drag.active ? <RowDropTarget task={task} node={node} /> : null}
      <RowBody {...props} setDndRef={setDndRef} onPointerDown={onPointerDown} setBusy={setBusy} />
    </>
  );
});

function RowDropTarget({ task, node }: { task: Task; node: RefObject<HTMLDivElement | null> }) {
  const { setNodeRef } = useDroppable({
    id: `row:${task.id}`,
    data: { kind: 'task', taskId: task.id, sectionId: task.section_id },
  });
  useLayoutEffect(() => {
    setNodeRef(node.current);
    return () => setNodeRef(null);
  }, [node, setNodeRef]);
  return null;
}

const RowBody = memo(function RowBody({
  task,
  canEdit,
  fading,
  assignee,
  meId,
  selected = false,
  dragging = false,
  dropIndicator = null,
  onSelectClick,
  onFocusRow,
  isOpen = false,
  onOpen,
  expanded = false,
  onToggleExpand,
  project,
  hideAssignee = false,
  fields,
  fieldValues,
  onUpdate,
  onToggle,
  onRename,
  onEnter,
  onDelete,
  setDndRef,
  onPointerDown,
  setBusy,
}: TaskRowProps & {
  setDndRef: (node: HTMLDivElement | null) => void;
  onPointerDown?: (e: unknown) => void;
  setBusy: (busy: boolean) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [picker, setPicker] = useState<Picker>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const row = useRef<HTMLDivElement | null>(null);
  const setRefs = useCallback(
    (node: HTMLDivElement | null) => {
      row.current = node;
      setDndRef(node);
    },
    [setDndRef],
  );
  useEffect(() => setBusy(editing || picker !== null), [editing, picker, setBusy]);
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
    else if (e.key === ' ' && onOpen) onOpen(task);
    else return;
    e.preventDefault();
  };

  const assigneeCell = (
    <Cell
      disabled={!canEdit}
      className="w-36 @max-3xl:w-10"
      aria-label={assignee ? `Assignee: ${assignee.name}` : 'Assign'}
      aria-keyshortcuts="A"
      onClick={() => setPicker('assignee')}
    >
      {assignee ? (
        <>
          <Avatar name={assignee.name} src={assignee.avatar_url} size={20} />
          <span className="truncate text-[12.5px] text-ink-2 @max-3xl:hidden">
            {assignee.name.split(' ')[0]}
          </span>
        </>
      ) : (
        <Placeholder icon={UserRound} show={canEdit} />
      )}
    </Cell>
  );
  const dueCell = (
    <Cell
      disabled={!canEdit}
      className="w-32 @max-3xl:w-28 @max-md:w-20"
      aria-label={task.due_on ? `Due ${formatDue(task.due_on, task.due_at)}` : 'Set due date'}
      aria-keyshortcuts="D"
      onClick={() => setPicker('due')}
    >
      {task.due_on ? (
        <DueText dueOn={task.due_on} dueAt={task.due_at} startOn={task.start_on} done={done} />
      ) : (
        <Placeholder icon={CalendarDays} show={canEdit} />
      )}
    </Cell>
  );
  const detailsButton = onOpen ? (
    <button
      type="button"
      aria-label={`Open details for ${task.title}`}
      title="Open details (Space)"
      onClick={() => onOpen(task)}
      className="grid h-7 w-7 shrink-0 place-items-center rounded-md text-muted opacity-0 group-hover/row:opacity-100 hover:bg-surface hover:text-ink focus-visible:opacity-100 @max-md:opacity-100 [@media(hover:none)]:opacity-100"
    >
      <Icon icon={PanelRightOpen} size={15} />
    </button>
  ) : null;
  const menuButton = (
    <button
      type="button"
      aria-label={`Actions for ${task.title}`}
      aria-haspopup="menu"
      onClick={() => setMenuOpen(true)}
      className="grid h-7 w-7 shrink-0 place-items-center rounded-md text-muted opacity-0 group-hover/row:opacity-100 @max-md:hidden hover:bg-surface hover:text-ink focus-visible:opacity-100 data-[state=open]:opacity-100"
    >
      <Icon icon={MoreHorizontal} size={15} />
    </button>
  );

  return (
    // Rows are keyboard targets (A/M/D/Enter); S1.2.4 adds roving focus + selection.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <div
      ref={setRefs}
      role="listitem"
      aria-label={task.title}
      data-selected={selected || undefined}
      data-task-id={task.id}
      data-open={isOpen || undefined}
      data-section-id={task.section_id}
      onPointerDown={onPointerDown}
      onClickCapture={onClickCapture}
      onClick={(e) => {
        // a click on the row itself (not a control inside it) opens the details pane
        if (!e.shiftKey && !e.metaKey && !e.ctrlKey && !(e.target as HTMLElement).closest(INTERACTIVE))
          onOpen?.(task);
      }}
      onFocus={(e) => e.target === e.currentTarget && onFocusRow?.(task)}
      // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
      tabIndex={0}
      onKeyDown={onRowKey}
      className={cn(
        'group/row relative flex h-9 items-center gap-2.5 border-b border-hair-soft px-2 transition-opacity duration-300 outline-none hover:bg-surface-2 focus-visible:bg-surface-2 focus-visible:shadow-[inset_2px_0_0_var(--focus)]',
        (done || fading) && 'text-muted',
        fading && 'opacity-60',
        selected && 'bg-selection hover:bg-selection focus-visible:bg-selection',
        isOpen && !selected && 'bg-accent-tint hover:bg-accent-tint',
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
      {/* The name button fits its text: the rest of the row is a click target for the pane. */}
      <div className="flex min-w-0 flex-1 items-center">
        {editing ? (
          <input
            ref={input}
            aria-label="Task name"
            value={draft}
            maxLength={500}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={commit}
            onKeyDown={onKey}
            className="h-7 w-full min-w-0 rounded-sm border border-focus bg-surface px-1 text-[13.5px] outline-none"
          />
        ) : (
          <button
            type="button"
            disabled={!canEdit}
            onClick={() => setEditing(true)}
            className={cn(
              'max-w-full min-w-0 cursor-text truncate rounded-sm px-0.5 text-left text-[13.5px] hover:ring-1 hover:ring-hairline disabled:cursor-default disabled:hover:ring-0',
              done && 'line-through decoration-muted-2',
            )}
          >
            {task.title}
          </button>
        )}
        {task.subtask_count ? (
          <button
            type="button"
            aria-expanded={onToggleExpand ? expanded : undefined}
            aria-label={`${task.completed_subtask_count} of ${task.subtask_count} subtasks done${onToggleExpand ? (expanded ? ', hide' : ', show') : ''}`}
            onClick={() => (onToggleExpand ? onToggleExpand(task) : onOpen?.(task))}
            className="tabular ml-2 flex h-6 shrink-0 items-center gap-0.5 rounded px-1 text-xs text-muted hover:bg-surface hover:text-ink"
          >
            ↳ {task.completed_subtask_count}/{task.subtask_count}
          </button>
        ) : null}
      </div>
      {project ? (
        <span className="flex w-40 shrink-0 items-center gap-1.5 truncate text-xs text-muted @max-3xl:w-24 @max-md:hidden">
          <span
            aria-hidden
            className="h-2 w-2 shrink-0 rounded-sm"
            style={{ background: project.color ? `var(--${project.color})` : 'var(--muted-2)' }}
          />
          <span className="truncate">{project.name}</span>
        </span>
      ) : null}
      <span className="w-14 shrink-0 text-right font-mono text-[11px] text-muted-2 opacity-0 group-hover/row:opacity-100 @max-3xl:hidden">
        {isTemp(task.id) ? '…' : task.key}
      </span>
      {/* Pickers and the menu mount only while open: most rows never open them, and each
          Radix root costs real time when hundreds of rows mount while scrolling. */}
      {hideAssignee ? null : picker === 'assignee' ? (
        <AssigneePicker
          open
          onOpenChange={(o) => !o && closePicker(false)}
          assigneeId={task.assignee_id}
          onChange={(u) => assign(u?.id ?? null, u?.id === meId ? 'you' : u?.name)}
        >
          {assigneeCell}
        </AssigneePicker>
      ) : (
        assigneeCell
      )}
      {/* (assignee hidden in My Tasks: it's always you) */}
      {picker === 'due' ? (
        <DatePicker
          open
          onOpenChange={(o) => !o && closePicker(false)}
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
          {dueCell}
        </DatePicker>
      ) : (
        dueCell
      )}
      {fields?.length ? (
        <span className="flex min-w-0 shrink flex-wrap items-center gap-1 @max-3xl:hidden">
          {fields.map((f) => (
            <FieldValueChip key={f.field.id} field={f.field} value={fieldValues?.get(f.field.id) ?? null} />
          ))}
        </span>
      ) : null}
      {detailsButton}
      {canEdit ? (
        menuOpen ? (
          <DropdownMenu open onOpenChange={setMenuOpen}>
            <DropdownMenuTrigger asChild>{menuButton}</DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem className="text-crit" onSelect={() => onDelete(task)}>
                <Icon icon={Trash2} /> Delete task
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        ) : (
          menuButton
        )
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
  onTab,
  onShiftTab,
  placeholder = 'Write a task name',
  initialValue = '',
}: {
  onSubmit: (title: string) => void;
  onPasteLines: (lines: string[]) => void;
  onCancel: () => void;
  /** Tab: make this new row a subtask of the task above (list). */
  onTab?: (title: string) => void;
  /** Shift+Tab: turn a new subtask row back into a task row. */
  onShiftTab?: (title: string) => void;
  placeholder?: string;
  initialValue?: string;
}) {
  const [value, setValue] = useState(initialValue);
  // Tab/Shift+Tab hand the row over to another list: don't treat the blur as "submit".
  const handedOver = useRef(false);
  return (
    <div
      role="listitem"
      aria-label="New task"
      className="flex h-9 items-center gap-2.5 border-b border-hair-soft px-2"
    >
      <CompleteCheck checked={false} disabled label="New task" onChange={() => {}} />
      <input
        aria-label="New task name"
        placeholder={placeholder}
        value={value}
        maxLength={500}
        // eslint-disable-next-line jsx-a11y/no-autofocus -- the user just asked for a new task row
        autoFocus
        onChange={(e) => setValue(e.target.value)}
        onBlur={() => {
          if (handedOver.current) return;
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
          } else if (e.key === 'Tab' && !e.shiftKey && onTab) {
            e.preventDefault();
            handedOver.current = true;
            onTab(value.trim());
          } else if (e.key === 'Tab' && e.shiftKey && onShiftTab) {
            e.preventDefault();
            handedOver.current = true;
            onShiftTab(value.trim());
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
