import { ArrowDown, ArrowUp, ChevronDown, ChevronUp, Columns3, Download, Save, Trash2 } from 'lucide-react';
import { useMemo, useState, type KeyboardEvent, type PointerEvent } from 'react';
import { EmptyState } from '@/components/common/States';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { IconButton } from '@/components/ui/IconButton';
import { Input } from '@/components/ui/Input';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/Popover';
import { Skeleton } from '@/components/ui/Skeleton';
import { FieldValueEditor, useProjectFieldDefs, type Field } from '@/features/fields';
import { cn } from '@/lib/cn';
import { useMomentumConfig } from '@/lib/config';
import { Cell, NUMERIC_KEYS, fieldOf, money } from './cells';
import type { PortfolioDetail } from './queries';
import {
  rowsQuery,
  useBulkSetField,
  usePortfolioRows,
  usePortfolioSettings,
  usePortfolioViews,
  useSetRowField,
  useViewMutations,
  type ColumnV2,
  type RowGroup,
  type RowV2,
  type RowsParams,
  type SavedView,
  type SortSpec,
} from './v2queries';

const selectClass =
  'h-8 rounded-md border border-hairline bg-surface-2 px-2.5 text-sm focus:border-focus focus:outline-none focus:ring-2 focus:ring-focus/25';
const DEFAULT_WIDTH = 140;
const NAME_WIDTH = 240;

/**
 * Portfolio table (spec §5.4): spreadsheet-like. A sticky name column; columns from the
 * portfolio's settings (pick, reorder and resize them; editors save that for everyone);
 * click a header to sort; group by health, owner, stage or a choice field with rollup rows;
 * project fields edit in place where you may edit the project; select rows for one-undo
 * "Set field…"; export what you see as CSV. Saved views (yours or shared) remember the rest.
 * Every number comes from the server.
 */
