import { X } from 'lucide-react';
import { useMemo } from 'react';
import { Icon } from '@/components/ui/Icon';
import type { Field } from './queries';
import {
  describeFieldFilter,
  fieldFilterText,
  LISTED,
  NUMERIC,
  parseFieldFilter,
  type FieldFilter,
  type FieldOp,
} from './filters';
import { usePeople } from '@/features/people';
import { cn } from '@/lib/cn';

/**
 * S7.4.1: the "Custom fields" part of a Filter popover. Each field folds open to the controls its
 * type takes (options, people, a checkbox, a number or date range, text to look for, set/empty).
 * Filters are the `<field id>:<op>[:<arg>]` texts the view keeps (and the API understands).
 */
export function FieldFilterSection({
  fields,
  value,
  onChange,
}: {
  fields: readonly Field[];
  value: readonly string[];
  onChange: (next: string[]) => void;
}) {
  const parsed = useMemo(
    () => value.map(parseFieldFilter).filter((f): f is FieldFilter => f !== null),
    [value],
  );
  const people = usePeople('', 'all').data ?? [];
  if (!fields.length) return null;

  const of = (fieldId: string, op: FieldOp) => parsed.find((f) => f.fieldId === fieldId && f.op === op);
  const put = (fieldId: string, op: FieldOp, next: FieldFilter | null, clear: FieldOp[] = []) => {
    const kept = parsed.filter((f) => !(f.fieldId === fieldId && (f.op === op || clear.includes(f.op))));
    onChange([...kept, ...(next ? [next] : [])].map(fieldFilterText));
  };
  const toggleValue = (fieldId: string, v: string) => {
    const cur = of(fieldId, 'any')?.values ?? [];
    const values = cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v];
    put(fieldId, 'any', values.length ? { fieldId, op: 'any', values, value: null } : null, ['set', 'empty']);
  };
  const setBound = (fieldId: string, op: 'min' | 'max' | 'has', raw: string) =>
    put(fieldId, op, raw.trim() ? { fieldId, op, values: [], value: raw } : null, ['set', 'empty']);
  const setPresence = (fieldId: string, op: 'set' | 'empty') =>
    of(fieldId, op)
      ? put(fieldId, op, null)
      : onChange([
          ...parsed.filter((f) => f.fieldId !== fieldId).map(fieldFilterText),
          fieldFilterText({ fieldId, op, values: [], value: null }),
        ]);

  const chip = (on: boolean, label: string, onClick: () => void, key: string) => (
    <button
      key={key}
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={cn(
        'h-7 rounded-md px-2 text-xs',
        on ? 'bg-accent text-on-accent' : 'bg-surface-2 text-ink-2 hover:bg-accent-tint',
      )}
    >
      {label}
    </button>
  );
  const inputClass =
    'h-7 w-full min-w-0 rounded-md border border-hairline bg-surface px-2 text-xs outline-none focus:border-focus';

  return (
    <fieldset className="mt-2 border-t border-hair-soft pt-2">
      <legend className="section-label px-2 pb-1">Custom fields</legend>
      <div className="max-h-64 overflow-auto">
        {fields.map((field) => {
          const active = parsed.filter((f) => f.fieldId === field.id);
          const options = Array.isArray(field.options) ? field.options.filter((o) => !o.archived) : [];
          const picked = of(field.id, 'any')?.values ?? [];
          return (
            <details key={field.id} open={active.length > 0} className="rounded-md px-2 py-1">
              <summary className="cursor-pointer text-sm">
                {field.name}
                {active.length ? <span className="ml-1 text-xs text-muted">· {active.length}</span> : null}
              </summary>
              <div
                role="group"
                aria-label={`Filter by ${field.name}`}
                className="mt-1 flex flex-wrap items-center gap-1"
              >
                {field.type === 'single_select' || field.type === 'multi_select'
                  ? options.map((o) =>
                      chip(picked.includes(o.id), o.label, () => toggleValue(field.id, o.id), o.id),
                    )
                  : null}
                {field.type === 'checkbox'
                  ? [
                      chip(picked.includes('true'), 'Checked', () => toggleValue(field.id, 'true'), 'true'),
                      chip(
                        picked.includes('false'),
                        'Not checked',
                        () => toggleValue(field.id, 'false'),
                        'false',
                      ),
                    ]
                  : null}
                {field.type === 'people' ? (
                  <>
                    {picked
                      .filter((v) => v !== 'none')
                      .map((v) =>
                        chip(
                          true,
                          people.find((p) => p.id === v)?.name ?? 'Someone',
                          () => toggleValue(field.id, v),
                          v,
                        ),
                      )}
                    <select
                      aria-label={`Add a person to the ${field.name} filter`}
                      value=""
                      onChange={(e) => e.target.value && toggleValue(field.id, e.target.value)}
                      className={cn(inputClass, 'w-auto')}
                    >
                      <option value="">Add person…</option>
                      {people
                        .filter((p) => !picked.includes(p.id))
                        .map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.name}
                          </option>
                        ))}
                    </select>
                  </>
                ) : null}
                {LISTED.includes(field.type)
                  ? chip(picked.includes('none'), 'No value', () => toggleValue(field.id, 'none'), 'none')
                  : null}
                {NUMERIC.includes(field.type) || field.type === 'date' ? (
                  <div className="grid w-full grid-cols-2 gap-1">
                    {(['min', 'max'] as const).map((op) => (
                      <input
                        key={`${op}:${of(field.id, op)?.value ?? ''}`} // reset when removed elsewhere
                        type={field.type === 'date' ? 'date' : 'number'}
                        aria-label={`${field.name} ${op === 'min' ? 'at least' : 'at most'}`}
                        placeholder={op === 'min' ? 'From' : 'To'}
                        defaultValue={of(field.id, op)?.value ?? ''}
                        onBlur={(e) => setBound(field.id, op, e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && setBound(field.id, op, e.currentTarget.value)}
                        className={inputClass}
                      />
                    ))}
                  </div>
                ) : null}
                {field.type === 'text' || field.type === 'url' ? (
                  <input
                    key={of(field.id, 'has')?.value ?? ''}
                    aria-label={`${field.name} contains`}
                    placeholder="Contains…"
                    defaultValue={of(field.id, 'has')?.value ?? ''}
                    onBlur={(e) => setBound(field.id, 'has', e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && setBound(field.id, 'has', e.currentTarget.value)}
                    className={inputClass}
                  />
                ) : null}
                {!LISTED.includes(field.type) && field.type !== 'checkbox' ? (
                  <>
                    {chip(!!of(field.id, 'set'), 'Has a value', () => setPresence(field.id, 'set'), 'set')}
                    {chip(!!of(field.id, 'empty'), 'Empty', () => setPresence(field.id, 'empty'), 'empty')}
                  </>
                ) : null}
              </div>
            </details>
          );
        })}
      </div>
    </fieldset>
  );
}

