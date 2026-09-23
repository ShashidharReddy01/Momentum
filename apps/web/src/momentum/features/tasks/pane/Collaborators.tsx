import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Bell, BellOff, Plus, UserMinus } from 'lucide-react';
import { Avatar } from '@/components/ui/Avatar';
import { Button } from '@/components/ui/Button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu';
import { Icon } from '@/components/ui/Icon';
import { useMe } from '@/features/auth';
import { PeoplePicker, usePeople } from '@/features/people';
import { toastError } from '@/lib/toast';
import { useUndoToast } from '@/lib/undo';
import { useApi } from '@/providers/api';
import type { TaskDetail } from '../detail';
import { taskKeys } from '../queries';

const MAX_SHOWN = 8;

/** Who follows the task (gets its updates): join/leave, add or remove collaborators. */
export function Collaborators({ task }: { task: TaskDetail }) {
  const api = useApi();
  const qc = useQueryClient();
  const undoToast = useUndoToast();
  const people = usePeople().data ?? [];
  const meId = useMe().data?.user.id;
  const role = task.my_role;
  const canComment = role === 'admin' || role === 'editor' || role === 'commenter';
  const canManage = role === 'admin' || role === 'editor';
  const followers = task.followers ?? [];
  const following = !!meId && followers.includes(meId);
  const key = taskKeys.detail(task.id);

  const change = useMutation({
    mutationFn: async (v: { userId: string; follow: boolean }) =>
      v.follow
        ? (
            await api.POST('/api/v1/tasks/{task_id}/followers', {
              params: { path: { task_id: task.id } },
              body: { user_id: v.userId },
            })
          ).data!
        : (
            await api.DELETE('/api/v1/tasks/{task_id}/followers/{user_id}', {
              params: { path: { task_id: task.id, user_id: v.userId } },
            })
          ).data!,
    onMutate: (v) =>
      qc.setQueryData<TaskDetail>(key, (old) =>
        old
          ? {
              ...old,
              followers: v.follow
                ? [...new Set([...(old.followers ?? []), v.userId])]
                : (old.followers ?? []).filter((f) => f !== v.userId),
            }
          : old,
      ),
    onSuccess: (res, v) => {
      qc.setQueryData<TaskDetail>(key, (old) => (old ? { ...old, followers: res.data.followers } : old));
      const who = v.userId === meId ? 'You' : (people.find((p) => p.id === v.userId)?.name ?? 'They');
      const message = v.follow
        ? `${who} will get updates on this task`
        : `${who} won't get updates on this task`;
      undoToast(message, res.meta, () => void qc.invalidateQueries({ queryKey: key }));
    },
    onError: (e) => {
      toastError(e);
      void qc.invalidateQueries({ queryKey: key });
    },
  });

  const shown = followers.slice(0, MAX_SHOWN);
  const extra = followers.length - shown.length;
  return (
    <section
      aria-label="Collaborators"
      className="mt-8 flex flex-wrap items-center gap-2 border-t border-hair-soft pt-3"
    >
      <span className="text-xs text-muted">Collaborators</span>
      <ul className="flex items-center -space-x-1.5">
        {shown.map((id) => {
          const person = people.find((p) => p.id === id);
          const name = person?.name ?? 'Someone';
          const removable = canManage || id === meId;
          return (
            <li key={id}>
              {removable ? (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <button type="button" aria-label={name} className="rounded-full ring-2 ring-surface">
                      <Avatar name={name} src={person?.avatar_url} size={24} />
                    </button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="start">
                    <DropdownMenuItem onSelect={() => change.mutate({ userId: id, follow: false })}>
                      <Icon icon={UserMinus} /> {id === meId ? 'Stop following' : `Remove ${name}`}
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              ) : (
                <span className="inline-flex rounded-full ring-2 ring-surface">
                  <Avatar name={name} src={person?.avatar_url} size={24} />
                </span>
              )}
            </li>
          );
        })}
      </ul>
      {extra > 0 ? <span className="tabular text-xs text-muted">+{extra}</span> : null}
      {canManage ? (
        <PeoplePicker
          exclude={followers}
          placeholder="Add a collaborator…"
          onSelect={(p) => change.mutate({ userId: p.id, follow: true })}
        >
          <button
            type="button"
            aria-label="Add collaborator"
            className="grid h-6 w-6 place-items-center rounded-full border border-dashed border-muted-2 text-muted hover:text-ink"
          >
            <Icon icon={Plus} size={13} />
          </button>
        </PeoplePicker>
      ) : null}
      <span className="flex-1" />
      {canComment && meId ? (
        <Button size="sm" variant="text" onClick={() => change.mutate({ userId: meId, follow: !following })}>
          <Icon icon={following ? BellOff : Bell} /> {following ? 'Stop following' : 'Follow task'}
        </Button>
      ) : null}
    </section>
  );
}
