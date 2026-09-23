import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  pointerWithin,
  PointerSensor,
  useDndContext,
  useDroppable,
  useSensor,
  useSensors,
  type CollisionDetection,
  type DragEndEvent,
  type DragMoveEvent,
  type DragStartEvent,
} from '@dnd-kit/core';
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import {
  ArrowDown,
  ArrowUp,
  ChevronDown,
  ChevronRight,
  GripVertical,
  MoreHorizontal,
  Plus,
  Trash2,
} from 'lucide-react';
import { useState, type FormEvent, type ReactNode } from 'react';
import { InlineText } from '@/components/common/InlineText';
import { ErrorState } from '@/components/common/States';
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
import { Input } from '@/components/ui/Input';
import { Skeleton } from '@/components/ui/Skeleton';
import { cn } from '@/lib/cn';
import { useSectionMutations, useSections, type Section } from './queries';

/** Collapsed sections per project, remembered in localStorage. */
export function useCollapsed(projectId: string) {
  const storageKey = `momentum.collapsed.${projectId}`;
  const [collapsed, setCollapsed] = useState<Set<string>>(() => {
    try {
      return new Set(JSON.parse(localStorage.getItem(storageKey) ?? '[]') as string[]);
    } catch {
      return new Set();
    }
  });
  const toggle = (id: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      try {
        localStorage.setItem(storageKey, JSON.stringify([...next]));
      } catch {
        /* storage unavailable: keep in memory */
      }
      return next;
    });
  return { collapsed, toggle };
}

/**
 * Drag handlers for items other than sections (tasks) that share this list's DndContext.
 * Draggables/droppables mark themselves with `data.kind`: 'task' rows and 'section-end' zones.
 */
export interface ItemDnd {
  onDragStart: (e: DragStartEvent) => void;
  onDragMove: (e: DragMoveEvent) => void;
  onDragEnd: (e: DragEndEvent) => void;
  onDragCancel: () => void;
  overlay: ReactNode;
}

export interface SectionListProps {
  projectId: string;
  canEdit: boolean;
  /** Renders the body of a section (tasks). */
  renderBody?: (section: Section) => ReactNode;
  /** Controlled collapse (so the parent knows which rows are visible). */
  collapsed?: ReadonlySet<string>;
  onToggleCollapsed?: (id: string) => void;
  itemDnd?: ItemDnd;
}

const isItem = (data: unknown) => (data as { kind?: string } | undefined)?.kind !== undefined;

/** Sections only collide with sections; task drags only with task rows and section drop zones. */
const collisions: CollisionDetection = (args) => {
  const item = isItem(args.active.data.current);
  const droppableContainers = args.droppableContainers.filter((c) => isItem(c.data.current) === item);
  if (!item) return closestCenter({ ...args, droppableContainers });
  const within = pointerWithin({ ...args, droppableContainers });
  return within.length ? within : closestCenter({ ...args, droppableContainers });
};

/** Sections of a project: collapse, rename, add, delete, and reorder by drag or menu. */
export function SectionList({
  projectId,
  canEdit,
  renderBody,
  collapsed: controlled,
  onToggleCollapsed,
  itemDnd,
}: SectionListProps) {
  const sections = useSections(projectId);
  const { create, rename, move, remove } = useSectionMutations(projectId);
  const own = useCollapsed(projectId);
  const collapsed = controlled ?? own.collapsed;
  const toggle = onToggleCollapsed ?? own.toggle;
  const [adding, setAdding] = useState(false);
  const [newName, setNewName] = useState('');
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  if (sections.isPending) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-6 w-40" />
        <Skeleton className="h-6 w-56" />
      </div>
    );
  }
  if (sections.isError) return <ErrorState error={sections.error} onRetry={() => void sections.refetch()} />;
  const list = sections.data;

  const moveTo = (id: string, newIndex: number) => {
    const reordered = arrayMove(
      list,
      list.findIndex((s) => s.id === id),
      newIndex,
    );
    const at = reordered.findIndex((s) => s.id === id);
    move.mutate({ id, afterId: reordered[at - 1]?.id ?? null, beforeId: reordered[at + 1]?.id ?? null });
  };

  const onDragEnd = (e: DragEndEvent) => {
    if (isItem(e.active.data.current)) return itemDnd?.onDragEnd(e);
    if (!e.over || e.active.id === e.over.id) return;
    moveTo(
      String(e.active.id),
      list.findIndex((s) => s.id === e.over!.id),
    );
  };

  const submitNew = (e: FormEvent) => {
    e.preventDefault();
    const name = newName.trim();
    if (!name) return setAdding(false);
    create.mutate({ name }, { onSuccess: () => setNewName('') });
  };

  return (
    <div className="flex flex-col gap-1">
      <DndContext
        sensors={sensors}
        collisionDetection={collisions}
        onDragStart={(e) => isItem(e.active.data.current) && itemDnd?.onDragStart(e)}
        onDragMove={(e) => isItem(e.active.data.current) && itemDnd?.onDragMove(e)}
        onDragEnd={onDragEnd}
        onDragCancel={(e) => isItem(e.active.data.current) && itemDnd?.onDragCancel()}
      >
        <SortableContext items={list.map((s) => s.id)} strategy={verticalListSortingStrategy}>
          {list.map((s, i) => (
            <SortableSection
              key={s.id}
              section={s}
              canEdit={canEdit}
              isCollapsed={collapsed.has(s.id)}
              onToggle={() => toggle(s.id)}
              onRename={(name) => rename.mutate({ id: s.id, name })}
              onAddBelow={() => create.mutate({ name: 'Untitled section', afterId: s.id })}
              onMoveUp={i > 0 ? () => moveTo(s.id, i - 1) : undefined}
              onMoveDown={i < list.length - 1 ? () => moveTo(s.id, i + 1) : undefined}
              onDelete={list.length > 1 ? () => remove.mutate(s.id) : undefined}
            >
              {renderBody?.(s)}
            </SortableSection>
          ))}
        </SortableContext>
        {itemDnd?.overlay}
      </DndContext>
      {canEdit ? (
        adding ? (
          <form onSubmit={submitNew} className="mt-2 flex max-w-sm gap-2">
            <Input
              aria-label="New section name"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => e.key === 'Escape' && setAdding(false)}
              placeholder="Section name"
              // eslint-disable-next-line jsx-a11y/no-autofocus -- user just asked to add a section
              autoFocus
            />
            <Button type="submit" variant="primary" loading={create.isPending}>
              Add
            </Button>
          </form>
        ) : (
          <Button variant="text" className="mt-2 w-fit" onClick={() => setAdding(true)}>
            <Icon icon={Plus} /> Add section
          </Button>
        )
      ) : null}
    </div>
  );
}