export function PortfolioTable({ p }: { p: PortfolioDetail }) {
  const views = usePortfolioViews(p.id);
  const [viewId, setViewId] = useState<string | null>(null);
  const view = (views.data ?? []).find((v) => v.id === viewId) ?? null;
  // ad hoc choices on top of the saved view (undefined = the view's own)
  const [groupBy, setGroupBy] = useState<string | null | undefined>(undefined);
  const [sort, setSort] = useState<SortSpec[] | undefined>(undefined);
  const params: RowsParams = { viewId, groupBy, sort };
  const q = usePortfolioRows(p.id, params);
  const defs = useProjectFieldDefs();
  const fields = useMemo(() => new Map((defs.data ?? []).map((f) => [f.id, f])), [defs.data]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [widths, setWidths] = useState<Record<string, number>>({});
  const setField = useSetRowField(p.id);

  const effectiveSort: SortSpec[] = sort ?? ((view?.sort ?? []) as SortSpec[]);
  const effectiveGroup = groupBy === undefined ? (view?.group_by ?? null) : groupBy;

  if (q.isPending) return <Skeleton className="h-64" />;
  if (q.isError) return <p className="text-sm text-crit">Couldn’t load the rows.</p>;
  const data = q.data;
  const columns = data.columns.filter((c) => c.visible);
  const width = (c: ColumnV2) => widths[c.key] ?? c.width ?? (c.key === 'name' ? NAME_WIDTH : DEFAULT_WIDTH);
  const rowsById = new Map(data.rows.map((r) => [r.id, r]));
  const editableSelected = [...selected].filter((id) => rowsById.get(id)?.can_edit);

  const toggleSort = (key: string) => {
    const current = effectiveSort[0];
    const next: SortSpec[] =
      current?.key === key ? (current.dir === 'asc' ? [{ key, dir: 'desc' }] : []) : [{ key, dir: 'asc' }];
    setSort(next);
  };

  return (
    <div className="space-y-3">
      <Toolbar
        p={p}
        views={views.data ?? []}
        view={view}
        onView={(id) => {
          setViewId(id);
          setGroupBy(undefined);
          setSort(undefined);
        }}
        groupBy={effectiveGroup}
        onGroupBy={setGroupBy}
        sort={effectiveSort}
        columns={data.columns}
        fields={fields}
        params={params}
      />
      {selected.size ? (
        <BulkBar
          p={p}
          count={selected.size}
          editable={editableSelected}
          fields={defs.data ?? []}
          onDone={() => setSelected(new Set())}
        />
      ) : null}
      {data.rows.length === 0 ? (
        <EmptyState title="No projects to show">
          {p.kind === 'rule'
            ? 'No project you can see matches this portfolio’s rule yet.'
            : 'Add projects to this portfolio, or clear the view’s filters.'}
        </EmptyState>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-hairline bg-surface">
          <table className="border-separate border-spacing-0 text-sm" style={{ tableLayout: 'fixed' }}>
            <caption className="sr-only">Projects in {p.name}</caption>
            <colgroup>
              <col style={{ width: 36 }} />
              {columns.map((c) => (
                <col key={c.key} style={{ width: width(c) }} />
              ))}
            </colgroup>
            <thead className="text-left text-xs text-muted">
              <tr>
                <th className="sticky left-0 z-20 border-b border-hairline bg-surface px-2 py-2">
                  <input
                    type="checkbox"
                    aria-label="Select all projects"
                    checked={selected.size > 0 && selected.size === data.rows.length}
                    onChange={(e) =>
                      setSelected(e.target.checked ? new Set(data.rows.map((r) => r.id)) : new Set())
                    }
                  />
                </th>
                {columns.map((c) => {
                  const s = effectiveSort.find((x) => x.key === c.key);
                  return (
                    <th
                      key={c.key}
                      scope="col"
                      aria-sort={s ? (s.dir === 'asc' ? 'ascending' : 'descending') : 'none'}
                      className={cn(
                        'relative border-b border-hairline bg-surface px-2 py-2 font-medium',
                        c.key === 'name' && 'sticky left-9 z-20',
                      )}
                    >
                      <button
                        type="button"
                        onClick={() => toggleSort(c.key)}
                        className={cn(
                          'flex w-full items-center gap-1 truncate hover:text-ink',
                          NUMERIC_KEYS.has(c.key) && 'justify-end',
                        )}
                      >
                        <span className="truncate">{c.label}</span>
                        {s ? <Icon icon={s.dir === 'asc' ? ArrowUp : ArrowDown} size={12} /> : null}
                      </button>
                      <Resizer
                        label={c.label}
                        width={width(c)}
                        onChange={(w) => setWidths((prev) => ({ ...prev, [c.key]: w }))}
                      />
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {(
                data.groups ?? [
                  { key: '__all', label: '', project_ids: data.rows.map((r) => r.id), rollup: {} },
                ]
              ).map((g) => (
                <GroupRows
                  key={g.key ?? '__none'}
                  group={g}
                  grouped={data.groups !== null && data.groups !== undefined}
                  rows={g.project_ids.map((id) => rowsById.get(id)).filter((r): r is RowV2 => !!r)}
                  columns={columns}
                  fields={fields}
                  selected={selected}
                  onSelect={(id, on) =>
                    setSelected((prev) => {
                      const next = new Set(prev);
                      if (on) next.add(id);
                      else next.delete(id);
                      return next;
                    })
                  }
                  onEdit={(row, f, value) =>
                    setField.mutate({ projectId: row.id, fieldId: f.id, value, name: f.name })
                  }
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data.hidden_projects > 0 ? (
        <p className="text-xs text-muted">
          {data.hidden_projects} more {data.hidden_projects === 1 ? 'project is' : 'projects are'} in this
          portfolio but not shown: you can’t see {data.hidden_projects === 1 ? 'it' : 'them'}.
        </p>
      ) : null}
    </div>
  );
}

function GroupRows({
  group,
  grouped,
  rows,
  columns,
  fields,
  selected,
  onSelect,
  onEdit,
}: {
  group: RowGroup;
  grouped: boolean;
  rows: RowV2[];
  columns: ColumnV2[];
  fields: Map<string, Field>;
  selected: Set<string>;
  onSelect: (id: string, on: boolean) => void;
  onEdit: (row: RowV2, f: Field, value: unknown) => void;
}) {
  return (
    <>
      {grouped ? (
        <tr className="bg-surface-2">
          <th
            scope="row"
            colSpan={columns.length + 1}
            className="sticky left-0 border-b border-hairline px-3 py-1.5 text-left text-xs font-semibold"
          >
            <span className="mr-2">{group.label}</span>
            <Rollup rollup={group.rollup} fields={fields} />
          </th>
        </tr>
      ) : null}
      {rows.map((row) => (
        <tr key={row.id} className="group hover:bg-surface-2" aria-selected={selected.has(row.id)}>
          <td className="sticky left-0 z-10 border-b border-hair-soft bg-surface px-2 py-2 group-hover:bg-surface-2">
            <input
              type="checkbox"
              aria-label={`Select ${row.name}`}
              checked={selected.has(row.id)}
              onChange={(e) => onSelect(row.id, e.target.checked)}
            />
          </td>
          {columns.map((c) => (
            <td
              key={c.key}
              className={cn(
                'truncate border-b border-hair-soft px-2 py-2',
                NUMERIC_KEYS.has(c.key) && 'text-right',
                c.key === 'name' && 'sticky left-9 z-10 bg-surface group-hover:bg-surface-2',
              )}
            >
              <Cell col={c} row={row} fields={fields} onEdit={(f, v) => onEdit(row, f, v)} />
            </td>
          ))}
        </tr>
      ))}
    </>
  );
}

/** A group header's rollups: count, average progress, overdue total, and the sums of money and
 * number fields (from the server). */
function Rollup({ rollup, fields }: { rollup: Record<string, unknown>; fields: Map<string, Field> }) {
  const r = rollup as {
    count?: number;
    progress_avg?: number | null;
    overdue_total?: number;
    sums?: Record<string, number>;
  };
  const sums = Object.entries(r.sums ?? {})
    .map(([id, total]) => {
      const f = fields.get(id);
      if (!f) return null;
      const unit =
        f.type === 'currency' ? ((f.options as { unit?: string | null } | null)?.unit ?? null) : null;
      return `${f.name} ${money(total, unit)}`;
    })
    .filter(Boolean);
  return (
    <span className="font-normal text-muted">
      {r.count ?? 0} {r.count === 1 ? 'project' : 'projects'}
      {r.progress_avg !== null && r.progress_avg !== undefined
        ? ` · ${Math.round(r.progress_avg * 100)}% done`
        : ''}
      {r.overdue_total ? ` · ${r.overdue_total} overdue` : ''}
      {sums.length ? ` · ${sums.join(' · ')}` : ''}
    </span>
  );
}

/** A column edge you can drag, or move with ←/→ when focused. */
function Resizer({
  label,
  width,
  onChange,
}: {
  label: string;
  width: number;
  onChange: (w: number) => void;
}) {
  const clamp = (w: number) => Math.max(60, Math.min(800, Math.round(w)));
  const down = (e: PointerEvent<HTMLDivElement>) => {
    const start = e.clientX;
    const initial = width;
    const move = (ev: globalThis.PointerEvent) => onChange(clamp(initial + ev.clientX - start));
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };
  const key = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault();
      onChange(clamp(width + (e.key === 'ArrowRight' ? 16 : -16)));
    }
  };
  // A focusable separator is the WAI-ARIA "window splitter" widget (←/→ resize); jsx-a11y
  // doesn't know it is interactive.
  /* eslint-disable jsx-a11y/no-noninteractive-element-interactions, jsx-a11y/no-noninteractive-tabindex */
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={`Resize ${label}`}
      aria-valuenow={width}
      aria-valuemin={60}
      aria-valuemax={800}
      tabIndex={0}
      onPointerDown={down}
      onKeyDown={key}
      className="absolute right-0 top-1 bottom-1 w-1.5 cursor-col-resize rounded hover:bg-hairline focus-visible:bg-focus"
    />
  );
  /* eslint-enable jsx-a11y/no-noninteractive-element-interactions, jsx-a11y/no-noninteractive-tabindex */
}

function Toolbar({
  p,
  views,
  view,
  onView,
  groupBy,
  onGroupBy,
  sort,
  columns,
  fields,
  params,
}: {
  p: PortfolioDetail;
  views: SavedView[];
  view: SavedView | null;
  onView: (id: string | null) => void;
  groupBy: string | null;
  onGroupBy: (g: string | null) => void;
  sort: SortSpec[];
  columns: ColumnV2[];
  fields: Map<string, Field>;
  params: RowsParams;
}) {
  const { api_base } = useMomentumConfig();
  const vm = useViewMutations(p.id);
  const groupOptions = [
    { id: '', label: 'No grouping' },
    { id: 'status', label: 'Health' },
    { id: 'owner', label: 'Owner' },
    ...(p.stage_field_id ? [{ id: 'stage', label: 'Stage' }] : []),
    ...[...fields.values()]
      .filter((f) => f.type === 'single_select' && f.id !== p.stage_field_id)
      .map((f) => ({ id: `field:${f.id}`, label: f.name })),
  ];
  const csv = `${api_base}/portfolios/${p.id}/export/csv?${new URLSearchParams(rowsQuery(params)).toString()}`;
  return (
    <div className="flex flex-wrap items-center gap-2" role="toolbar" aria-label="Table view">
      <label className="sr-only" htmlFor="portfolio-view">
        View
      </label>
      <select
        id="portfolio-view"
        className={selectClass}
        value={view?.id ?? ''}
        onChange={(e) => onView(e.target.value || null)}
      >
        <option value="">All projects</option>
        {views.some((v) => v.shared) ? (
          <optgroup label="Shared views">
            {views
              .filter((v) => v.shared)
              .map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name}
                </option>
              ))}
          </optgroup>
        ) : null}
        {views.some((v) => !v.shared) ? (
          <optgroup label="My views">
            {views
              .filter((v) => !v.shared)
              .map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name}
                </option>
              ))}
          </optgroup>
        ) : null}
      </select>
      <SaveView
        p={p}
        view={view}
        onSave={(name, shared) =>
          vm.create.mutate(
            { name, shared, group_by: groupBy, sort, layout: 'table' },
            { onSuccess: (res) => onView(res.data.id) },
          )
        }
        onUpdate={() => view && vm.update.mutate({ viewId: view.id, patch: { group_by: groupBy, sort } })}
      />
      {view && (!view.shared || p.can_edit) ? (
        <IconButton
          icon={Trash2}
          label={`Delete view ${view.name}`}
          size="icon-sm"
          onClick={() => vm.remove.mutate(view.id, { onSuccess: () => onView(null) })}
        />
      ) : null}
      <label className="sr-only" htmlFor="portfolio-group">
        Group by
      </label>
      <select
        id="portfolio-group"
        className={selectClass}
        value={groupBy ?? ''}
        onChange={(e) => onGroupBy(e.target.value || null)}
      >
        {groupOptions.map((o) => (
          <option key={o.id} value={o.id}>
            {o.id ? `Group: ${o.label}` : o.label}
          </option>
        ))}
      </select>
      <ColumnPicker p={p} columns={columns} fields={fields} />
      <a
        href={csv}
        download
        className="inline-flex h-8 items-center gap-1.5 rounded-md px-2.5 text-sm text-muted hover:bg-surface-2 hover:text-ink"
      >
        <Icon icon={Download} size={14} /> Export CSV
      </a>
    </div>
  );
}

