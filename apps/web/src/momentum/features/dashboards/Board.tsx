import { Plus } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { MoMark } from '@/components/common/MoMark';
import { Button } from '@/components/ui/Button';
import { useMomentumConfig } from '@/lib/config';
import { useChannel } from '@/lib/realtime';
import { AskChart } from './AskChart';
import { DashboardView, type DrillState } from './DashboardView';
import {
  dashboardKeys,
  useDashboardMutations,
  type DashboardDetail,
  type Widget,
  type WidgetIn,
} from './queries';
import type { WidgetItem } from './WidgetCard';
import { WidgetEditor } from './WidgetEditor';

export function itemOf(w: Widget): WidgetItem {
  return {
    id: w.id,
    kind: w.kind,
    title: w.title,
    spec: w.query_spec,
    size: w.viz.size ?? 'md',
    version: w.version,
    prompt: w.created_from_prompt ?? null,
  };
}

/**
 * A dashboard's grid with editing: add, edit, reorder and remove charts, each one undoable.
 * `ensure` returns the saved dashboard, creating it first when the grid shows the starter layout,
 * so the first edit of a project's starter dashboard saves it and then applies the edit.
 */
export function Board({
  dashboard,
  starter,
  projectId,
  editable,
  ensure,
  onOpenTask,
  title,
  actions,
  banner,
  paneOpen,
  onOrder,
}: {
  dashboard: DashboardDetail | null;
  starter?: WidgetItem[];
  projectId: string | null;
  editable: boolean;
  ensure: () => Promise<DashboardDetail>;
  onOpenTask: (taskId: string) => void;
  title: ReactNode;
  actions?: ReactNode;
  banner?: ReactNode;
  paneOpen?: boolean;
  onOrder?: (ids: string[]) => void;
}) {
  const qc = useQueryClient();
  const m = useDashboardMutations(dashboard?.id ?? null);
  const [drill, setDrill] = useState<DrillState | null>(null);
  const [editing, setEditing] = useState<{
    item: WidgetItem | null;
    index: number | null;
    prompt?: string;
  } | null>(null);
  const [asking, setAsking] = useState(false);
  const aiEnabled = useMomentumConfig().ai_enabled;
  const items = dashboard ? dashboard.widgets.map(itemOf) : (starter ?? []);

  // someone else's edit to this dashboard refreshes the layout
  useChannel(dashboard ? `dashboard:${dashboard.id}` : null, () => {
    void qc.invalidateQueries({ queryKey: dashboardKeys.all });
  });

  /** The saved widget at this position (saving the starter first if needed). */
  const savedAt = async (item: WidgetItem, index: number) => {
    if (item.id) return { board: dashboard!, id: item.id };
    const board = await ensure();
    return { board, id: board.widgets[index]!.id };
  };

  const save = async (body: WidgetIn) => {
    const target = editing;
    setEditing(null);
    if (target?.item && target.index !== null) {
      const { id } = await savedAt(target.item, target.index);
      m.updateWidget.mutate({ widgetId: id, body });
    } else {
      const board = await ensure();
      const prompt = target?.prompt;
      m.addWidget.mutate({
        dashboardId: board.id,
        body: prompt ? { ...body, created_from_prompt: prompt } : body,
      });
    }
  };
  const addAsked = async (body: WidgetIn) => {
    setAsking(false);
    const board = await ensure();
    m.addWidget.mutate({ dashboardId: board.id, body });
  };
  const remove = async (item: WidgetItem, index: number) => {
    const { id } = await savedAt(item, index);
    m.removeWidget.mutate(id);
  };
  const move = async (item: WidgetItem, index: number, dir: -1 | 1) => {
    const j = index + dir;
    if (j < 0 || j >= items.length) return;
    const { board, id } = await savedAt(item, index);
    const neighbour = board.widgets[j]!.id;
    m.moveWidget.mutate(
      dir < 0 ? { widgetId: id, before_id: neighbour } : { widgetId: id, after_id: neighbour },
    );
  };

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center gap-2">
        <div className="mr-auto min-w-0">{title}</div>
        {actions}
        {aiEnabled ? (
          <Button variant="ai" onClick={() => setAsking(true)}>
            <MoMark size={13} /> Ask for a chart
          </Button>
        ) : null}
        {editable ? (
          <Button variant="primary" onClick={() => setEditing({ item: null, index: null })}>
            <Plus size={14} aria-hidden /> Add chart
          </Button>
        ) : null}
      </header>
      <DashboardView
        items={items}
        projectId={projectId}
        editable={editable}
        drill={drill}
        onDrill={setDrill}
        onOpenTask={onOpenTask}
        onEdit={editable ? (item, index) => setEditing({ item, index }) : undefined}
        onRemove={editable ? (item, index) => void remove(item, index) : undefined}
        onMove={editable ? (item, index, dir) => void move(item, index, dir) : undefined}
        banner={banner}
        paneOpen={paneOpen}
        onOrder={onOrder}
      />
      <AskChart
        open={asking}
        onOpenChange={setAsking}
        projectId={projectId}
        editable={editable}
        onAdd={(body) => void addAsked(body)}
        onAdjust={(item, prompt) => {
          setAsking(false);
          setEditing({ item, index: null, prompt });
        }}
      />
      <WidgetEditor
        open={editing !== null}
        onOpenChange={(o) => (o ? undefined : setEditing(null))}
        initial={editing?.item ?? null}
        projectId={projectId}
        onSave={(body) => void save(body)}
        saving={m.addWidget.isPending || m.updateWidget.isPending}
      />
    </div>
  );
}
