import { Command } from 'cmdk';
import { CircleCheck, Hourglass, Plus, X } from 'lucide-react';
import { useState } from 'react';
import { IconButton } from '@/components/ui/IconButton';
import { Icon } from '@/components/ui/Icon';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/Popover';
import { cn } from '@/lib/cn';
import { useDependencies, useDependencyMutations, useSearchProjectTasks, type TaskSummary } from '../queries';

const ITEM =
  'flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm data-[selected=true]:bg-surface-2';

function AddBlockerCommand({
  projectId,
  taskId,
  exclude,
  onSelect,
}: {
  projectId: string;
  taskId: string;
  exclude: string[];
  onSelect: (t: TaskSummary) => void;
}) {
  const [q, setQ] = useState('');
  const results = useSearchProjectTasks(projectId, q, taskId);
  const options = (results.data ?? []).filter((t) => !exclude.includes(t.id));
  return (
    <Command label="Tasks" loop shouldFilter={false}>
      <Command.Input
        value={q}
        onValueChange={setQ}
        placeholder="Search tasks in this project…"
        className="h-10 w-full border-b border-hair-soft bg-transparent px-3 text-sm outline-none placeholder:text-muted-2"
      />
      <Command.List className="max-h-64 overflow-auto p-1">
        <Command.Empty className="px-3 py-4 text-center text-sm text-muted">
          {results.isPending ? 'Loading…' : 'No tasks found'}
        </Command.Empty>
        {options.map((t) => (
          <Command.Item key={t.id} value={t.id} onSelect={() => onSelect(t)} className={ITEM}>
            <span className={cn('truncate', t.completed_at && 'text-muted line-through')}>{t.title}</span>
          </Command.Item>
        ))}
      </Command.List>
    </Command>
  );
}

function BlockerRow({ task, onRemove }: { task: TaskSummary; onRemove?: () => void }) {
  const done = !!task.completed_at;
  return (
    <li className="flex h-7 items-center gap-1.5 text-sm">
      <Icon icon={done ? CircleCheck : Hourglass} size={13} className={done ? 'text-ok' : 'text-warn'} />
      <span className={cn('min-w-0 flex-1 truncate', done && 'text-muted line-through')}>{task.title}</span>
      {onRemove ? (
        <button
          type="button"
          aria-label={`Remove dependency: ${task.title}`}
          onClick={onRemove}
          className="grid h-5 w-5 shrink-0 place-items-center rounded-sm text-muted opacity-60 hover:bg-surface-2 hover:opacity-100"
        >
          <X size={12} />
        </button>
      ) : null}
    </li>
  );
}

/** Blocked by / blocking (S2.4.2). Only "blocked by" is editable here — removing a "blocking"
 * entry means editing the *other* task's own dependencies, which needs its own pane open. */
export function TaskDependencies({
  taskId,
  projectId,
  canEdit,
}: {
  taskId: string;
  projectId: string | undefined;
  canEdit: boolean;
}) {
  const deps = useDependencies(taskId);
  const m = useDependencyMutations(taskId);
  const [open, setOpen] = useState(false);
  const blockedBy = deps.data?.blocked_by ?? [];
  const blocking = deps.data?.blocking ?? [];

  if (!blockedBy.length && !blocking.length && !canEdit) return null;

  return (
    <section className="mt-6">
      <div className="mb-1 flex items-center gap-2">
        <h3 className="section-label">Blocked by</h3>
        {canEdit && projectId ? (
          <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger asChild>
              <IconButton icon={Plus} label="Add a dependency" size="icon-sm" />
            </PopoverTrigger>
            <PopoverContent className="w-72 p-0">
              <AddBlockerCommand
                projectId={projectId}
                taskId={taskId}
                exclude={[taskId, ...blockedBy.map((t) => t.id)]}
                onSelect={(t) => {
                  setOpen(false);
                  m.add.mutate(t.id);
                }}
              />
            </PopoverContent>
          </Popover>
        ) : null}
      </div>
      {blockedBy.length ? (
        <ul className="flex flex-col gap-0.5">
          {blockedBy.map((t) => (
            <BlockerRow key={t.id} task={t} onRemove={canEdit ? () => m.remove.mutate(t.id) : undefined} />
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted">Not blocked by anything</p>
      )}
      {blocking.length ? (
        <>
          <h3 className="section-label mt-3 mb-1">Blocking</h3>
          <ul className="flex flex-col gap-0.5">
            {blocking.map((t) => (
              <BlockerRow key={t.id} task={t} />
            ))}
          </ul>
        </>
      ) : null}
    </section>
  );
}
