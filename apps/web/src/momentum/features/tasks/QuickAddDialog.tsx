import { useMutation, useQueryClient } from '@tanstack/react-query';
import { CalendarDays, UserRound } from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { useLocation } from 'react-router';
import { DueText } from '@/components/common/DueText';
import { Avatar } from '@/components/ui/Avatar';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { Icon } from '@/components/ui/Icon';
import { useMe } from '@/features/auth';
import { usePeople } from '@/features/people';
import { useProjects } from '@/features/projects';
import type { DueValue } from '@/lib/dates';
import { toastError } from '@/lib/toast';
import { useUndoToast } from '@/lib/undo';
import { useApi } from '@/providers/api';
import { AssigneePicker } from './AssigneePicker';
import { DatePicker } from './DatePicker';

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

  const create = useMutation({
    mutationFn: async () =>
      (
        await api.POST('/api/v1/projects/{project_id}/tasks', {
          params: { path: { project_id: projectId } },
          body: {
            title: title.trim(),
            assignee_id: assignee?.id ?? null,
            due_on: due?.at ? null : (due?.date ?? null),
            due_at: due?.at ?? null,
          },
        })
      ).data!,
    onSuccess: (res) => {
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
    if (!title.trim() || !projectId || create.isPending) return;
    create.mutate();
  };

  const assigneeName =
    assignee && assignee.id === me?.id
      ? 'Me'
      : (people?.find((p) => p.id === assignee?.id)?.name ?? assignee?.name ?? null);

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
            onChange={(e) => setTitle(e.target.value)}
            className="h-10 w-full rounded-md border border-hairline bg-surface px-3 text-[15px] outline-none placeholder:text-muted-2 focus:border-focus"
          />
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <label htmlFor="quick-add-project" className="sr-only">
              Project
            </label>
            <select
              id="quick-add-project"
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
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
              assigneeId={assignee?.id ?? null}
              onChange={(u) => {
                setAssignee(u && u.id === me?.id ? { id: me.id, name: me.name } : u);
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
              dueOn={due?.date ?? null}
              dueAt={due?.at ?? null}
              allowClear
              onChange={(v) => {
                setDue(v);
                input.current?.focus();
              }}
            >
              <button
                type="button"
                aria-label={due ? 'Change due date' : 'Set due date'}
                className="flex h-8 items-center gap-1.5 rounded-md border border-hairline px-2 hover:bg-surface-2"
              >
                <Icon icon={CalendarDays} className="text-muted" />
                {due ? (
                  <DueText dueOn={due.date} dueAt={due.at} />
                ) : (
                  <span className="text-muted">Due date</span>
                )}
              </button>
            </DatePicker>
          </div>
          <div className="flex justify-end gap-2">
            <Button onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button
              type="submit"
              variant="primary"
              loading={create.isPending}
              disabled={!title.trim() || !projectId}
            >
              Add task
            </Button>
          </div>
        </form>
      )}
    </Dialog>
  );
}