function SortableSection({
  section,
  canEdit,
  isCollapsed,
  onToggle,
  onRename,
  onAddBelow,
  onMoveUp,
  onMoveDown,
  onDelete,
  children,
}: {
  section: Section;
  canEdit: boolean;
  isCollapsed: boolean;
  onToggle: () => void;
  onRename: (name: string) => void;
  onAddBelow: () => void;
  onMoveUp?: () => void;
  onMoveDown?: () => void;
  onDelete?: () => void;
  children?: ReactNode;
}) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } =
    useSortable({
      id: section.id,
      disabled: !canEdit,
      data: {},
    });
  // Dropping tasks on the header appends them to this section (works when collapsed too).
  const head = useDroppable({
    id: `section-head:${section.id}`,
    data: { kind: 'section-end', sectionId: section.id },
  });
  const draggingItem = isItem(useDndContext().active?.data.current);
  return (
    <section
      ref={setNodeRef}
      aria-label={`Section ${section.name}`}
      style={{ transform: CSS.Translate.toString(transform), transition }}
      className={cn('group/section rounded-md', isDragging && 'relative z-10 bg-surface shadow-pop')}
    >
      <div
        ref={head.setNodeRef}
        className={cn(
          'flex h-9 items-center gap-1 rounded-md',
          draggingItem && head.isOver && 'bg-accent-tint ring-1 ring-focus',
        )}
      >
        {canEdit ? (
          <button
            type="button"
            ref={setActivatorNodeRef}
            aria-label={`Reorder section ${section.name}`}
            className="grid h-7 w-5 cursor-grab place-items-center text-muted-2 opacity-0 group-hover/section:opacity-100 focus-visible:opacity-100"
            {...attributes}
            {...listeners}
          >
            <Icon icon={GripVertical} size={14} />
          </button>
        ) : (
          <span className="w-5" />
        )}
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={!isCollapsed}
          aria-label={isCollapsed ? `Expand ${section.name}` : `Collapse ${section.name}`}
          className="grid h-7 w-6 place-items-center rounded text-muted hover:text-ink"
        >
          <Icon icon={isCollapsed ? ChevronRight : ChevronDown} size={15} />
        </button>
        <h2 className="min-w-0 text-[15px] font-semibold">
          <InlineText
            aria-label="Section name"
            value={section.name}
            disabled={!canEdit}
            onCommit={onRename}
          />
        </h2>
        {canEdit ? (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <IconButton
                icon={MoreHorizontal}
                label={`Actions for section ${section.name}`}
                size="icon-sm"
                className="opacity-0 group-hover/section:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100"
              />
            </DropdownMenuTrigger>
            <DropdownMenuContent>
              <DropdownMenuItem onSelect={onAddBelow}>
                <Icon icon={Plus} /> Add section below
              </DropdownMenuItem>
              <DropdownMenuItem disabled={!onMoveUp} onSelect={onMoveUp}>
                <Icon icon={ArrowUp} /> Move up
              </DropdownMenuItem>
              <DropdownMenuItem disabled={!onMoveDown} onSelect={onMoveDown}>
                <Icon icon={ArrowDown} /> Move down
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                className="text-crit"
                disabled={!onDelete}
                hint={onDelete ? undefined : 'last section'}
                onSelect={onDelete}
              >
                <Icon icon={Trash2} /> Delete section
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        ) : null}
      </div>
      {isCollapsed ? null : <div className="pb-3 pl-11">{children}</div>}
    </section>
  );
}
