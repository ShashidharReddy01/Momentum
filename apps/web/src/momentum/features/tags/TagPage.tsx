import { Tag as TagIcon, Trash2 } from 'lucide-react';
import { useMemo } from 'react';
import { useParams } from 'react-router';
import { CompleteCheck } from '@/components/common/CompleteCheck';
import { DueText } from '@/components/common/DueText';
import { EmptyState, ErrorState } from '@/components/common/States';
import { InlineText } from '@/components/common/InlineText';
import { Avatar } from '@/components/ui/Avatar';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { Skeleton } from '@/components/ui/Skeleton';
import { usePeople } from '@/features/people';
import { useProjects } from '@/features/projects';
import { TaskNavProvider, TaskPane, useTaskDetailMutations, useTaskNav, type Task } from '@/features/tasks';
import { cn } from '@/lib/cn';
import { useTagLibrary, useTagMutations, useTagTasks } from './queries';

/** The tag page: every visible, incomplete task carrying one tag, across every project. */
export function TagPage() {
  return (
    <TaskNavProvider>
      <TagPageBody />
    </TaskNavProvider>
  );
}

function TagPageBody() {
  const { tagId } = useParams<{ tagId: string }>();
  const nav = useTaskNav()!;
  const library = useTagLibrary();
  const tasks = useTagTasks(tagId ?? '', !!tagId);
  const projects = useProjects().data;
  const projectsById = useMemo(() => new Map((projects ?? []).map((p) => [p.id, p])), [projects]);
  const tag = library.data?.find((t) => t.id === tagId);
  const m = useTagMutations();

  if (!tagId) return null;

  return (
    <div className="flex h-full min-h-0">
      <div className="min-w-0 flex-1 overflow-auto px-4 md:px-8 py-6">
        <div className="mb-4 flex items-center gap-2">
          <span
            aria-hidden
            className="h-3 w-3 shrink-0 rounded-full"
            style={{ background: tag?.color ?? 'var(--muted-2)' }}
          />
          <h1 className="page-title">
            {tag ? (
              <InlineText
                value={tag.name}
                onCommit={(name) => m.update.mutate({ id: tag.id, patch: { name } })}
                aria-label="Tag name"
              />
            ) : (
              <Skeleton className="h-7 w-32" />
            )}
          </h1>
          {tag ? (
            <input
              type="color"
              aria-label="Tag color"
              value={tag.color}
              onChange={(e) => m.update.mutate({ id: tag.id, patch: { color: e.target.value } })}
              className="h-6 w-6 cursor-pointer rounded border border-hairline bg-transparent p-0"
            />
          ) : null}
          <span className="flex-1" />
          {tag ? (
            <Button
              size="sm"
              variant="text"
              className="text-crit"
              onClick={() => {
                if (confirm(`Delete the "${tag.name}" tag? It will be removed from every task.`)) {
                  m.remove.mutate(tag.id);
                }
              }}
            >
              <Icon icon={Trash2} /> Delete tag
            </Button>
          ) : null}
        </div>

        {tasks.isPending ? (
          <div className="flex flex-col gap-2" aria-busy>
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="h-9" />
            ))}
          </div>
        ) : tasks.isError ? (
          <ErrorState error={tasks.error} onRetry={() => void tasks.refetch()} />
        ) : tasks.data.length === 0 ? (
          <EmptyState icon={TagIcon} title="No tasks with this tag">
            Tag a task from its details pane to see it here.
          </EmptyState>
        ) : (
          <ul aria-label="Tagged tasks" className="flex flex-col">
            {tasks.data.map((t) => (
              <TagPageRow
                key={t.id}
                task={t}
                project={t.project_id ? projectsById.get(t.project_id) : undefined}
                isOpen={nav.openId === t.id}
                onOpen={() => nav.open(t.id)}
              />
            ))}
          </ul>
        )}
      </div>
      {nav.openId ? (
        <TaskPane
          taskId={nav.openId}
          onClose={nav.close}
          onStep={nav.step}
          onOpenTask={(id) => nav.open(id)}
        />
      ) : null}
    </div>
  );
}

function TagPageRow({
  task,
  project,
  isOpen,
  onOpen,
}: {
  task: Task;
  project: { id: string; name: string; color: string | null } | undefined;
  isOpen: boolean;
  onOpen: () => void;
}) {
  const people = usePeople().data;
  const assignee = task.assignee_id ? people?.find((p) => p.id === task.assignee_id) : undefined;
  const m = useTaskDetailMutations(task.id);
  const done = !!task.completed_at;
  return (
    <li
      className={cn(
        'flex h-11 items-center gap-2 border-b border-hair-soft px-2 text-sm hover:bg-surface-2',
        isOpen && 'bg-surface-2',
      )}
    >
      <CompleteCheck
        checked={done}
        onChange={() => m.setCompleted.mutate(!done)}
        label={`Complete ${task.title}`}
      />
      <button
        type="button"
        onClick={onOpen}
        className={cn('min-w-0 flex-1 truncate text-left', done && 'text-muted line-through')}
      >
        {task.title}
      </button>
      {project ? (
        <span className="flex shrink-0 items-center gap-1.5 truncate text-xs text-muted">
          <span
            aria-hidden
            className="h-2 w-2 rounded-sm"
            style={{ background: project.color ? `var(--${project.color})` : 'var(--muted-2)' }}
          />
          {project.name}
        </span>
      ) : null}
      {task.due_on ? (
        <DueText dueOn={task.due_on} dueAt={task.due_at} done={done} className="text-xs" />
      ) : null}
      {assignee ? <Avatar name={assignee.name} src={assignee.avatar_url} size={20} /> : null}
    </li>
  );
}
