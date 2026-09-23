import type { JSONContent } from '@tiptap/react';
import {
  CalendarDays,
  Check,
  CornerLeftUp,
  CircleCheck,
  Copy,
  Maximize2,
  MoreHorizontal,
  Trash2,
  UserRound,
  X,
} from 'lucide-react';
import { lazy, Suspense, useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { Link } from 'react-router';
import { toast } from 'sonner';
import { DueText } from '@/components/common/DueText';
import { ErrorState } from '@/components/common/States';
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
import { IconButton } from '@/components/ui/IconButton';
import { Skeleton } from '@/components/ui/Skeleton';
import { useMe } from '@/features/auth';
import { usePeople } from '@/features/people';
import { isNotFound } from '@/lib/api/errors';
import { cn } from '@/lib/cn';
import { useMomentumConfig } from '@/lib/config';
import { formatDay, formatDue } from '@/lib/dates';
import { AssigneePicker } from '../AssigneePicker';
import { DatePicker } from '../DatePicker';
import { useTaskDetail, useTaskDetailMutations, type TaskDetail } from '../detail';
import { SubtaskList } from '../SubtaskList';
import { Collaborators } from './Collaborators';
// the comment editor (Tiptap) loads with the pane, not the app
const Comments = lazy(() => import('./Comments').then((m) => ({ default: m.Comments })));
import { useDescriptionAutosave, type SaveState } from './useDescriptionAutosave';

const EDITABLE = 'input, textarea, [contenteditable="true"]';
// The editor (Tiptap/ProseMirror) is the heaviest dependency: load it with the first pane.
const RichTextEditor = lazy(() =>
  import('@/components/editor/RichTextEditor').then((m) => ({ default: m.RichTextEditor })),
);

/** Task details: in a side pane next to a list, or as a full page (`/task/:id`). */
export function TaskPane({
  taskId,
  mode = 'pane',
  onClose,
  onStep,
  onOpenTask,
  canEditHint,
}: {
  taskId: string;
  mode?: 'pane' | 'page';
  onClose?: () => void;
  onStep?: (dir: 1 | -1) => void;
  /** Open another task in the same place (a subtask or the parent). */
  onOpenTask?: (id: string) => void;
  /** Whether the viewer may edit (from the project they're looking at). */
  canEditHint?: boolean;
}) {
  const detail = useTaskDetail(taskId);
  const root = useRef<HTMLElement>(null);

  const onKeyDown = (e: KeyboardEvent<HTMLElement>) => {
    const target = e.target as HTMLElement;
    const inField = !!target.closest(EDITABLE);
    if (e.key === 'Escape') {
      if (target.closest('[role="dialog"], [role="menu"], [data-radix-popper-content-wrapper]')) return;
      e.preventDefault();
      if (inField) root.current?.focus();
      else onClose?.();
      return;
    }
    if (inField || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === 'j' || e.key === 'k') {
      e.preventDefault();
      onStep?.(e.key === 'j' ? 1 : -1);
    }
  };

  return (
    // Pane-level shortcuts (Esc, J/K) are delegated from its controls.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <aside
      ref={root}
      tabIndex={-1}
      aria-label="Task details"
      onKeyDown={onKeyDown}
      className={cn(
        'flex min-h-0 flex-col bg-surface outline-none',
        mode === 'pane'
          ? 'h-full w-[var(--pane-w)] shrink-0 border-l border-hairline shadow-[var(--shadow-pane)] max-md:fixed max-md:inset-0 max-md:z-30 max-md:w-full max-md:border-l-0'
          : 'mx-auto w-full max-w-3xl',
      )}
    >
      {detail.isPending ? (
        <div className="flex flex-col gap-4 p-6" aria-busy>
          <Skeleton className="h-8 w-3/4" />
          <Skeleton className="h-5 w-1/2" />
          <Skeleton className="h-32" />
        </div>
      ) : detail.isError ? (
        <div className="p-6">
          {isNotFound(detail.error) ? (
            <p className="text-sm text-muted">This task was deleted, or you don't have access to it.</p>
          ) : (
            <ErrorState error={detail.error} onRetry={() => void detail.refetch()} />
          )}
          {onClose ? (
            <Button size="sm" className="mt-3" onClick={onClose}>
              Close
            </Button>
          ) : null}
        </div>
      ) : (
        <PaneBody
          key={detail.data.id}
          task={detail.data}
          mode={mode}
          onClose={onClose}
          onOpenTask={onOpenTask}
          canEdit={
            (detail.data.my_role === 'admin' || detail.data.my_role === 'editor') && (canEditHint ?? true)
          }
        />
      )}
    </aside>
  );
}

function PaneBody({
  task,
  mode,
  onClose,
  onOpenTask,
  canEdit,
}: {
  task: TaskDetail;
  mode: 'pane' | 'page';
  onClose?: () => void;
  onOpenTask?: (id: string) => void;
  canEdit: boolean;
}) {
  const m = useTaskDetailMutations(task.id);
  const config = useMomentumConfig();
  const people = usePeople().data;
  const meId = useMe().data?.user.id;
  const nameOf = (id: string | null | undefined) => (id ? people?.find((p) => p.id === id)?.name : undefined);
  const assignee = people?.find((p) => p.id === task.assignee_id);
  const [picker, setPicker] = useState<'assignee' | 'due' | 'start' | null>(null);
  const done = !!task.completed_at;
  const link = `${window.location.origin}${config.base_path}/task/${task.id}`;

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(link);
      toast.success('Link copied');
    } catch {
      toast(link);
    }
  };

  return (
    <>
      <div className="flex h-12 shrink-0 items-center gap-1 border-b border-hair-soft px-4">
        <Button
          size="sm"
          variant={done ? 'ghost' : 'text'}
          disabled={!canEdit}
          aria-pressed={done}
          onClick={() => m.setCompleted.mutate(!done)}
          className={cn('border border-hairline', done && 'border-ok text-ok')}
        >
          <Icon icon={done ? CircleCheck : Check} /> {done ? 'Completed' : 'Mark complete'}
        </Button>
        <span className="flex-1" />
        <span className="mr-1 font-mono text-[11px] text-muted-2">{task.key}</span>
        <IconButton icon={Copy} label="Copy task link" size="icon-sm" onClick={() => void copyLink()} />
        {mode === 'pane' ? (
          <Link
            to={`/task/${task.id}`}
            aria-label="Open full page"
            title="Open full page"
            className="grid h-7 w-7 place-items-center rounded-md text-muted hover:bg-surface-2 hover:text-ink"
          >
            <Icon icon={Maximize2} size={15} />
          </Link>
        ) : null}
        {canEdit ? (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <IconButton icon={MoreHorizontal} label="More actions" size="icon-sm" />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => void copyLink()}>
                <Icon icon={Copy} /> Copy link
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                className="text-crit"
                onSelect={() => {
                  m.remove.mutate();
                  onClose?.();
                }}
              >
                <Icon icon={Trash2} /> Delete task
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        ) : null}
        {onClose ? (
          <IconButton icon={X} label="Close details" shortcut="Esc" size="icon-sm" onClick={onClose} />
        ) : null}
      </div>

      <div className="min-h-0 flex-1 overflow-auto px-6 py-5">
        {task.parent ? (
          <button
            type="button"
            onClick={() => onOpenTask?.(task.parent!.id)}
            className="mb-1 flex max-w-full items-center gap-1 truncate rounded px-2 text-xs text-muted hover:text-ink"
          >
            <Icon icon={CornerLeftUp} size={13} /> Subtask of{' '}
            <span className="truncate font-medium">{task.parent.name}</span>
          </button>
        ) : null}
        <TitleField task={task} canEdit={canEdit} onSave={(title) => m.update.mutate({ patch: { title } })} />

        <dl className="mt-4 grid grid-cols-[112px_1fr] items-center gap-x-3 gap-y-1 text-sm">
          <Field label="Assignee">
            <AssigneePicker
              open={picker === 'assignee'}
              onOpenChange={(o) => setPicker(o ? 'assignee' : null)}
              assigneeId={task.assignee_id}
              onChange={(u) =>
                m.update.mutate({
                  patch: { assignee_id: u?.id ?? null },
                  message: u ? `Assigned to ${u.id === meId ? 'you' : u.name}` : 'Unassigned',
                })
              }
            >
              <FieldButton disabled={!canEdit} label={assignee ? `Assignee: ${assignee.name}` : 'Assign'}>
                {assignee ? (
                  <>
                    <Avatar name={assignee.name} src={assignee.avatar_url} size={22} /> {assignee.name}
                  </>
                ) : (
                  <span className="flex items-center gap-2 text-muted">
                    <Icon icon={UserRound} size={15} /> No assignee
                  </span>
                )}
              </FieldButton>
            </AssigneePicker>
          </Field>
          <Field label="Due date">
            <DatePicker
              open={picker === 'due'}
              onOpenChange={(o) => setPicker(o ? 'due' : null)}
              dueOn={task.due_on}
              dueAt={task.due_at}
              onChange={(v) => {
                if (v && task.start_on && v.date < task.start_on) {
                  toast.error('The due date must be on or after the start date');
                  return;
                }
                m.update.mutate({
                  patch: v ? { due_on: v.date, due_at: v.at } : { due_on: null, due_at: null },
                  message: v ? `Due date set: ${formatDue(v.date, v.at)}` : 'Due date removed',
                });
              }}
            >
              <FieldButton
                disabled={!canEdit}
                label={task.due_on ? `Due ${formatDue(task.due_on, task.due_at)}` : 'Set due date'}
              >
                {task.due_on ? (
                  <DueText dueOn={task.due_on} dueAt={task.due_at} done={done} className="text-sm" />
                ) : (
                  <span className="flex items-center gap-2 text-muted">
                    <Icon icon={CalendarDays} size={15} /> No due date
                  </span>
                )}
              </FieldButton>
            </DatePicker>
          </Field>
          <Field label="Start date">
            <DatePicker
              open={picker === 'start'}
              onOpenChange={(o) => setPicker(o ? 'start' : null)}
              dueOn={task.start_on}
              dueAt={null}
              onChange={(v) => {
                if (v && task.due_on && v.date > task.due_on) {
                  toast.error('The start date must be on or before the due date');
                  return;
                }
                m.update.mutate({
                  patch: { start_on: v?.date ?? null },
                  message: v ? `Start date set: ${formatDay(v.date)}` : 'Start date removed',
                });
              }}
            >
              <FieldButton
                disabled={!canEdit}
                label={task.start_on ? `Starts ${formatDay(task.start_on)}` : 'Set start date'}
              >
                {task.start_on ? (
                  <span className="tabular">{formatDay(task.start_on)}</span>
                ) : (
                  <span className="text-muted">No start date</span>
                )}
              </FieldButton>
            </DatePicker>
          </Field>
          {task.project ? (
            <Field label="Project">
              <span className="flex h-8 items-center gap-2 px-2">
                <span
                  aria-hidden
                  className="h-2.5 w-2.5 rounded-sm"
                  style={{
                    background: task.project.color ? `var(--${task.project.color})` : 'var(--muted-2)',
                  }}
                />
                <Link to={`/projects/${task.project.id}`} className="hover:underline">
                  {task.project.name}
                </Link>
                {task.section ? <span className="text-muted">· {task.section.name}</span> : null}
              </span>
            </Field>
          ) : null}
        </dl>

        <Description task={task} canEdit={canEdit} />

        <SubtaskList
          key={task.id}
          parentId={task.id}
          canEdit={canEdit}
          onOpen={onOpenTask ? (sub) => onOpenTask(sub.id) : undefined}
        />

        <Suspense fallback={<Skeleton className="mt-8 h-24" />}>
          <Comments task={task} />
        </Suspense>
        <Collaborators task={task} />
        <p className="mt-3 text-xs text-muted">
          Created by {nameOf(task.created_by) ?? 'someone'} · {formatDay(task.created_at.slice(0, 10))}
          {task.completed_at ? ` · Completed ${formatDay(task.completed_at.slice(0, 10))}` : ''}
        </p>
      </div>
    </>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0">{children}</dd>
    </>
  );
}

