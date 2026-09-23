import {
  DragOverlay,
  useDndContext,
  useDroppable,
  type DragMoveEvent,
  type DragStartEvent,
} from '@dnd-kit/core';
import { Plus } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { ErrorState } from '@/components/common/States';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { Skeleton } from '@/components/ui/Skeleton';
import { useMe } from '@/features/auth';
import { usePeople, type Person } from '@/features/people';
import { SectionList, useCollapsed, useSections, type ItemDnd, type Section } from '@/features/sections';
import { cn } from '@/lib/cn';
import { formatDue } from '@/lib/dates';
import { applyRealtimeEvent, useChannel } from '@/lib/realtime';
import { BulkBar, type BulkPicker } from './BulkBar';
import { ListToolbar } from './ListToolbar';
import { isTemp, useProjectTasks, useTaskMutations, type Task, type TaskPatch } from './queries';
import {
  clickRow,
  dropNeighbors,
  emptySelection,
  prune,
  selectAll,
  step,
  targets,
  type DropPlacement,
  type Modifiers,
  type Selection,
} from './selection';
import { DraftRow, TaskRow } from './TaskRow';
import { useTaskNav } from './pane/nav';
import { useListView } from './useListView';
import { SubtaskList } from './SubtaskList';
import { VIRTUALIZE_OVER, VirtualRows } from './VirtualRows';
import {
  filterCount,
  groupTasks,
  isManualOrder,
  matches,
  sortTasks,
  todayLocal,
  type ListView,
} from './view';

type Draft = { sectionId: string; afterId: string | null; key: number; title?: string };
type DropTarget = { sectionId: string; anchorId: string | null; placement: DropPlacement };
const FADE_MS = 1500;
const CONFIRM_PASTE_OVER = 5;
const plural = (n: number, one: string) => `${n} ${one}${n === 1 ? '' : 's'}`;

/** The project list view: sections with their tasks; inline create/edit/complete, selection,
 * keyboard navigation, drag and drop (multi), and bulk actions. */
