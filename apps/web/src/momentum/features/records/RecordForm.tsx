import { ArrowDown, ArrowUp, Plus, Trash2 } from 'lucide-react';
import type { KeyboardEvent } from 'react';
import { Button } from '@/components/ui/Button';
import { IconButton } from '@/components/ui/IconButton';
import { cn } from '@/lib/cn';
import { getPath, sumMoney, type ArraySpec, type FieldSpec, type FormSpec, type Prov } from './model';

export const fieldId = (path: string) => `rf-${path.replace(/[^a-z0-9]/gi, '-')}`;

const INPUT =
  'h-8 w-full min-w-0 rounded-md border border-hairline bg-surface px-2 text-sm text-ink disabled:bg-surface-2 disabled:text-ink-2';

function display(v: unknown): string {
  return v == null ? '' : String(v);
}

function parse(kind: FieldSpec['kind'], raw: string | boolean): unknown {
  if (kind === 'bool') return raw;
  const s = String(raw);
  if (kind === 'number') return s.trim() === '' ? null : Number(s);
  if (kind === 'money') return s.trim() === '' ? null : s.replace(/,/g, '').trim();
  if (kind === 'currency') return s.toUpperCase();
  return s;
}

function ProvHint({ prov }: { prov?: Prov }) {
  if (!prov?.method) return null;
  const by =
    prov.method === 'human'
      ? 'Set by a person'
      : `${prov.method}${prov.confidence != null ? ` · ${Math.round(prov.confidence * 100)}%` : ''}`;
  return (
    <span className={cn('text-[11px]', prov.method === 'human' ? 'text-muted' : 'text-amber-ink')}>{by}</span>
  );
}

/**
 * The record form (spec §12.4), generated from the type: header fields, then each list as a grid
 * (keyboard: ↑/↓ move between rows in the same column; Alt+↑/↓ move the row), with a totals row
 * for money columns. Focusing a field makes it the active one (its box lights up in the viewer).
 */
export function RecordForm({
  spec,
  data,
  provenance,
  canEdit,
  active,
  onActive,
  onSet,
  onAdd,
  onRemove,
  onMove,
  currency,
}: {
  spec: FormSpec;
  data: Record<string, unknown>;
  provenance: Record<string, Prov>;
  canEdit: boolean;
  active: string | null;
  onActive: (path: string) => void;
  onSet: (path: string, value: unknown) => void;
  onAdd: (array: string, columns: FieldSpec[]) => void;
  onRemove: (array: string, index: number) => void;
  onMove: (array: string, from: number, to: number) => void;
  currency: string | null;
}) {
  return (
    <div className="flex flex-col gap-5">
      <div className="grid gap-x-3 gap-y-2 sm:grid-cols-2">
        {spec.fields.map((f) => (
          <label
            key={f.path}
            htmlFor={fieldId(f.path)}
            className={cn(
              'flex flex-col gap-0.5 rounded-md px-1 py-0.5 text-xs text-muted',
              active === f.path && 'bg-amber-2/60 ring-1 ring-amber',
            )}
          >
            <span className="flex items-baseline justify-between gap-2">
              <span>
                {f.label}
                {f.required ? '' : ' (optional)'}
              </span>
              <ProvHint prov={provenance[f.path]} />
            </span>
            <Field
              id={fieldId(f.path)}
              spec={f}
              value={getPath(data, f.path)}
              disabled={!canEdit}
              onFocus={() => onActive(f.path)}
              onChange={(v) => onSet(f.path, v)}
            />
          </label>
        ))}
      </div>
      {spec.arrays.map((a) => (
        <ArrayGrid
          key={a.path}
          spec={a}
          rows={(getPath(data, a.path) as Record<string, unknown>[] | undefined) ?? []}
          provenance={provenance}
          canEdit={canEdit}
          active={active}
          currency={currency}
          onActive={onActive}
          onSet={onSet}
          onAdd={() => onAdd(a.path, a.columns)}
          onRemove={(i) => onRemove(a.path, i)}
          onMove={(from, to) => onMove(a.path, from, to)}
        />
      ))}
    </div>
  );
}

function Field({
  id,
  spec,
  value,
  disabled,
  onFocus,
  onChange,
  label,
  onKeyDown,
}: {
  id: string;
  spec: FieldSpec;
  value: unknown;
  disabled: boolean;
  onFocus: () => void;
  onChange: (v: unknown) => void;
  label?: string;
  onKeyDown?: (e: KeyboardEvent<HTMLInputElement>) => void;
}) {
  if (spec.kind === 'bool')
    return (
      <input
        id={id}
        type="checkbox"
        aria-label={label}
        checked={!!value}
        disabled={disabled}
        onFocus={onFocus}
        onChange={(e) => onChange(parse('bool', e.target.checked))}
      />
    );
  return (
    <input
      id={id}
      aria-label={label}
      type={spec.kind === 'date' ? 'date' : 'text'}
      inputMode={spec.kind === 'money' || spec.kind === 'number' ? 'decimal' : undefined}
      maxLength={spec.kind === 'currency' ? 3 : undefined}
      className={cn(INPUT, (spec.kind === 'money' || spec.kind === 'number') && 'text-right tabular-nums')}
      value={display(value)}
      disabled={disabled}
      onFocus={onFocus}
      onKeyDown={onKeyDown}
      onChange={(e) => onChange(parse(spec.kind, e.target.value))}
    />
  );
}

