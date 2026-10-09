import { X } from 'lucide-react';
import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { PeoplePicker, usePeople } from '@/features/people';

/** One property of a pack's settings JSON Schema (pydantic `model_json_schema()`), with the
 * pack's UI hint in `ui` (spec §8.3). */
export interface SchemaProp {
  title?: string;
  description?: string;
  type?: string;
  default?: unknown;
  ui?: string;
  options?: string[];
  enum?: string[];
  minimum?: number;
  maximum?: number;
}

export interface SettingsSchema {
  properties?: Record<string, SchemaProp>;
}

type Values = Record<string, unknown>;

/** The hint, else one inferred from the JSON type. */
export function widgetOf(p: SchemaProp): string {
  if (p.ui) return p.ui;
  if (p.enum) return 'enum';
  if (p.type === 'boolean') return 'bool';
  if (p.type === 'integer') return 'int';
  if (p.type === 'number') return 'number';
  if (p.type === 'string') return 'text';
  return 'json';
}

/**
 * The settings form generated from a JSON Schema (spec §12.2). It edits one level (the workspace,
 * or one project): each field shows this level's own value, or the inherited one greyed with
 * "inherited"; "Use inherited" drops this level's value so it falls back again. Nothing is saved
 * until Save; the server validates the whole model.
 */
export function SchemaForm({
  schema,
  own,
  effective,
  canEdit,
  saving,
  onSave,
  inheritLabel,
}: {
  schema: SettingsSchema;
  own: Values;
  effective: Values;
  canEdit: boolean;
  saving: boolean;
  onSave: (values: Values) => void;
  inheritLabel: string;
}) {
  const [draft, setDraft] = useState<Values>(own);
  const props = Object.entries(schema.properties ?? {});
  const dirty = JSON.stringify(draft) !== JSON.stringify(own);
  return (
    <form
      aria-label="Settings form"
      className="flex flex-col gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        onSave(draft);
      }}
    >
      {props.map(([key, p]) => {
        const set = key in draft;
        const value = set ? draft[key] : effective[key];
        return (
          <fieldset key={key} className="flex flex-col gap-1" disabled={!canEdit}>
            <legend className="text-sm font-medium">{p.title ?? key}</legend>
            {p.description ? <p className="text-xs text-muted">{p.description}</p> : null}
            <Widget
              id={`setting-${key}`}
              label={p.title ?? key}
              prop={p}
              value={value}
              onChange={(v) => setDraft((d) => ({ ...d, [key]: v }))}
            />
            <p className="text-xs text-muted-2">
              {set ? (
                canEdit ? (
                  <button
                    type="button"
                    className="text-accent hover:underline"
                    onClick={() =>
                      setDraft((d) => {
                        const next = { ...d };
                        delete next[key];
                        return next;
                      })
                    }
                  >
                    Use {inheritLabel}
                  </button>
                ) : (
                  'Set here'
                )
              ) : (
                `Inherited (${inheritLabel})`
              )}
            </p>
          </fieldset>
        );
      })}
      {canEdit ? (
        <div className="flex gap-2">
          <Button type="submit" variant="primary" size="sm" disabled={!dirty} loading={saving}>
            Save
          </Button>
          {dirty ? (
            <Button type="button" variant="text" size="sm" onClick={() => setDraft(own)}>
              Discard changes
            </Button>
          ) : null}
        </div>
      ) : null}
    </form>
  );
}

const INPUT = 'h-8 rounded-md border border-hairline bg-surface px-2 text-sm text-ink disabled:opacity-60';

function Widget({
  id,
  label,
  prop,
  value,
  onChange,
}: {
  id: string;
  label: string;
  prop: SchemaProp;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  switch (widgetOf(prop)) {
    case 'bool':
      return (
        <label className="flex items-center gap-2 text-sm">
          <input id={id} type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} />
          {value ? 'On' : 'Off'}
        </label>
      );
    case 'int':
    case 'number':
      return (
        <input
          id={id}
          aria-label={label}
          type="number"
          step={widgetOf(prop) === 'int' ? 1 : 'any'}
          min={prop.minimum}
          max={prop.maximum}
          className={`${INPUT} w-40`}
          value={value == null ? '' : String(value)}
          onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}
        />
      );
    case 'percent':
      return (
        <span className="flex items-center gap-1">
          <input
            id={id}
            aria-label={`${label} (percent)`}
            type="number"
            min={0}
            max={100}
            step="any"
            className={`${INPUT} w-28`}
            value={value == null ? '' : String(Math.round(Number(value) * 10_000) / 100)}
            onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value) / 100)}
          />
          <span className="text-sm text-muted">%</span>
        </span>
      );
    case 'enum': {
      const options = prop.options ?? prop.enum ?? [];
      return (
        <select
          id={id}
          aria-label={label}
          className={`${INPUT} w-fit`}
          value={String(value ?? '')}
          onChange={(e) => onChange(e.target.value)}
        >
          {options.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      );
    }
    case 'people':
      return <PeopleField label={label} value={(value as string[] | null) ?? []} onChange={onChange} />;
    case 'text_list':
      return <TextListField label={label} value={(value as string[] | null) ?? []} onChange={onChange} />;
    case 'money_by_currency':
      return (
        <MoneyByCurrency
          label={label}
          value={(value as Record<string, string | number> | null) ?? {}}
          onChange={onChange}
        />
      );
    case 'text':
      return (
        <input
          id={id}
          aria-label={label}
          className={INPUT}
          value={String(value ?? '')}
          onChange={(e) => onChange(e.target.value)}
        />
      );
    default:
      return <JsonField id={id} label={label} value={value} onChange={onChange} />;
  }
}