/** The active field filters as removable chips under the toolbar ("Stage: Ship ×"). */
export function FieldFilterChips({
  fields,
  value,
  onChange,
}: {
  fields: readonly Field[];
  value: readonly string[];
  onChange: (next: string[]) => void;
}) {
  const people = usePeople('', 'all').data ?? [];
  const byId = useMemo(() => new Map(fields.map((f) => [f.id, f])), [fields]);
  const parsed = value.map((t) => [t, parseFieldFilter(t)] as const).filter(([, f]) => f !== null);
  if (!parsed.length) return null;
  const nameOf = (id: string) => people.find((p) => p.id === id)?.name;
  return (
    <ul aria-label="Custom field filters" className="-mt-1 mb-3 flex flex-wrap gap-1">
      {parsed.map(([text, f]) => (
        <li key={text}>
          <button
            type="button"
            onClick={() => onChange(value.filter((v) => v !== text))}
            aria-label={`Remove filter: ${describeFieldFilter(f!, byId.get(f!.fieldId), nameOf)}`}
            className="inline-flex h-7 items-center gap-1 rounded-full bg-accent-tint px-2.5 text-xs text-ink hover:bg-surface-2"
          >
            {describeFieldFilter(f!, byId.get(f!.fieldId), nameOf)}
            <Icon icon={X} size={12} />
          </button>
        </li>
      ))}
    </ul>
  );
}