const FieldButton = ({
  label,
  disabled,
  children,
  ...props
}: { label: string; disabled?: boolean; children: ReactNode } & React.ComponentProps<'button'>) => (
  <button
    type="button"
    aria-label={label}
    disabled={disabled}
    className="flex h-8 max-w-full items-center gap-2 truncate rounded-md px-2 text-left hover:bg-surface-2 disabled:pointer-events-none data-[state=open]:bg-surface-2"
    {...props}
  >
    {children}
  </button>
);

function TitleField({
  task,
  canEdit,
  onSave,
}: {
  task: TaskDetail;
  canEdit: boolean;
  onSave: (t: string) => void;
}) {
  const [value, setValue] = useState(task.title);
  const [editing, setEditing] = useState(false);
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    if (!editing) setValue(task.title);
  }, [task.title, editing]);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = '0px';
    el.style.height = `${el.scrollHeight}px`;
  }, [value]);
  const commit = () => {
    setEditing(false);
    const t = value.replace(/\s+/g, ' ').trim();
    if (!t) setValue(task.title);
    else if (t !== task.title) onSave(t);
  };
  return (
    <textarea
      ref={ref}
      aria-label="Task name"
      value={value}
      rows={1}
      maxLength={500}
      readOnly={!canEdit}
      onFocus={() => setEditing(true)}
      onChange={(e) => setValue(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          e.currentTarget.blur();
        } else if (e.key === 'Escape') {
          e.preventDefault();
          e.stopPropagation();
          setValue(task.title);
          setEditing(false);
          requestAnimationFrame(() => ref.current?.blur());
        }
      }}
      className={cn(
        'w-full resize-none overflow-hidden rounded-md bg-transparent px-2 py-1 text-[20px] leading-snug font-semibold outline-none',
        canEdit && 'hover:bg-surface-2 focus:bg-surface-2',
        task.completed_at && 'text-muted line-through',
      )}
    />
  );
}

