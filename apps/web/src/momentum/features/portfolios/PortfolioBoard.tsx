import {
  DndContext,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import { Check, Diamond, MoreHorizontal, X } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Link } from 'react-router';
import { EmptyState } from '@/components/common/States';
import { Avatar } from '@/components/ui/Avatar';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu';
import { Icon } from '@/components/ui/Icon';
import { IconButton } from '@/components/ui/IconButton';
import { Skeleton } from '@/components/ui/Skeleton';
import { useProjectFieldDefs, type Field } from '@/features/fields';
import { cn } from '@/lib/cn';
import { day, money } from './cells';
import type { PortfolioDetail } from './queries';
import { HandoffOffer, ReadinessDialog, ReadWithMo } from './MoPortfolio';
import { gateChecklist, useMoveStage, usePortfolioRows, type Readiness, type RowV2 } from './v2queries';

const HEALTH_DOT: Record<string, string> = {
  on_track: 'bg-ok',
  at_risk: 'bg-warn',
  off_track: 'bg-crit',
  on_hold: 'bg-info',
  complete: 'bg-muted-2',
};

type Option = { id: string; label: string };
type Pending = { row: RowV2; to: Option; readiness: Readiness };

/**
 * Portfolio board (spec §5.4, §5.5): one column per stage, in the stage field's order. A card
 * shows the customer, its owner, value, health, days in stage (red past the stage's target) and
 * the next milestone. Drag a card, or use its "Move to stage…" menu from the keyboard, to set
 * the stage (undoable). A stage with a gate that isn't met shows the checklist instead; an
 * editor may "Move anyway", and the override is recorded.
 */
export function PortfolioBoard({ p }: { p: PortfolioDetail }) {
  const rows = usePortfolioRows(p.id, { groupBy: 'stage' });
  const defs = useProjectFieldDefs();
  const move = useMoveStage(p.id);
  const [pending, setPending] = useState<Pending | null>(null);
  // S75-10: "Check readiness for…" from a card, and the handoff offered after a move
  const [checking, setChecking] = useState<{ row: RowV2; to: Option } | null>(null);
  const [moved, setMoved] = useState<{ id: string; name: string; stage: string } | null>(null);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));
  const fields = useMemo(() => new Map((defs.data ?? []).map((f) => [f.id, f])), [defs.data]);
  const stage = p.stage_field_id ? fields.get(p.stage_field_id) : undefined;
  const options: Option[] = useMemo(
    () => ((stage?.options as Option[] | null) ?? []).map((o) => ({ id: o.id, label: o.label })),
    [stage],
  );
  const valueField = useMemo(
    () =>
      (rows.data?.columns ?? [])
        .filter((c) => c.visible && c.key.startsWith('field:'))
        .map((c) => fields.get(c.key.slice(6)))
        .find((f): f is Field => f?.type === 'currency'),
    [rows.data, fields],
  );

  if (!p.stage_field_id)
    return (
      <EmptyState title="No stage field yet">
        {p.can_edit
          ? 'Pick a stage field in the portfolio’s settings: its choices become the board’s columns.'
          : 'The portfolio’s editors haven’t picked a stage field yet.'}
      </EmptyState>
    );
  if (rows.isPending || defs.isPending) return <Skeleton className="h-64" />;
  if (rows.isError) return <p className="text-sm text-crit">Couldn’t load the board.</p>;

  const byId = new Map(rows.data.rows.map((r) => [r.id, r]));
  const targets = (p.stage_targets ?? {}) as Record<string, number>;
  const gates = (p.stage_gates ?? {}) as Record<string, unknown>;
  const gated = options.filter((o) => gates[o.id]);
  const tryMove = (row: RowV2, to: Option, override = false) => {
    if (row.stage?.option_id === to.id) return;
    move.mutate(
      { projectId: row.id, to: to.id, override, label: to.label },
      {
        onSuccess: () => {
          setPending(null);
          setMoved({ id: row.id, name: row.name, stage: to.label });
        },
        onError: (e) => {
          const r = gateChecklist(e);
          if (r) setPending({ row, to, readiness: r });
        },
      },
    );
  };
  const onDragEnd = (e: DragEndEvent) => {
    const row = byId.get(String(e.active.id));
    const to = options.find((o) => `stage:${o.id}` === e.over?.id);
    if (row && to) tryMove(row, to);
  };

  return (
    <>
      {moved ? (
        <div className="mb-3">
          <HandoffOffer
            key={`${moved.id}:${moved.stage}`}
            project={moved}
            stage={moved.stage}
            onDismiss={() => setMoved(null)}
          />
        </div>
      ) : null}
      <DndContext sensors={sensors} onDragEnd={onDragEnd}>
        <div className="flex gap-3 overflow-x-auto pb-2" role="list" aria-label={`Stages of ${p.name}`}>
          {(rows.data.groups ?? []).map((g) => {
            const option = options.find((o) => o.id === g.key);
            if (!option) return null; // "No stage": shown in the table, not as a column
            const cards = g.project_ids.map((id) => byId.get(id)).filter((r): r is RowV2 => !!r);
            const sums = (g.rollup as { sums?: Record<string, number> }).sums ?? {};
            const total = valueField ? sums[valueField.id] : undefined;
            const unit = (valueField?.options as { unit?: string | null } | null)?.unit ?? null;
            return (
              <Column
                key={option.id}
                option={option}
                count={cards.length}
                total={total === undefined ? null : money(total, unit)}
                target={targets[option.id] ?? null}
              >
                {cards.map((row) => (
                  <Card
                    key={row.id}
                    row={row}
                    options={options}
                    valueField={valueField}
                    target={targets[option.id] ?? null}
                    onMove={(to) => tryMove(row, to)}
                    gated={gated}
                    onCheck={(to) => setChecking({ row, to })}
                  />
                ))}
              </Column>
            );
          })}
        </div>
      </DndContext>
      {checking ? (
        <ReadinessDialog
          portfolioId={p.id}
          project={checking.row}
          stage={checking.to}
          onClose={() => setChecking(null)}
        />
      ) : null}
      <GateDialog
        portfolioId={p.id}
        pending={pending}
        busy={move.isPending}
        onCancel={() => setPending(null)}
        onOverride={() => pending && tryMove(pending.row, pending.to, true)}
      />
    </>
  );
}

