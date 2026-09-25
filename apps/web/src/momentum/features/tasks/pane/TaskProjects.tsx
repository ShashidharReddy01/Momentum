import { Command } from 'cmdk';
import { useQuery } from '@tanstack/react-query';
import { FolderPlus, Plus, X } from 'lucide-react';
import { useState } from 'react';
import { IconButton } from '@/components/ui/IconButton';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/Popover';
import { useApi } from '@/providers/api';
import { useTaskProjects, useTaskProjectMutations, type TaskProjectPlacement } from '../queries';

const ITEM =
  'flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm data-[selected=true]:bg-surface-2';

// `useProjects` (features/projects) can't be imported here: features/projects already imports
// features/tasks (ProjectPage renders ProjectTasksView), so the other direction would close a
// cycle. This duplicates its list query's key/shape (not the whole hook) so results still share
// the same cache entry — a rename elsewhere is reflected here too — without the import.
type PickableProject = { id: string; name: string; color: string | null; my_role: string };
function useAddableProjects() {
  const api = useApi();
  return useQuery({
    queryKey: ['projects', 'list', 'all', false] as const,
    queryFn: async () =>
      (await api.GET('/api/v1/projects', { params: { query: { archived: false } } })).data!.data,
  });
}

function ProjectDot({ color }: { color: string | null }) {
  return (
    <span
      aria-hidden
      className="h-2.5 w-2.5 shrink-0 rounded-sm"
      style={{ background: color ? `var(--${color})` : 'var(--muted-2)' }}
    />
  );
}

function AddProjectCommand({
  exclude,
  onSelect,
}: {
  exclude: string[];
  onSelect: (project: PickableProject) => void;
}) {
  const projects = useAddableProjects();
  const options = (projects.data ?? []).filter(
    (p) => !exclude.includes(p.id) && (p.my_role === 'admin' || p.my_role === 'editor'),
  );
  return (
    <Command label="Projects" loop>
      <Command.Input
        placeholder="Search projects…"
        className="h-10 w-full border-b border-hair-soft bg-transparent px-3 text-sm outline-none placeholder:text-muted-2"
      />
      <Command.List className="max-h-64 overflow-auto p-1">
        <Command.Empty className="px-3 py-4 text-center text-sm text-muted">
          {projects.isPending ? 'Loading…' : 'No other project to add'}
        </Command.Empty>
        {options.map((p) => (
          <Command.Item key={p.id} value={p.name} onSelect={() => onSelect(p)} className={ITEM}>
            <ProjectDot color={p.color} />
            <span className="truncate">{p.name}</span>
          </Command.Item>
        ))}
      </Command.List>
    </Command>
  );
}

/** The pane's "Projects" row (S2.4.1 multi-homing): every project this task is placed in, each
 * removable, plus a picker to add another. A task must stay in at least one project — the
 * backend enforces that; the UI just surfaces whatever error comes back. */
export function TaskProjects({ taskId, canEdit }: { taskId: string; canEdit: boolean }) {
  const placements = useTaskProjects(taskId);
  const m = useTaskProjectMutations(taskId);
  const [open, setOpen] = useState(false);
  const rows = placements.data ?? [];

  return (
    <div className="flex flex-wrap items-center gap-1">
      {rows.map((p) => (
        <ProjectChip
          key={p.project.id}
          placement={p}
          onRemove={canEdit ? () => m.remove.mutate(p.project.id) : undefined}
        />
      ))}
      {canEdit ? (
        <Popover open={open} onOpenChange={setOpen}>
          <PopoverTrigger asChild>
            <IconButton
              icon={rows.length ? Plus : FolderPlus}
              label="Add to another project"
              size="icon-sm"
            />
          </PopoverTrigger>
          <PopoverContent className="w-64 p-0">
            <AddProjectCommand
              exclude={rows.map((p) => p.project.id)}
              onSelect={(p) => {
                setOpen(false);
                m.add.mutate({ projectId: p.id });
              }}
            />
          </PopoverContent>
        </Popover>
      ) : null}
    </div>
  );
}

function ProjectChip({ placement, onRemove }: { placement: TaskProjectPlacement; onRemove?: () => void }) {
  return (
    <span className="inline-flex h-6 items-center gap-1 rounded-md bg-surface-2 px-1.5 text-xs font-medium">
      <ProjectDot color={placement.project.color} />
      {placement.project.name}
      {onRemove ? (
        <button
          type="button"
          aria-label={`Remove from ${placement.project.name}`}
          onClick={onRemove}
          className="grid h-4 w-4 place-items-center rounded-sm text-muted opacity-60 hover:bg-black/10 hover:opacity-100"
        >
          <X size={11} />
        </button>
      ) : null}
    </span>
  );
}