function ArrayGrid({
  spec,
  rows,
  provenance,
  canEdit,
  active,
  currency,
  onActive,
  onSet,
  onAdd,
  onRemove,
  onMove,
}: {
  spec: ArraySpec;
  rows: Record<string, unknown>[];
  provenance: Record<string, Prov>;
  canEdit: boolean;
  active: string | null;
  currency: string | null;
  onActive: (path: string) => void;
  onSet: (path: string, value: unknown) => void;
  onAdd: () => void;
  onRemove: (index: number) => void;
  onMove: (from: number, to: number) => void;
}) {
  const cellPath = (i: number, col: string) => `${spec.path}[${i}].${col}`;
  const focusCell = (i: number, col: string) =>
    requestAnimationFrame(() => document.getElementById(fieldId(cellPath(i, col)))?.focus());
  const onKey = (e: KeyboardEvent<HTMLInputElement>, i: number, col: string) => {
    if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
      const to = e.key === 'ArrowUp' ? i - 1 : i + 1;
      if (to < 0 || to >= rows.length) return;
      e.preventDefault();
      if (e.altKey && canEdit) onMove(i, to);
      focusCell(to, col);
    }
  };
  const money = spec.columns.filter((c) => c.kind === 'money');
  return (
    <section aria-label={spec.label} className="flex flex-col gap-1.5">
      <h3 className="section-label">
        {spec.label} <span className="font-normal text-muted">({rows.length})</span>
      </h3>
      <div className="overflow-x-auto rounded-md border border-hairline">
        <table role="grid" aria-label={`${spec.label} grid`} className="w-full text-sm">
          <thead>
            <tr className="bg-surface-2 text-left text-xs text-muted">
              <th scope="col" className="w-8 px-2 py-1 font-normal">
                #
              </th>
              {spec.columns.map((c) => (
                <th
                  key={c.path}
                  scope="col"
                  className={cn('px-1 py-1 font-normal', c.kind === 'money' && 'text-right')}
                >
                  {c.label}
                </th>
              ))}
              {canEdit ? (
                <th scope="col" className="w-24 px-1 py-1 font-normal">
                  <span className="sr-only">Row actions</span>
                </th>
              ) : null}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i} className="border-t border-hair-soft">
                <td className="px-2 text-xs text-muted tabular-nums">{i + 1}</td>
                {spec.columns.map((c) => {
                  const path = cellPath(i, c.path);
                  return (
                    <td
                      key={c.path}
                      className={cn('px-1 py-0.5', active === path && 'bg-amber-2/60')}
                      title={provenance[path]?.method ? `Read by ${provenance[path]!.method}` : undefined}
                    >
                      <Field
                        id={fieldId(path)}
                        label={`${c.label}, row ${i + 1}`}
                        spec={c}
                        value={row[c.path]}
                        disabled={!canEdit}
                        onFocus={() => onActive(path)}
                        onKeyDown={(e) => onKey(e, i, c.path)}
                        onChange={(v) => onSet(path, v)}
                      />
                    </td>
                  );
                })}
                {canEdit ? (
                  <td className="whitespace-nowrap px-1">
                    <IconButton
                      icon={ArrowUp}
                      size="icon-sm"
                      label={`Move row ${i + 1} up`}
                      disabled={i === 0}
                      onClick={() => onMove(i, i - 1)}
                    />
                    <IconButton
                      icon={ArrowDown}
                      size="icon-sm"
                      label={`Move row ${i + 1} down`}
                      disabled={i === rows.length - 1}
                      onClick={() => onMove(i, i + 1)}
                    />
                    <IconButton
                      icon={Trash2}
                      size="icon-sm"
                      label={`Remove row ${i + 1}`}
                      onClick={() => onRemove(i)}
                    />
                  </td>
                ) : null}
              </tr>
            ))}
            {!rows.length ? (
              <tr>
                <td colSpan={spec.columns.length + 2} className="px-2 py-3 text-center text-xs text-muted">
                  No {spec.label.toLowerCase()} yet.
                </td>
              </tr>
            ) : null}
          </tbody>
          {money.length && rows.length ? (
            <tfoot>
              <tr className="border-t border-hairline bg-surface-2 text-xs">
                <th scope="row" className="px-2 py-1 text-left font-medium">
                  Total
                </th>
                {spec.columns.map((c) => {
                  const total = c.kind === 'money' ? sumMoney(rows.map((r) => r[c.path])) : null;
                  return (
                    <td key={c.path} className="px-2 py-1 text-right tabular-nums">
                      {c.kind === 'money'
                        ? total === null
                          ? 'Check the amounts'
                          : `${total}${currency ? ` ${currency}` : ''}`
                        : null}
                    </td>
                  );
                })}
                {canEdit ? <td /> : null}
              </tr>
            </tfoot>
          ) : null}
        </table>
      </div>
      {canEdit ? (
        <Button size="sm" variant="text" className="w-fit" onClick={onAdd}>
          <Plus size={13} aria-hidden /> Add a row
        </Button>
      ) : null}
    </section>
  );
}