function PeopleField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string[];
  onChange: (v: string[]) => void;
}) {
  const people = usePeople('').data ?? [];
  const name = (id: string) => people.find((p) => p.id === id)?.name ?? 'Former member';
  return (
    <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label={label}>
      {value.map((id) => (
        <span
          key={id}
          className="flex items-center gap-1 rounded-full border border-hairline px-2 py-0.5 text-sm"
        >
          {name(id)}
          <button
            type="button"
            aria-label={`Remove ${name(id)}`}
            className="text-muted hover:text-ink"
            onClick={() => onChange(value.filter((v) => v !== id))}
          >
            <Icon icon={X} size={12} />
          </button>
        </span>
      ))}
      {!value.length ? <span className="text-sm text-muted">Nobody yet</span> : null}
      <PeoplePicker exclude={value} onSelect={(p) => onChange([...value, p.id])}>
        <Button type="button" size="sm" variant="text">
          Add person
        </Button>
      </PeoplePicker>
    </div>
  );
}

function TextListField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string[];
  onChange: (v: string[]) => void;
}) {
  const [next, setNext] = useState('');
  const add = () => {
    const t = next.trim();
    if (t && !value.includes(t)) onChange([...value, t]);
    setNext('');
  };
  return (
    <div className="flex flex-col gap-1.5" role="group" aria-label={label}>
      {value.length ? (
        <ul className="flex flex-wrap gap-1.5">
          {value.map((t) => (
            <li
              key={t}
              className="flex items-center gap-1 rounded-full border border-hairline px-2 py-0.5 text-sm"
            >
              {t}
              <button
                type="button"
                aria-label={`Remove ${t}`}
                className="text-muted hover:text-ink"
                onClick={() => onChange(value.filter((v) => v !== t))}
              >
                <Icon icon={X} size={12} />
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <span className="flex gap-1.5">
        <input
          aria-label={`Add to ${label}`}
          className={`${INPUT} w-56`}
          value={next}
          onChange={(e) => setNext(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              add();
            }
          }}
        />
        <Button type="button" size="sm" variant="text" onClick={add} disabled={!next.trim()}>
          Add
        </Button>
      </span>
    </div>
  );
}

/** Amounts per currency (spec §9.7 `materiality`): one row per currency, never mixed. */
function MoneyByCurrency({
  label,
  value,
  onChange,
}: {
  label: string;
  value: Record<string, string | number>;
  onChange: (v: Record<string, string>) => void;
}) {
  const [currency, setCurrency] = useState('');
  const rows = Object.entries(value);
  const asStrings = (v: Record<string, string | number>) =>
    Object.fromEntries(Object.entries(v).map(([k, x]) => [k, String(x)]));
  return (
    <div className="flex flex-col gap-1.5" role="group" aria-label={label}>
      {rows.map(([cur, amount]) => (
        <span key={cur} className="flex items-center gap-1.5">
          <span className="w-12 font-mono text-sm">{cur}</span>
          <input
            aria-label={`${label} in ${cur}`}
            inputMode="decimal"
            className={`${INPUT} w-36 text-right tabular`}
            value={String(amount)}
            onChange={(e) => onChange({ ...asStrings(value), [cur]: e.target.value })}
          />
          <button
            type="button"
            aria-label={`Remove ${cur}`}
            className="text-muted hover:text-ink"
            onClick={() => {
              const next = asStrings(value);
              delete next[cur];
              onChange(next);
            }}
          >
            <Icon icon={X} size={12} />
          </button>
        </span>
      ))}
      <span className="flex items-center gap-1.5">
        <input
          aria-label={`Currency to add to ${label}`}
          placeholder="EUR"
          maxLength={3}
          className={`${INPUT} w-16 uppercase`}
          value={currency}
          onChange={(e) => setCurrency(e.target.value.toUpperCase())}
        />
        <Button
          type="button"
          size="sm"
          variant="text"
          disabled={!/^[A-Z]{3}$/.test(currency) || currency in value}
          onClick={() => {
            onChange({ ...asStrings(value), [currency]: '0' });
            setCurrency('');
          }}
        >
          Add currency
        </Button>
      </span>
    </div>
  );
}

function JsonField({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  label: string;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  const [text, setText] = useState(() => JSON.stringify(value ?? null, null, 2));
  const [bad, setBad] = useState(false);
  return (
    <span className="flex flex-col gap-0.5">
      <textarea
        id={id}
        aria-label={`${label} (JSON)`}
        rows={4}
        className="rounded-md border border-hairline bg-surface p-2 font-mono text-xs"
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          try {
            onChange(JSON.parse(e.target.value));
            setBad(false);
          } catch {
            setBad(true);
          }
        }}
      />
      {bad ? <span className="text-xs text-crit">Not valid JSON yet</span> : null}
    </span>
  );
}
