import { useMutation, useQueryClient } from '@tanstack/react-query';
import { CalendarDays, Repeat, UserRound, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { useLocation } from 'react-router';
import { AIBadge } from '@/components/common/AI';
import { DueText } from '@/components/common/DueText';
import { Avatar } from '@/components/ui/Avatar';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { Icon } from '@/components/ui/Icon';
import { useMe } from '@/features/auth';
import { usePeople } from '@/features/people';
import { useProjects } from '@/features/projects';
import type { components } from '@/lib/api/schema';
import { useMomentumConfig } from '@/lib/config';
import type { DueValue } from '@/lib/dates';
import { toastError } from '@/lib/toast';
import { useUndoToast } from '@/lib/undo';
import { useApi } from '@/providers/api';
import { AssigneePicker } from './AssigneePicker';
import { DatePicker } from './DatePicker';
import { looksLikeMoreDetail, parseQuickAdd, type Priority, type Recurrence } from './quickAddParse';

type MoParse = components['schemas']['QuickAddParseOut'];
type Fields = {
  title: string;
  assignee: { id: string; name: string } | null;
  projectId: string | null;
  due: DueValue | null;
  priority: Priority | null;
  recurrence: RepeatRule | null;
};
type RepeatRule = Omit<Recurrence, 'by_weekday' | 'text'> & {
  by_weekday?: number[] | null;
  text?: string | null;
};
const PRIORITY_LABEL: Record<Priority, string> = {
  urgent: 'Urgent',
  high: 'High',
  medium: 'Medium',
  low: 'Low',
};
const DAY = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

function repeatLabel(r: RepeatRule): string {
  if (r.text) return r.text;
  const every = r.interval > 1 ? `every ${r.interval} ` : 'every ';
  if (r.workdays_only) return 'every weekday';
  if (r.by_weekday?.length) return `${every}${r.by_weekday.map((d) => DAY[d]).join(', ')}`;
  const unit = { daily: 'day', weekly: 'week', monthly: 'month', yearly: 'year' }[r.freq];
  return r.interval > 1 ? `${every}${unit}s` : `every ${unit}`;
}

const LAST_PROJECT = 'momentum.quickadd.project';

function readLast(): string | null {
  try {
    return localStorage.getItem(LAST_PROJECT);
  } catch {
    return null;
  }
}

/**
 * Quick add (Create → Task, or `Q` anywhere): name, project, assignee (you by default) and due
 * date, created in one step with undo. Defaults to the project you're looking at, else the
 * last one you used.
 *
 * S3.2.1 smart quick-add: the name is parsed as you type (`Review deck @ana friday #website
 * !high every monday`): recognized tokens leave the name and set the fields; anything picked by
 * hand wins over what was typed. If the rest still reads like details ("for Ana by end of next
 * week"), "✦ Let Mo fill in the details" asks the AI half; its result is shown, marked as Mo's,
 * and nothing is created until you add the task.
 */
export function QuickAddDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const api = useApi();
  const qc = useQueryClient();
  const undoToast = useUndoToast();
  const me = useMe().data?.user;
  const people = usePeople().data;
  const projects = useProjects();
  // the project on screen (list or task page of a project), if any
  const routeProject = /^\/projects\/([^/?#]+)/.exec(useLocation().pathname)?.[1];
  const editable = useMemo(
    () => (projects.data ?? []).filter((p) => p.my_role === 'admin' || p.my_role === 'editor'),
    [projects.data],
  );

  const [title, setTitle] = useState('');
  const [projectId, setProjectId] = useState('');
  const [assignee, setAssignee] = useState<{ id: string; name: string } | null>(null);
  const [due, setDue] = useState<DueValue | null>(null);
  const [picker, setPicker] = useState<'assignee' | 'due' | null>(null);
  const [touched, setTouched] = useState<{ assignee?: boolean; due?: boolean; project?: boolean }>({});
  const [dismissed, setDismissed] = useState<{ priority?: boolean; recurrence?: boolean }>({});
  const [mo, setMo] = useState<MoParse | null>(null);
  const aiEnabled = useMomentumConfig().ai_enabled;
  const input = useRef<HTMLInputElement>(null);

  // fresh form each time it opens
  useEffect(() => {
    if (!open) {
      setProjectId('');
      return;
    }
    setTitle('');
    setDue(null);
    setPicker(null);
    setTouched({});
    setDismissed({});
    setMo(null);
    setAssignee(me ? { id: me.id, name: me.name } : null);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only on open
  }, [open]);
  // default project: the one on screen, else the last used, else the first (also once the
  // project list arrives after opening); never overrides a choice already made
  useEffect(() => {
    if (!open || !editable.length) return;
    setProjectId((current) => {
      const ids = new Set(editable.map((p) => p.id));
      if (current && ids.has(current)) return current;
      const last = readLast();
      if (routeProject && ids.has(routeProject)) return routeProject;
      if (last && ids.has(last)) return last;
      return editable[0]!.id;
    });
  }, [open, editable, routeProject]);

  const parsed = useMemo(
    () =>
      parseQuickAdd(title, {
        people: (people ?? []).map((p) => ({ id: p.id, name: p.name, email: p.email })),
        projects: editable.map((p) => ({ id: p.id, name: p.name })),
        me: me ? { id: me.id, name: me.name, email: me.email } : null,
      }),
    [title, people, editable, me],
  );
  // what will be created: a hand-picked value, else Mo's reading, else the parsed token, else
  // the default
  const moProject = mo?.project && editable.some((p) => p.id === mo.project!.id) ? mo.project.id : null;
  const fields: Fields = {
    title: mo?.title ?? parsed.title,
    assignee: touched.assignee ? assignee : (mo?.assignee ?? parsed.assignee ?? assignee),
    projectId: touched.project ? projectId : (moProject ?? parsed.project?.id ?? projectId),
    due: touched.due ? due : mo?.due_on ? { date: mo.due_on, at: null } : (parsed.due ?? due),
    priority: dismissed.priority ? null : (mo?.priority ?? parsed.priority),
    recurrence: dismissed.recurrence ? null : (mo?.recurrence ?? parsed.recurrence),
  };

  const askMo = useMutation({
    mutationFn: async () => (await api.POST('/api/v1/ai/quick-add', { body: { text: title.trim() } })).data!,
    onSuccess: (r) => setMo(r),
    onError: (e) => toastError(e, "Mo couldn't read that; set the details with the buttons below"),
  });

  const create = useMutation({
    mutationFn: async () =>
      (
        await api.POST('/api/v1/projects/{project_id}/tasks', {
          params: { path: { project_id: fields.projectId! } },
          body: {
            title: fields.title,
            assignee_id: fields.assignee?.id ?? null,
            due_on: fields.due?.at ? null : (fields.due?.date ?? null),
            due_at: fields.due?.at ?? null,
            priority: fields.priority,
            recurrence: fields.recurrence
              ? {
                  freq: fields.recurrence.freq,
                  interval: fields.recurrence.interval,
                  by_weekday: fields.recurrence.by_weekday ?? null,
                  workdays_only: fields.recurrence.workdays_only ?? false,
                  text: fields.recurrence.text ?? null,
                }
              : null,
          },
        })
      ).data!,
    onSuccess: (res) => {
      const projectId = fields.projectId!;
      try {
        localStorage.setItem(LAST_PROJECT, projectId);
      } catch {
        /* ignore */
      }
      const refresh = () => {
        void qc.invalidateQueries({ queryKey: ['projects', projectId, 'tasks'] });
        void qc.invalidateQueries({ queryKey: ['me', 'tasks'] });
        void qc.invalidateQueries({ queryKey: ['home'] });
      };
      refresh();
      const name = editable.find((p) => p.id === projectId)?.name;
      undoToast(name ? `Task added to ${name}` : 'Task added', res.meta, refresh);
      onOpenChange(false);
    },
    onError: (e) => toastError(e, "Couldn't add the task"),
  });

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    if (!fields.title || !fields.projectId || create.isPending) return;
    create.mutate();
  };

  const shown = fields.assignee;
  const assigneeName =
    shown && shown.id === me?.id
      ? 'Me'
      : (people?.find((p) => p.id === shown?.id)?.name ?? shown?.name ?? null);
  const canAskMo = aiEnabled && !mo && title.trim().length > 0 && looksLikeMoreDetail(parsed.title);

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="New task">
      {projects.isSuccess && editable.length === 0 ? (
        <p className="p-5 text-sm text-muted">
          You can add tasks once you&apos;re an editor in a project. Create a project, or ask a project admin
          to add you.
        </p>
      ) : (
        <form onSubmit={submit} className="flex flex-col gap-4 p-5">
          <input
            ref={input}
            // eslint-disable-next-line jsx-a11y/no-autofocus -- the dialog exists to type a task name
            autoFocus
            aria-label="Task name"
            placeholder="Task name"
            value={title}
            maxLength={500}
            onChange={(e) => {
              setTitle(e.target.value);
              setMo(null); // Mo's reading was of the old text
            }}
            className="h-10 w-full rounded-md border border-hairline bg-surface px-3 text-[15px] outline-none placeholder:text-muted-2 focus:border-focus"
          />
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <label htmlFor="quick-add-project" className="sr-only">
              Project
            </label>
            <select
              id="quick-add-project"
              value={fields.projectId ?? ''}
              onChange={(e) => {
                setProjectId(e.target.value);
                setTouched((t) => ({ ...t, project: true }));
              }}
              className="h-8 max-w-56 rounded-md border border-hairline bg-surface px-2 text-sm"
            >
              {editable.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            <AssigneePicker
              open={picker === 'assignee'}
              onOpenChange={(o) => setPicker(o ? 'assignee' : null)}
              assigneeId={fields.assignee?.id ?? null}
              onChange={(u) => {
                setAssignee(u && u.id === me?.id ? { id: me.id, name: me.name } : u);
                setTouched((t) => ({ ...t, assignee: true }));
                input.current?.focus();
              }}
            >
              <button
                type="button"
                aria-label={assigneeName ? `Assignee: ${assigneeName}` : 'Assign'}
                className="flex h-8 items-center gap-1.5 rounded-md border border-hairline px-2 hover:bg-surface-2"
              >
                {assigneeName ? (
                  <>
                    <Avatar name={assigneeName === 'Me' ? (me?.name ?? 'Me') : assigneeName} size={18} />
                    {assigneeName}
                  </>
                ) : (
                  <>
                    <Icon icon={UserRound} className="text-muted" /> Unassigned
                  </>
                )}
              </button>
            </AssigneePicker>
            <DatePicker
              open={picker === 'due'}
              onOpenChange={(o) => setPicker(o ? 'due' : null)}
              dueOn={fields.due?.date ?? null}
              dueAt={fields.due?.at ?? null}
              allowClear
              onChange={(v) => {
                setDue(v);
                setTouched((t) => ({ ...t, due: true }));
                input.current?.focus();
              }}
            >
              <button
                type="button"
                aria-label={fields.due ? 'Change due date' : 'Set due date'}
                className="flex h-8 items-center gap-1.5 rounded-md border border-hairline px-2 hover:bg-surface-2"
              >
                <Icon icon={CalendarDays} className="text-muted" />
                {fields.due ? (
                  <DueText dueOn={fields.due.date} dueAt={fields.due.at} />
                ) : (
                  <span className="text-muted">Due date</span>
                )}
              </button>
            </DatePicker>
          </div>
          <SmartLine
            title={title}
            fields={fields}
            unresolved={mo ? (mo.unresolved ?? []) : parsed.unresolved}
            fromMo={Boolean(mo)}
            onDismiss={(k) => setDismissed((d) => ({ ...d, [k]: true }))}
          />
          <div className="flex items-center justify-end gap-2">
            {canAskMo ? (
              <Button
                variant="ai"
                size="sm"
                className="mr-auto"
                loading={askMo.isPending}
                onClick={() => askMo.mutate()}
              >
                ✦ Let Mo fill in the details
              </Button>
            ) : null}
            <Button onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button
              type="submit"
              variant="primary"
              loading={create.isPending}
              disabled={!fields.title || !fields.projectId}
            >
              Add task
            </Button>
          </div>
        </form>
      )}
    </Dialog>
  );
}

/** What typing produced beyond the pickers: the cleaned name, priority and repeat chips (each
 * removable), names that matched nothing, and whether Mo filled this in. */
function SmartLine({
  title,
  fields,
  unresolved,
  fromMo,
  onDismiss,
}: {
  title: string;
  fields: Fields;
  unresolved: string[];
  fromMo: boolean;
  onDismiss: (k: 'priority' | 'recurrence') => void;
}) {
  const renamed = fields.title && fields.title !== title.trim();
  if (!renamed && !fields.priority && !fields.recurrence && !unresolved.length && !fromMo) return null;
  const chip = 'inline-flex h-6 items-center gap-1 rounded-md bg-surface-2 px-1.5 text-[13px]';
  return (
    <div
      role="status"
      aria-label="Understood from the name"
      className="-mt-2 flex flex-wrap items-center gap-2 text-sm"
    >
      {fromMo ? <AIBadge title="Filled in by Mo from what you typed" /> : null}
      {renamed ? (
        <span className="text-muted">
          Creates <span className="text-ink">“{fields.title}”</span>
        </span>
      ) : null}
      {fields.priority ? (
        <span className={chip}>
          Priority: {PRIORITY_LABEL[fields.priority]}
          <button type="button" aria-label="Remove priority" onClick={() => onDismiss('priority')}>
            <Icon icon={X} size={12} />
          </button>
        </span>
      ) : null}
      {fields.recurrence ? (
        <span className={chip}>
          <Icon icon={Repeat} size={12} /> Repeats {repeatLabel(fields.recurrence)}
          <button type="button" aria-label="Remove repeat" onClick={() => onDismiss('recurrence')}>
            <Icon icon={X} size={12} />
          </button>
        </span>
      ) : null}
      {unresolved.map((u) => (
        <span key={u} className="text-[13px] text-warn">
          Couldn&apos;t match {u}
        </span>
      ))}
    </div>
  );
}