function Column({
  option,
  count,
  total,
  target,
  children,
}: {
  option: Option;
  count: number;
  total: string | null;
  target: number | null;
  children: React.ReactNode;
}) {
  const drop = useDroppable({ id: `stage:${option.id}` });
  return (
    <section
      ref={drop.setNodeRef}
      role="listitem"
      aria-label={`${option.label}: ${count} ${count === 1 ? 'project' : 'projects'}`}
      className={cn(
        'flex w-64 shrink-0 flex-col rounded-xl border border-hair-soft bg-surface-2 p-2',
        drop.isOver && 'border-focus',
      )}
    >
      <header className="mb-2 px-1">
        <h3 className="flex items-center gap-2 text-sm font-semibold">
          <span className="truncate">{option.label}</span>
          <span className="tabular-nums text-muted">{count}</span>
        </h3>
        <p className="text-xs text-muted">
          {total ? <span className="tabular-nums">{total}</span> : null}
          {total && target !== null ? ' · ' : null}
          {target !== null ? `target ${target} days` : null}
        </p>
      </header>
      <ul className="flex min-h-12 flex-col gap-2" aria-label={`Projects in ${option.label}`}>
        {children}
      </ul>
    </section>
  );
}

function Card({
  row,
  options,
  valueField,
  target,
  onMove,
  gated,
  onCheck,
}: {
  row: RowV2;
  options: Option[];
  valueField: Field | undefined;
  target: number | null;
  onMove: (to: Option) => void;
  gated: Option[];
  onCheck: (to: Option) => void;
}) {
  const drag = useDraggable({ id: row.id, disabled: !row.can_edit });
  const value = valueField ? row.fields[valueField.id] : undefined;
  const unit = (valueField?.options as { unit?: string | null } | null)?.unit ?? null;
  const late =
    target !== null &&
    row.stage_age_days !== null &&
    row.stage_age_days !== undefined &&
    row.stage_age_days > target;
  return (
    <li
      ref={drag.setNodeRef}
      // pointer dragging only: from the keyboard, the card's "Move to stage…" menu does the same
      // (dnd-kit's own attributes would make the card a button around the menu's button)
      {...drag.listeners}
      className={cn(
        'rounded-lg border border-hairline bg-surface p-2.5 text-sm shadow-raise',
        drag.isDragging && 'opacity-60',
        row.can_edit && 'cursor-grab',
      )}
      style={
        drag.transform ? { transform: `translate(${drag.transform.x}px, ${drag.transform.y}px)` } : undefined
      }
    >
      <div className="flex items-start gap-2">
        {row.status ? (
          <span
            aria-label={`Health: ${row.status.replace('_', ' ')}`}
            role="img"
            className={cn('mt-1.5 h-2 w-2 shrink-0 rounded-full', HEALTH_DOT[row.status] ?? 'bg-hairline')}
          />
        ) : null}
        <Link
          to={`/projects/${row.id}/overview`}
          className="min-w-0 flex-1 truncate font-medium hover:underline"
        >
          {row.name}
        </Link>
        {row.can_edit ? (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <IconButton icon={MoreHorizontal} label={`Move ${row.name} to stage…`} size="icon-sm" />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel>Move to stage…</DropdownMenuLabel>
              {options.map((o) => (
                <DropdownMenuItem
                  key={o.id}
                  disabled={row.stage?.option_id === o.id}
                  onSelect={() => onMove(o)}
                >
                  {o.label}
                </DropdownMenuItem>
              ))}
              {gated.length ? <DropdownMenuLabel>Check readiness for…</DropdownMenuLabel> : null}
              {gated.map((o) => (
                <DropdownMenuItem key={`check:${o.id}`} onSelect={() => onCheck(o)}>
                  {o.label} readiness
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        ) : null}
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
        {row.owner_name ? (
          <span className="flex items-center gap-1">
            <Avatar name={row.owner_name} size={16} />
            <span className="truncate">{row.owner_name}</span>
          </span>
        ) : null}
        {typeof value === 'number' ? <span className="tabular-nums">{money(value, unit)}</span> : null}
        {row.stage_age_days !== null && row.stage_age_days !== undefined ? (
          <span className={cn('tabular-nums', late && 'font-medium text-crit')}>
            {row.stage_age_days} {row.stage_age_days === 1 ? 'day' : 'days'} in stage
          </span>
        ) : null}
      </div>
      {row.next_milestone ? (
        <p className="mt-1 flex items-center gap-1 text-xs text-muted">
          <Icon icon={Diamond} size={11} />
          <span className="truncate">{row.next_milestone.title}</span>
          {row.next_milestone.due_on ? <span>{day(row.next_milestone.due_on)}</span> : null}
        </p>
      ) : null}
    </li>
  );
}

/** The gate's checklist: met and missing, each with a link to what to open. */
function GateDialog({
  portfolioId,
  pending,
  busy,
  onCancel,
  onOverride,
}: {
  portfolioId: string;
  pending: Pending | null;
  busy: boolean;
  onCancel: () => void;
  onOverride: () => void;
}) {
  const r = pending?.readiness;
  return (
    <Dialog
      open={!!pending}
      onOpenChange={(o) => !o && onCancel()}
      title={r ? `${pending!.row.name} isn’t ready for ${r.stage_label}` : 'Not ready'}
      description="This stage has a gate. Here is what it needs."
    >
      {r ? (
        <div className="space-y-4 p-5">
          <ul className="space-y-1.5" aria-label="Gate checklist">
            {r.items.map((i) => (
              <li key={`${i.kind}:${i.label}`} className="flex items-center gap-2 text-sm">
                <Icon
                  icon={i.met ? Check : X}
                  size={14}
                  className={i.met ? 'text-ok' : 'text-crit'}
                  aria-label={i.met ? 'Met' : 'Missing'}
                />
                <span className="text-muted">{KIND_LABEL[i.kind] ?? i.kind}</span>
                <ItemLink item={i} projectId={pending!.row.id} />
              </li>
            ))}
          </ul>
          {r.items.some((i) => i.kind === 'file' && i.met) ? (
            <ReadWithMo portfolioId={portfolioId} projectId={pending!.row.id} to={r.stage} />
          ) : null}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={onCancel}>
              Cancel
            </Button>
            {pending!.row.can_edit ? (
              <Button size="sm" variant="danger" disabled={busy} onClick={onOverride}>
                Move anyway
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}
    </Dialog>
  );
}

const KIND_LABEL: Record<string, string> = { field: 'Field', milestone: 'Milestone', file: 'File' };

function ItemLink({ item, projectId }: { item: Readiness['items'][number]; projectId: string }) {
  const ref = item.ref as { type?: string; id?: string } | null;
  if (ref?.type === 'task' && ref.id)
    return (
      <Link className="truncate hover:underline" to={`/task/${ref.id}`}>
        {item.label}
      </Link>
    );
  if (ref?.type === 'file')
    return (
      <Link className="truncate hover:underline" to={`/projects/${projectId}/files`}>
        {item.label}
      </Link>
    );
  return (
    <Link className="truncate hover:underline" to={`/projects/${projectId}/overview`}>
      {item.label}
    </Link>
  );
}
