import { EyeOff, X } from 'lucide-react';
import { useEffect, type ReactNode } from 'react';
import { cn } from '@/lib/cn';
import { Icon } from '@/components/ui/Icon';
import { IconButton } from '@/components/ui/IconButton';
import { Skeleton } from '@/components/ui/Skeleton';
import { formatValue } from './model';
import { useDrill, type DrillPoint } from './queries';
import { TaskLine, WidgetCard, type Mark, type WidgetItem } from './WidgetCard';

export interface DrillState extends DrillPoint {
  title: string;
  label?: string;
}

/**
 * The widget grid (4 columns on wide screens: numbers are one column, charts two, lists four) and
 * the drill-down beside it. Clicking any mark opens the tasks behind it, listed by the same clause
 * that counted them, so the numbers always add up.
 */
export function DashboardView({
  items,
  projectId,
  editable,
  drill,
  onDrill,
  onOpenTask,
  onEdit,
  onRemove,
  onMove,
  banner,
  paneOpen = false,
  onOrder,
}: {
  items: WidgetItem[];
  projectId: string | null;
  editable: boolean;
  drill: DrillState | null;
  onDrill: (d: DrillState | null) => void;
  onOpenTask: (taskId: string) => void;
  onEdit?: (item: WidgetItem, index: number) => void;
  onRemove?: (item: WidgetItem, index: number) => void;
  onMove?: (item: WidgetItem, index: number, dir: -1 | 1) => void;
  banner?: ReactNode;
  /** the task pane is open: the drill panel floats over the grid instead of narrowing it */
  paneOpen?: boolean;
  /** the drill's tasks become the pane's J/K order */
  onOrder?: (ids: string[]) => void;
}) {
  const open = (item: WidgetItem, mark: Mark) =>
    onDrill({
      spec: item.spec,
      projectId,
      key: mark.key ?? null,
      bucketStart: mark.bucketStart ?? null,
      title: item.title,
      label: mark.label,
    });
  return (
    <div className="relative flex min-h-0 gap-4">
      <div className="min-w-0 flex-1 space-y-4">
        {banner}
        <div className="grid grid-cols-2 gap-3 md:gap-4 xl:grid-cols-4">
          {items.map((item, i) => (
            <WidgetCard
              key={item.id ?? `starter-${i}`}
              item={item}
              projectId={projectId}
              editable={editable}
              onDrill={open}
              onOpenTask={onOpenTask}
              onEdit={onEdit ? () => onEdit(item, i) : undefined}
              onRemove={onRemove ? () => onRemove(item, i) : undefined}
              onMove={onMove ? (dir) => onMove(item, i, dir) : undefined}
            />
          ))}
        </div>
        <p className="flex items-center gap-1.5 text-xs text-muted">
          <Icon icon={EyeOff} size={12} aria-hidden />
          Numbers count top-level tasks in projects you can see, so a teammate may see different numbers here.
        </p>
      </div>
      {drill ? (
        <DrillPanel
          drill={drill}
          floating={paneOpen}
          onClose={() => onDrill(null)}
          onOpenTask={onOpenTask}
          onOrder={onOrder}
        />
      ) : null}
    </div>
  );
}

function DrillPanel({
  drill,
  floating,
  onClose,
  onOpenTask,
  onOrder,
}: {
  drill: DrillState;
  floating: boolean;
  onClose: () => void;
  onOpenTask: (taskId: string) => void;
  onOrder?: (ids: string[]) => void;
}) {
  const q = useDrill(drill);
  const ids = q.data?.tasks.map((t) => t.id).join(',') ?? '';
  useEffect(() => {
    if (ids) onOrder?.(ids.split(','));
  }, [ids, onOrder]);
  const heading = drill.label ?? q.data?.label;
  return (
    <aside
      aria-label="Tasks behind this number"
      className={cn(
        'flex shrink-0 flex-col rounded-xl border border-hair-soft bg-surface max-md:fixed max-md:inset-x-2 max-md:bottom-2 max-md:z-30 max-md:max-h-[70vh] max-md:shadow-pop md:sticky md:top-0 md:max-h-[calc(100vh-var(--topbar-h)-120px)] md:w-[min(360px,36vw)]',
        floating && 'md:absolute md:right-0 md:top-0 md:z-20 md:shadow-pop',
      )}
    >
      <header className="flex items-start gap-2 border-b border-hair-soft px-4 py-3">
        <div className="min-w-0 flex-1">
          <p className="truncate text-xs text-muted">{drill.title}</p>
          <h2 className="truncate text-sm font-semibold">
            {heading && heading !== 'Tasks' ? heading : 'All matching tasks'}
            {q.data ? (
              <span className="ml-2 font-normal text-muted">
                {formatValue({ measure: 'count' }, q.data.total)} {q.data.total === 1 ? 'task' : 'tasks'}
              </span>
            ) : null}
          </h2>
        </div>
        <IconButton icon={X} label="Close" size="icon-sm" onClick={onClose} />
      </header>
      <div className="min-h-0 flex-1 overflow-auto px-3 py-2">
        {q.isPending ? (
          <div className="space-y-2 py-2">
            <Skeleton className="h-6" />
            <Skeleton className="h-6" />
            <Skeleton className="h-6" />
          </div>
        ) : q.isError ? (
          <p role="alert" className="py-6 text-center text-sm text-muted">
            We couldn&apos;t load these tasks.
          </p>
        ) : q.data.tasks.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted">No tasks here.</p>
        ) : (
          <>
            <ul className="divide-y divide-hair-soft">
              {q.data.tasks.map((t) => (
                <TaskLine key={t.id} task={t} compact onOpen={() => onOpenTask(t.id)} />
              ))}
            </ul>
            {q.data.total > q.data.tasks.length ? (
              <p className="py-2 text-xs text-muted">
                Showing the first {q.data.tasks.length} of {q.data.total.toLocaleString()}.
              </p>
            ) : null}
          </>
        )}
      </div>
    </aside>
  );
}