export function ProjectTasksView({ projectId, canEdit }: { projectId: string; canEdit: boolean }) {
  const qc = useQueryClient();
  useChannel(`project:${projectId}`, (event) => applyRealtimeEvent(qc, event, { projectId }));
  const { view, setView: applyView, ready: viewReady } = useListView(projectId);
  const showCompleted = view.show_completed;
  const manual = isManualOrder(view);
  const open = useProjectTasks(projectId);
  const done = useProjectTasks(projectId, true, showCompleted);
  const sections = useSections(projectId).data;
  const m = useTaskMutations(projectId);
  const { collapsed, toggle } = useCollapsed(projectId);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [fading, setFading] = useState<Set<string>>(new Set());
  const [rawSelection, setSelection] = useState<Selection>(emptySelection);
  const [drag, setDrag] = useState<{ ids: string[]; active: Task } | null>(null);
  const [dropTarget, setDropTarget] = useState<DropTarget | null>(null);
  const [bulkPicker, setBulkPicker] = useState<BulkPicker>(null);
  // Subtasks shown inline under rows, and a pending "new subtask" row (Tab from a new task row).
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());
  const [subDraft, setSubDraft] = useState<{ parentId: string; title: string; sectionId: string } | null>(
    null,
  );
  const toggleExpand = useCallback(
    (t: Task) =>
      setExpanded((s) => {
        const n = new Set(s);
        if (n.has(t.id)) n.delete(t.id);
        else n.add(t.id);
        return n;
      }),
    [],
  );
  const draftKey = useRef(0);
  const container = useRef<HTMLDivElement>(null);
  const meId = useMe().data?.user.id;
  const nav = useTaskNav();
  const openId = nav?.openId ?? null;
  const people = usePeople().data;
  const peopleById = useMemo(() => new Map<string, Person>((people ?? []).map((p) => [p.id, p])), [people]);
  // Rows edited or created here stay visible even if they stop matching the filters,
  // until the view changes (so a row never vanishes under the cursor).
  const [sticky, setSticky] = useState<ReadonlySet<string>>(new Set());
  const keep = useCallback((ids: string[]) => setSticky((s) => new Set([...s, ...ids])), []);
  const setView = useCallback(
    (v: ListView) => {
      setSticky(new Set());
      applyView(v);
    },
    [applyView],
  );

  const nameOf = useCallback((id: string) => peopleById.get(id)?.name, [peopleById]);
  const bySection = useMemo(() => {
    const today = todayLocal();
    const shown = (t: Task) => isTemp(t.id) || sticky.has(t.id) || matches(t, view, meId, today);
    const map = new Map<string, Task[]>();
    const visible = (open.data ?? []).filter(
      (t) => (!t.completed_at || fading.has(t.id) || showCompleted) && shown(t),
    );
    for (const t of visible) {
      const list = map.get(t.section_id!);
      if (list) list.push(t);
      else map.set(t.section_id!, [t]);
    }
    if (showCompleted) {
      const ids = new Set(visible.map((t) => t.id));
      for (const t of done.data ?? []) {
        if (ids.has(t.id) || !t.section_id || !shown(t)) continue;
        const list = map.get(t.section_id) ?? [];
        // merge by position; temp rows (no position) keep their place
        const i = list.findIndex((x) => x.position && t.position && x.position > t.position);
        map.set(t.section_id, i < 0 ? [...list, t] : [...list.slice(0, i), t, ...list.slice(i)]);
      }
    }
    if (view.sort !== 'manual') for (const [k, list] of map) map.set(k, sortTasks(list, view.sort, nameOf));
    return map;
  }, [open.data, done.data, fading, showCompleted, view, meId, sticky, nameOf]);

  // Non-section groupings (assignee / due) regroup the same filtered, sorted rows.
  const groups = useMemo(() => {
    if (view.group === 'section') return null;
    const all = (sections ?? []).flatMap((s) => bySection.get(s.id) ?? []);
    return groupTasks(sortTasks(all, view.sort, nameOf), view.group, nameOf, meId, todayLocal());
  }, [view.group, view.sort, sections, bySection, nameOf, meId]);

  // Visible rows in display order (collapsed sections excluded): the basis for ranges and arrows.
  const order = useMemo(
    () =>
      groups
        ? groups.flatMap((g) => g.tasks.map((t) => t.id))
        : (sections ?? [])
            .filter((s) => !collapsed.has(s.id))
            .flatMap((s) => (bySection.get(s.id) ?? []).map((t) => t.id)),
    [groups, sections, collapsed, bySection],
  );
  const selection = useMemo(() => prune(rawSelection, order), [rawSelection, order]);
  const taskById = useMemo(() => {
    const map = new Map<string, Task>();
    for (const list of bySection.values()) for (const t of list) map.set(t.id, t);
    return map;
  }, [bySection]);

  // Refs so row callbacks and drag handlers see current values (rows are memoized).
  const orderRef = useRef(order);
  const selectionRef = useRef(selection);
  const bySectionRef = useRef(bySection);
  const dropRef = useRef(dropTarget);
  useEffect(() => {
    orderRef.current = order;
    selectionRef.current = selection;
    bySectionRef.current = bySection;
  });

  // The pane steps through tasks in this list's order (J/K) and highlights the open row.
  useEffect(() => nav?.setOrder(order), [nav, order]);
  useEffect(() => {
    if (!openId) return;
    container.current
      ?.querySelector<HTMLElement>(`[data-task-id="${CSS.escape(openId)}"]`)
      ?.scrollIntoView?.({ block: 'nearest' });
  }, [openId]);
  const onOpen = useCallback(
    (t: Task) => {
      if (!nav || isTemp(t.id)) return;
      if (nav.openId === t.id) nav.close();
      else nav.open(t.id);
    },
    [nav],
  );

  const focusRow = useCallback((id: string | null) => {
    if (!id) return;
    const el = container.current?.querySelector<HTMLElement>(`[data-task-id="${CSS.escape(id)}"]`);
    el?.focus();
    el?.scrollIntoView?.({ block: 'nearest' });
  }, []);

  const openDraft = useCallback((sectionId: string, afterId: string | null, title?: string) => {
    draftKey.current += 1;
    setDraft({ sectionId, afterId, key: draftKey.current, title });
  }, []);

  const fade = useCallback((ids: string[]) => {
    setFading((s) => new Set([...s, ...ids]));
    setTimeout(
      () =>
        setFading((s) => {
          const n = new Set(s);
          ids.forEach((id) => n.delete(id));
          return n;
        }),
      FADE_MS,
    );
  }, []);

  const onToggle = useCallback(
    (t: Task) => {
      const completing = !t.completed_at;
      m.setCompleted.mutate({ id: t.id, completed: completing });
      if (completing) fade([t.id]);
    },
    [m.setCompleted, fade],
  );
  const onRename = useCallback((t: Task, title: string) => m.rename.mutate({ id: t.id, title }), [m.rename]);
  const onEnter = useCallback((t: Task) => canEdit && openDraft(t.section_id!, t.id), [canEdit, openDraft]);
  const onDelete = useCallback((t: Task) => m.remove.mutate(t.id), [m.remove]);
  const onUpdate = useCallback(
    (t: Task, patch: TaskPatch, message?: string) => {
      keep([t.id]);
      m.update.mutate({ id: t.id, patch, message });
    },
    [m.update, keep],
  );
  const onSelectClick = useCallback(
    (t: Task, mods: Modifiers) =>
      setSelection((s) => clickRow(prune(s, orderRef.current), t.id, mods, orderRef.current)),
    [],
  );
  // Focus moves on mouse-down, before the click: it must not move the Shift/⌘ range anchor.
  const onFocusRow = useCallback(
    (t: Task) => setSelection((s) => (s.focus === t.id ? s : { ...s, focus: t.id })),
    [],
  );

  // ---------- actions on the selection (or the focused row) ----------

  const sectionName = (id: string) => sections?.find((s) => s.id === id)?.name ?? 'section';

  const moveBlock = useCallback(
    (
      ids: string[],
      sectionId: string,
      anchorId: string | null,
      placement: DropPlacement,
      message?: string,
    ) => {
      const sectionOrder = (bySectionRef.current.get(sectionId) ?? []).map((t) => t.id);
      const n = dropNeighbors(sectionOrder, ids, anchorId, placement);
      if (!n) return false;
      m.move.mutate({ ids, sectionId, ...n, message });
      return true;
    },
    [m.move],
  );

  /** ⌘↑ / ⌘↓: move the target block one step, crossing into the neighboring section at the edges. */
  const nudge = (dir: 1 | -1) => {
    const ids = targets(selection, order);
    if (!ids.length || !sections) return;
    const first = taskById.get(ids[0]!);
    if (!first?.section_id) return;
    const sectionOrder = (bySection.get(first.section_id) ?? []).map((t) => t.id);
    const moving = new Set(ids);
    const firstIdx = sectionOrder.findIndex((id) => moving.has(id));
    let lastIdx = firstIdx;
    sectionOrder.forEach((id, i) => {
      if (moving.has(id)) lastIdx = i;
    });
    const si = sections.findIndex((s) => s.id === first.section_id);
    if (dir === -1) {
      const prev = sectionOrder
        .slice(0, firstIdx)
        .reverse()
        .find((id) => !moving.has(id));
      if (prev) moveBlock(ids, first.section_id, prev, 'before');
      else if (sections[si - 1]) {
        const target = sections[si - 1]!;
        moveBlock(ids, target.id, null, 'after', `Moved to ${target.name}`);
      }
    } else {
      const next = sectionOrder.slice(lastIdx + 1).find((id) => !moving.has(id));
      if (next) moveBlock(ids, first.section_id, next, 'after');
      else if (sections[si + 1]) {
        const target = sections[si + 1]!;
        const head = (bySection.get(target.id) ?? [])[0];
        moveBlock(ids, target.id, head?.id ?? null, head ? 'before' : 'after', `Moved to ${target.name}`);
      }
    }
    requestAnimationFrame(() => focusRow(selection.focus));
  };

  const bulkIds = targets(selection, order);
  const bulkUpdate = (patch: TaskPatch, message: string) => {
    keep(bulkIds);
    m.bulk.mutate({ ids: bulkIds, action: 'update', patch, message });
  };
  const bulkComplete = (ids: string[]) => {
    const incomplete = ids.filter((id) => !taskById.get(id)?.completed_at);
    if (!incomplete.length) {
      m.bulk.mutate({
        ids,
        action: 'uncomplete',
        message: `${plural(ids.length, 'task')} marked incomplete`,
      });
      return;
    }
    fade(incomplete);
    m.bulk.mutate({
      ids: incomplete,
      action: 'complete',
      message: `${plural(incomplete.length, 'task')} completed`,
    });
    setSelection(emptySelection);
  };
  const bulkDelete = (ids: string[]) => {
    m.bulk.mutate({ ids, action: 'delete', message: `${plural(ids.length, 'task')} deleted` });
    setSelection(emptySelection);
  };

  // ---------- keyboard ----------

  const isRowTarget = (e: KeyboardEvent) => (e.target as HTMLElement).dataset?.taskId !== undefined;

  const onKeyDownCapture = (e: KeyboardEvent<HTMLDivElement>) => {
    // With several rows selected, A / D / M act on the whole selection.
    if (!isRowTarget(e) || selection.selected.size < 2 || !canEdit) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const k = e.key.toLowerCase();
    if (k === 'a') setBulkPicker('assignee');
    else if (k === 'd') setBulkPicker('due');
    else if (k === 'm' && meId)
      bulkUpdate({ assignee_id: meId }, `${plural(bulkIds.length, 'task')} assigned to you`);
    else return;
    e.preventDefault();
    e.stopPropagation();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!isRowTarget(e) || e.defaultPrevented) return;
    const mod = e.metaKey || e.ctrlKey;
    const k = e.key;
    let next: Selection | null = null;
    if ((k === 'ArrowDown' || k === 'ArrowUp') && mod) {
      if (canEdit && manual) nudge(k === 'ArrowDown' ? 1 : -1);
    } else if (k === 'ArrowDown' || (k === 'j' && !mod)) next = step(selection, 1, e.shiftKey, order);
    else if (k === 'ArrowUp' || (k === 'k' && !mod)) next = step(selection, -1, e.shiftKey, order);
    else if (k === 'Escape' && selection.selected.size) next = { ...selection, selected: new Set() };
    else if (mod && k.toLowerCase() === 'a') {
      const sid = selection.focus ? taskById.get(selection.focus)?.section_id : null;
      if (!sid) return;
      next = selectAll(
        selection,
        (bySection.get(sid) ?? []).map((t) => t.id),
      );
    } else if (mod && k === 'Enter' && canEdit) {
      const ids = targets(selection, order);
      if (ids.length === 1) onToggle(taskById.get(ids[0]!)!);
      else if (ids.length > 1) bulkComplete(ids);
    } else if (mod && (k === 'Backspace' || k === 'Delete') && canEdit) {
      const ids = targets(selection, order);
      if (ids.length) bulkDelete(ids);
    } else return;
    e.preventDefault();
    if (next) {
      setSelection(next);
      if (next.focus !== selection.focus) {
        focusRow(next.focus);
        // with the pane open, it follows keyboard focus
        if (openId && next.focus && !e.shiftKey && !isTemp(next.focus))
          nav?.open(next.focus, { replace: true });
      }
    }
  };

  // ---------- drag and drop ----------

  const setDrop = (next: DropTarget | null) => {
    const prev = dropRef.current;
    if (
      prev?.sectionId === next?.sectionId &&
      prev?.anchorId === next?.anchorId &&
      prev?.placement === next?.placement
    )
      return;
    dropRef.current = next;
    setDropTarget(next);
  };
  const endDrag = () => {
    setDrag(null);
    setDrop(null);
  };

  const itemDnd: ItemDnd = {
    onDragStart: (e: DragStartEvent) => {
      const id = String(e.active.id);
      const active = taskById.get(id);
      if (!active) return;
      const current = selectionRef.current;
      let ids = [id];
      if (current.selected.has(id)) ids = targets(current, orderRef.current);
      else setSelection((s) => clickRow(s, id, {}, orderRef.current));
      setDraft(null);
      setDrag({ ids, active });
    },
    onDragMove: (e: DragMoveEvent) => {
      const data = e.over?.data.current as { kind?: string; taskId?: string; sectionId?: string } | undefined;
      if (data?.kind === 'section-end' && data.sectionId) {
        return setDrop({ sectionId: data.sectionId, anchorId: null, placement: 'after' });
      }
      if (data?.kind === 'section-head' && data.sectionId) {
        const first = (bySectionRef.current.get(data.sectionId) ?? []).find((t) => !drag?.ids.includes(t.id));
        return setDrop({
          sectionId: data.sectionId,
          anchorId: first?.id ?? null,
          placement: first ? 'before' : 'after',
        });
      }
      if (data?.kind === 'task' && data.taskId && data.sectionId && e.over) {
        const r = e.active.rect.current.translated;
        const mid = r ? r.top + r.height / 2 : 0;
        const placement = mid < e.over.rect.top + e.over.rect.height / 2 ? 'before' : 'after';
        return setDrop({ sectionId: data.sectionId, anchorId: data.taskId, placement });
      }
      setDrop(null);
    },
    onDragEnd: () => {
      const target = dropRef.current;
      if (drag && target) {
        const n = drag.ids.length;
        const crossing = drag.active.section_id !== target.sectionId;
        const msg =
          n > 1
            ? `Moved ${plural(n, 'task')}`
            : crossing
              ? `Moved to ${sectionName(target.sectionId)}`
              : undefined;
        moveBlock(drag.ids, target.sectionId, target.anchorId, target.placement, msg);
      }
      endDrag();
    },
    onDragCancel: endDrag,
    overlay: (
      <DragOverlay dropAnimation={null}>
        {drag ? (
          <div className="flex h-9 max-w-md items-center gap-2 rounded-md bg-surface px-3 text-[13.5px] shadow-pop">
            <span className="truncate">{drag.active.title}</span>
            {drag.ids.length > 1 ? (
              <span className="tabular rounded-full bg-accent px-1.5 text-xs font-medium text-on-accent">
                {drag.ids.length}
              </span>
            ) : null}
          </div>
        ) : null}
      </DragOverlay>
    ),
  };
  const draggingIds = useMemo(() => new Set(drag?.ids ?? []), [drag]);

  if (open.isPending || !viewReady) {
    return (
      <div className="flex flex-col gap-2">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-8" />
        ))}
      </div>
    );
  }
  if (open.isError) return <ErrorState error={open.error} onRetry={() => void open.refetch()} />;

  const renderRow = (t: Task, canExpand = false) => (
    <>
      <TaskRow
        task={t}
        canEdit={canEdit}
        draggable={manual}
        fading={fading.has(t.id)}
        assignee={t.assignee_id ? peopleById.get(t.assignee_id) : undefined}
        meId={meId}
        selected={selection.selected.has(t.id)}
        dragging={draggingIds.has(t.id)}
        dropIndicator={dropTarget?.anchorId === t.id ? dropTarget.placement : null}
        onSelectClick={onSelectClick}
        onFocusRow={onFocusRow}
        isOpen={openId === t.id}
        onOpen={nav ? onOpen : undefined}
        expanded={canExpand && expanded.has(t.id)}
        onToggleExpand={canExpand ? toggleExpand : undefined}
        onUpdate={onUpdate}
        onToggle={onToggle}
        onRename={onRename}
        onEnter={onEnter}
        onDelete={onDelete}
      />
      {canExpand && expanded.has(t.id) ? (
        <div className="border-b border-hair-soft pb-1 pl-9">
          <SubtaskList
            compact
            parentId={t.id}
            canEdit={canEdit}
            onOpen={nav ? (sub) => nav.open(sub.id) : undefined}
            startDraft={subDraft?.parentId === t.id}
            initialDraft={subDraft?.parentId === t.id ? subDraft.title : undefined}
            onDraftDone={() => setSubDraft((d) => (d?.parentId === t.id ? null : d))}
            onOutdentDraft={(title) => {
              // Shift+Tab: back to a top-level task row right after the parent
              setSubDraft(null);
              if (t.section_id) openDraft(t.section_id, t.id, title);
            }}
          />
        </div>
      ) : null}
    </>
  );

  const renderBody = (section: Section) => {
    const tasks = bySection.get(section.id) ?? [];
    const draftHere = draft && draft.sectionId === section.id ? draft : null;
    const draftRow = draftHere ? (
      <DraftRow
        key={`draft-${draftHere.key}`}
        onSubmit={(title) => {
          const id = m.create({ title, sectionId: section.id, afterId: draftHere.afterId }, (real) =>
            keep([real]),
          );
          openDraft(section.id, id);
        }}
        onPasteLines={(lines) => {
          if (
            lines.length > CONFIRM_PASTE_OVER &&
            !window.confirm(`Create ${lines.length} tasks, one per line?`)
          )
            return;
          m.createMany.mutate({ titles: lines, sectionId: section.id, afterId: draftHere.afterId });
          setDraft(null);
        }}
        onCancel={() => setDraft((d) => (d?.key === draftHere.key ? null : d))}
        initialValue={draftHere.title}
        onTab={(title) => {
          // Tab: this new row becomes a subtask of the task above it
          const parentId = draftHere.afterId;
          if (!parentId || isTemp(parentId)) return;
          setDraft(null);
          setExpanded((s) => new Set(s).add(parentId));
          setSubDraft({ parentId, title, sectionId: section.id });
        }}
      />
    ) : null;
    const draftIndex = draftHere
      ? draftHere.afterId
        ? tasks.findIndex((t) => t.id === draftHere.afterId) + 1
        : tasks.length
      : -1;
    type Item = { kind: 'task'; task: Task } | { kind: 'draft' };
    const items: Item[] = tasks.map((task) => ({ kind: 'task', task }));
    if (draftRow) items.splice(Math.max(0, Math.min(draftIndex, items.length)), 0, { kind: 'draft' });
    return (
      <div role="list" aria-label={`Tasks in ${section.name}`}>
        <VirtualRows
          items={items}
          getKey={(it) => (it.kind === 'draft' ? `draft-${draftHere?.key}` : it.task.id)}
          render={(it) =>
            it.kind === 'draft' ? draftRow : renderRow(it.task, tasks.length <= VIRTUALIZE_OVER)
          }
        />
        <SectionEnd
          sectionId={section.id}
          active={dropTarget?.sectionId === section.id && !dropTarget.anchorId}
        >
          {canEdit && !draftHere ? (
            <Button
              variant="text"
              size="sm"
              className="mt-1 text-muted"
              onClick={() => openDraft(section.id, tasks.filter((t) => !t.completed_at).at(-1)?.id ?? null)}
            >
              <Icon icon={Plus} /> Add task
            </Button>
          ) : null}
          {!canEdit && tasks.length === 0 ? <p className="py-1 text-sm text-muted-2">No tasks</p> : null}
        </SectionEnd>
      </div>
    );
  };

  const count = bulkIds.length;
  return (
    // Keyboard handling is delegated from the rows (each row is focusable).
    // eslint-disable-next-line jsx-a11y/no-static-element-interactions
    <div ref={container} className="@container" onKeyDownCapture={onKeyDownCapture} onKeyDown={onKeyDown}>
      <ListToolbar view={view} onChange={setView} />
      {!manual && canEdit ? (
        <p className="mb-2 text-xs text-muted">
          Drag to reorder is off while the list is sorted or grouped.{' '}
          <button
            type="button"
            className="underline underline-offset-2 hover:text-ink"
            onClick={() => setView({ ...view, sort: 'manual', group: 'section' })}
          >
            Back to drag order
          </button>
        </p>
      ) : null}
      <div
        aria-hidden
        className="flex h-8 items-center gap-2.5 border-b border-hairline pr-2 pl-11 text-xs text-muted"
      >
        <span className="flex-1 pl-[30px]">Task name</span>
        <span className="w-14 @max-3xl:hidden" />
        <span className="w-36 px-1.5 @max-3xl:w-10">
          <span className="@max-3xl:sr-only">Assignee</span>
        </span>
        <span className="w-32 px-1.5 @max-3xl:w-28 @max-md:w-20">Due date</span>
        <span className="w-7 @max-md:hidden" />
      </div>
      {order.length === 0 && filterCount(view) > 0 ? (
        <div className="py-10 text-center text-sm text-muted">
          <p>No tasks match these filters.</p>
          <Button
            size="sm"
            variant="text"
            className="mt-1"
            onClick={() => setView({ ...view, assignees: [], due: 'any' })}
          >
            Clear filters
          </Button>
        </div>
      ) : null}
      {groups ? (
        groups.map((g) => (
          <section key={g.id} aria-label={`Group ${g.name}`} className="mb-2">
            <h2 className="flex h-9 items-center gap-2 pl-6 text-[15px] font-semibold">
              {g.name}
              <span className="tabular text-xs font-normal text-muted">{g.tasks.length}</span>
            </h2>
            <div role="list" aria-label={`Tasks in ${g.name}`} className="pb-3 pl-11">
              <VirtualRows items={g.tasks} getKey={(t) => t.id} render={renderRow} />
            </div>
          </section>
        ))
      ) : (
        <SectionList
          projectId={projectId}
          canEdit={canEdit}
          renderBody={renderBody}
          collapsed={collapsed}
          onToggleCollapsed={toggle}
          itemDnd={canEdit && manual ? itemDnd : undefined}
        />
      )}
      {canEdit && selection.selected.size > 1 ? (
        <BulkBar
          count={count}
          sections={sections ?? []}
          picker={bulkPicker}
          onPickerChange={setBulkPicker}
          onAssign={(u) =>
            bulkUpdate(
              { assignee_id: u?.id ?? null },
              u
                ? `${plural(count, 'task')} assigned to ${u.id === meId ? 'you' : u.name}`
                : `${plural(count, 'task')} unassigned`,
            )
          }
          onDue={(v) =>
            bulkUpdate(
              v ? { due_on: v.date, due_at: v.at } : { due_on: null, due_at: null },
              v
                ? `${plural(count, 'task')} due ${formatDue(v.date, v.at)}`
                : `Due date removed from ${plural(count, 'task')}`,
            )
          }
          onMove={(sid) =>
            moveBlock(bulkIds, sid, null, 'after', `Moved ${plural(count, 'task')} to ${sectionName(sid)}`)
          }
          onComplete={() => bulkComplete(bulkIds)}
          onDelete={() => bulkDelete(bulkIds)}
          onClear={() => setSelection((s) => ({ ...s, selected: new Set() }))}
        />
      ) : null}
    </div>
  );
}

/** Drop zone at the end of a section (also where "Add task" lives). */
function SectionEnd({
  sectionId,
  active,
  children,
}: {
  sectionId: string;
  active: boolean;
  children: ReactNode;
}) {
  const { setNodeRef } = useDroppable({
    id: `section-end:${sectionId}`,
    data: { kind: 'section-end', sectionId },
  });
  const dragging = useDndContext().active !== null;
  return (
    <div ref={setNodeRef} className={cn('relative min-h-3', dragging && 'min-h-9')}>
      {active ? (
        <span aria-hidden className="absolute top-0 right-0 left-0 h-0.5 rounded-full bg-focus" />
      ) : null}
      {children}
    </div>
  );
}