function SaveView({
  p,
  view,
  onSave,
  onUpdate,
}: {
  p: PortfolioDetail;
  view: SavedView | null;
  onSave: (name: string, shared: boolean) => void;
  onUpdate: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [shared, setShared] = useState(false);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button size="sm" variant="ghost">
          <Icon icon={Save} size={14} /> Save view
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-72 space-y-2 p-3">
        {view && (!view.shared || p.can_edit) ? (
          <Button
            size="sm"
            variant="ghost"
            className="w-full justify-start"
            onClick={() => {
              onUpdate();
              setOpen(false);
            }}
          >
            Update “{view.name}”
          </Button>
        ) : null}
        <form
          aria-label="Save as a new view"
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (!name.trim()) return;
            onSave(name.trim(), shared);
            setName('');
            setOpen(false);
          }}
        >
          <Input
            aria-label="View name"
            placeholder="New view name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          {p.can_edit ? (
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={shared} onChange={(e) => setShared(e.target.checked)} />
              Share with everyone who sees this portfolio
            </label>
          ) : null}
          <Button type="submit" size="sm" disabled={!name.trim()}>
            Save
          </Button>
        </form>
      </PopoverContent>
    </Popover>
  );
}

/** Show, hide and reorder columns. Editors save the choice for everyone; others see it apply to
 * their own table only while the page is open (saved views remember filters, grouping and sort). */