const SAVE_LABEL: Record<SaveState, string> = {
  saved: '',
  dirty: 'Editing…',
  saving: 'Saving…',
  offline: "Offline. Kept on this device; we'll keep trying.",
  'signed-out': 'Signed out. Kept on this device; it saves after you sign in.',
  conflict: '',
  error: "Couldn't save. Kept on this device.",
};

function docText(doc: JSONContent | null): string {
  if (!doc) return '';
  const parts: string[] = [];
  const walk = (n: JSONContent) => {
    if (n.text) parts.push(n.text);
    n.content?.forEach(walk);
    if (n.type && ['paragraph', 'heading', 'listItem', 'taskItem', 'codeBlock'].includes(n.type))
      parts.push('\n');
  };
  walk(doc);
  return parts
    .join('')
    .replace(/\n{2,}/g, '\n')
    .trim();
}

function Description({ task, canEdit }: { task: TaskDetail; canEdit: boolean }) {
  const d = useDescriptionAutosave(task, canEdit);
  const label = SAVE_LABEL[d.state];
  return (
    <section aria-label="Description" className="mt-6">
      <div className="mb-1 flex items-center gap-2">
        <h3 className="section-label">Description</h3>
        <span
          role="status"
          aria-live="polite"
          className={cn(
            'text-xs',
            d.state === 'offline' || d.state === 'signed-out' || d.state === 'error'
              ? 'text-warn'
              : 'text-muted-2',
          )}
        >
          {label}
        </span>
      </div>
      {d.conflict ? (
        <div role="alert" className="mb-2 rounded-md border border-warn bg-warn-tint p-3 text-sm">
          <p className="font-medium">Someone else changed this description while you were editing.</p>
          <p className="mt-1 text-xs text-ink-2">
            Your version is in the editor below (and kept on this device). Their version:
          </p>
          <blockquote className="mt-1 max-h-32 overflow-auto rounded bg-surface p-2 text-xs whitespace-pre-wrap text-ink-2">
            {docText(d.conflict.theirs) || '(empty)'}
          </blockquote>
          <div className="mt-2 flex flex-wrap gap-2">
            <Button size="sm" variant="primary" onClick={d.keepMine}>
              Keep mine
            </Button>
            <Button size="sm" onClick={d.useTheirs}>
              Use theirs
            </Button>
            <Button
              size="sm"
              variant="text"
              onClick={() =>
                void navigator.clipboard
                  .writeText(docText(d.mine()))
                  .then(() => toast.success('Your text is copied'))
                  .catch(() => undefined)
              }
            >
              Copy my text
            </Button>
          </div>
        </div>
      ) : null}
      <Suspense fallback={<Skeleton className="h-24" />}>
        <RichTextEditor
          content={d.content.doc}
          revision={d.content.revision}
          editable={canEdit}
          label="Task description"
          placeholder={canEdit ? 'What is this task about? Markdown paste works too.' : 'No description'}
          onChange={d.onChange}
          onBlur={() => void d.flush()}
          className="-mx-2 px-2 py-1 focus-within:bg-surface-2/40 hover:bg-surface-2/40"
        />
      </Suspense>
    </section>
  );
}