function ColumnPicker({
  p,
  columns,
  fields,
}: {
  p: PortfolioDetail;
  columns: ColumnV2[];
  fields: Map<string, Field>;
}) {
  const { configure } = usePortfolioSettings(p.id);
  const [draft, setDraft] = useState<ColumnV2[] | null>(null);
  const list = draft ?? columns;
  const save = (next: ColumnV2[]) => {
    setDraft(next);
    if (p.can_edit)
      configure.mutate({
        columns: next.map((c) => ({ key: c.key, visible: c.visible, width: c.width ?? null })),
      });
  };
  const move = (i: number, dir: -1 | 1) => {
    const next = [...list];
    const [c] = next.splice(i, 1);
    next.splice(i + dir, 0, c!);
    save(next);
  };
  return (
    <Popover onOpenChange={(o) => !o && setDraft(null)}>
      <PopoverTrigger asChild>
        <Button size="sm" variant="ghost">
          <Icon icon={Columns3} size={14} /> Columns
        </Button>
      </PopoverTrigger>
      <PopoverContent className="max-h-96 w-72 overflow-auto p-2">
        {!p.can_edit ? (
          <p className="px-1 pb-2 text-xs text-muted">Only the portfolio’s editors can change its columns.</p>
        ) : null}
        <ul aria-label="Columns">
          {list.map((c, i) => (
            <li key={c.key} className="flex items-center gap-1.5 rounded px-1 py-0.5 hover:bg-surface-2">
              <label className="flex min-w-0 flex-1 items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={c.visible}
                  disabled={!p.can_edit || c.key === 'name'}
                  onChange={(e) =>
                    save(list.map((x) => (x.key === c.key ? { ...x, visible: e.target.checked } : x)))
                  }
                />
                <span className="truncate">{c.label}</span>
                {fieldOf(c.key, fields) ? <span className="text-xs text-muted-2">field</span> : null}
              </label>
              <IconButton
                icon={ChevronUp}
                label={`Move ${c.label} up`}
                size="icon-sm"
                disabled={!p.can_edit || i === 0}
                onClick={() => move(i, -1)}
              />
              <IconButton
                icon={ChevronDown}
                label={`Move ${c.label} down`}
                size="icon-sm"
                disabled={!p.can_edit || i === list.length - 1}
                onClick={() => move(i, 1)}
              />
            </li>
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  );
}

/** "Set field…" on the selected rows: one change, one undo. Rows you can't edit are skipped
 * (the toast says how many). */
function BulkBar({
  p,
  count,
  editable,
  fields,
  onDone,
}: {
  p: PortfolioDetail;
  count: number;
  editable: string[];
  fields: Field[];
  onDone: () => void;
}) {
  const bulk = useBulkSetField(p.id);
  const [fieldId, setFieldId] = useState('');
  const field = fields.find((f) => f.id === fieldId);
  const [value, setValue] = useState<unknown>(null);
  return (
    <div
      role="region"
      aria-label="Selected projects"
      className="flex flex-wrap items-center gap-2 rounded-lg border border-hairline bg-surface-2 px-3 py-2 text-sm"
    >
      <span className="font-medium">{count} selected</span>
      {editable.length < count ? (
        <span className="text-xs text-muted">({count - editable.length} you can’t edit)</span>
      ) : null}
      <label className="sr-only" htmlFor="bulk-field">
        Field to set
      </label>
      <select
        id="bulk-field"
        className={selectClass}
        value={fieldId}
        onChange={(e) => {
          setFieldId(e.target.value);
          setValue(null);
        }}
      >
        <option value="">Set field…</option>
        {fields.map((f) => (
          <option key={f.id} value={f.id}>
            {f.name}
          </option>
        ))}
      </select>
      {field ? <FieldValueEditor field={field} value={value} onChange={setValue} /> : null}
      <Button
        size="sm"
        disabled={!field || editable.length === 0 || bulk.isPending}
        onClick={() =>
          field &&
          bulk.mutate(
            { project_ids: [...editable], field_id: field.id, value },
            {
              onSuccess: () => {
                setFieldId('');
                onDone();
              },
            },
          )
        }
      >
        Apply
      </Button>
      <Button size="sm" variant="ghost" onClick={onDone}>
        Clear selection
      </Button>
    </div>
  );
}
