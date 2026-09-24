import { Check } from 'lucide-react';
import { useState } from 'react';
import { Avatar } from '@/components/ui/Avatar';
import { Calendar } from '@/components/common/Calendar';
import { Icon } from '@/components/ui/Icon';
import { Input } from '@/components/ui/Input';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/Popover';
import { usePeople } from '@/features/people';
import { formatDay } from '@/lib/dates';
import { cn } from '@/lib/cn';
import type { Field, SelectOption } from './queries';

const EMPTY = '—';

function optionsOf(field: Field): SelectOption[] {
  return Array.isArray(field.options) ? field.options : [];
}

/** A compact display of a field's current value on a task, for a list/board chip: read-only, no
 * editor — click opens the task instead (matches how due-date/assignee already work in the
 * list). The pane's own editor (below) is where values actually get changed. */
export function FieldValueChip({ field, value }: { field: Field; value: unknown }) {
  if (value === null || value === undefined || (Array.isArray(value) && value.length === 0)) return null;
  if (field.type === 'checkbox') {
    return value ? (
      <span className="inline-flex items-center gap-0.5 text-xs text-ok">
        <Icon icon={Check} size={12} /> {field.name}
      </span>
    ) : null;
  }
  if (field.type === 'single_select' || field.type === 'multi_select') {
    const ids = field.type === 'single_select' ? [value as string] : (value as string[]);
    const opts = optionsOf(field).filter((o) => ids.includes(o.id));
    if (!opts.length) return null;
    return (
      <span className="inline-flex items-center gap-1">
        {opts.map((o) => (
          <span
            key={o.id}
            className="inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[11px]"
            style={{ background: `${o.color}26`, color: o.color }}
          >
            {o.label}
          </span>
        ))}
      </span>
    );
  }
  if (field.type === 'date') {
    return <span className="text-xs text-muted">{formatDay(value as string)}</span>;
  }
  if (field.type === 'people') {
    return (
      <span className="inline-flex -space-x-1">
        {(value as string[]).slice(0, 3).map((id) => (
          <PersonAvatar key={id} id={id} />
        ))}
      </span>
    );
  }
  const opts =
    field.type === 'number' || field.type === 'currency' || field.type === 'percent'
      ? (field.options as { unit?: string | null } | null)
      : null;
  const suffix = field.type === 'percent' ? '%' : opts?.unit ? ` ${opts.unit}` : '';
  return (
    <span className="truncate text-xs text-muted" title={field.name}>
      {String(value)}
      {suffix}
    </span>
  );
}

function PersonAvatar({ id }: { id: string }) {
  const people = usePeople().data;
  const person = people?.find((p) => p.id === id);
  return (
    <Avatar name={person?.name ?? '?'} src={person?.avatar_url} size={18} className="ring-2 ring-canvas" />
  );
}

/** Inline editor for one field's value on a task, per type. Used in the pane's Fields section. */
export function FieldValueEditor({
  field,
  value,
  onChange,
  disabled,
}: {
  field: Field;
  value: unknown;
  onChange: (v: unknown) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);

  if (field.type === 'checkbox') {
    return (
      <button
        type="button"
        role="checkbox"
        aria-checked={!!value}
        aria-label={field.name}
        disabled={disabled}
        onClick={() => onChange(!value)}
        className={cn(
          'flex h-7 w-7 items-center justify-center rounded-md border',
          value ? 'border-ok bg-ok/10 text-ok' : 'border-hairline text-transparent',
        )}
      >
        <Icon icon={Check} size={14} />
      </button>
    );
  }

  if (field.type === 'text' || field.type === 'url') {
    return (
      <TextEditor
        label={field.name}
        value={(value as string | null) ?? ''}
        onCommit={(v) => onChange(v.trim() || null)}
        disabled={disabled}
      />
    );
  }

  if (field.type === 'number' || field.type === 'currency' || field.type === 'percent') {
    return (
      <TextEditor
        label={field.name}
        type="number"
        value={value === null || value === undefined ? '' : String(value)}
        onCommit={(v) => onChange(v.trim() === '' ? null : Number(v))}
        disabled={disabled}
      />
    );
  }

  if (field.type === 'date') {
    return (
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <button
            type="button"
            aria-label={`${field.name}: ${value ? formatDay(value as string) : 'empty'}`}
            disabled={disabled}
            className="h-7 rounded-md border border-hairline px-2 text-left text-sm hover:bg-surface-2 disabled:pointer-events-none"
          >
            {value ? formatDay(value as string) : <span className="text-muted-2">{EMPTY}</span>}
          </button>
        </PopoverTrigger>
        <PopoverContent>
          <Calendar
            selected={(value as string | null) ?? null}
            onSelect={(iso) => {
              onChange(iso);
              setOpen(false);
            }}
          />
        </PopoverContent>
      </Popover>
    );
  }

  if (field.type === 'single_select' || field.type === 'multi_select') {
    const opts = optionsOf(field).filter((o) => !o.archived);
    const selected = new Set(
      field.type === 'single_select' ? [value].filter(Boolean) : ((value as string[]) ?? []),
    );
    return (
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <button
            type="button"
            aria-label={field.name}
            disabled={disabled}
            className="flex h-7 min-w-[3rem] items-center gap-1 rounded-md border border-hairline px-2 text-sm hover:bg-surface-2 disabled:pointer-events-none"
          >
            {selected.size ? (
              opts
                .filter((o) => selected.has(o.id))
                .map((o) => (
                  <span
                    key={o.id}
                    className="rounded-full px-1.5 text-[11px]"
                    style={{ background: `${o.color}26`, color: o.color }}
                  >
                    {o.label}
                  </span>
                ))
            ) : (
              <span className="text-muted-2">{EMPTY}</span>
            )}
          </button>
        </PopoverTrigger>
        <PopoverContent className="w-48 p-1">
          <ul
            role="listbox"
            aria-label={`${field.name} options`}
            aria-multiselectable={field.type === 'multi_select'}
          >
            {opts.map((o) => (
              <li key={o.id}>
                <button
                  type="button"
                  role="option"
                  aria-selected={selected.has(o.id)}
                  onClick={() => {
                    if (field.type === 'single_select') {
                      onChange(selected.has(o.id) ? null : o.id);
                      setOpen(false);
                    } else {
                      const next = new Set(selected);
                      if (next.has(o.id)) next.delete(o.id);
                      else next.add(o.id);
                      onChange([...next]);
                    }
                  }}
                  className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-surface-2"
                >
                  <span aria-hidden className="h-2.5 w-2.5 rounded-full" style={{ background: o.color }} />
                  <span className="flex-1 truncate">{o.label}</span>
                  {selected.has(o.id) ? <Icon icon={Check} size={14} /> : null}
                </button>
              </li>
            ))}
          </ul>
        </PopoverContent>
      </Popover>
    );
  }

  if (field.type === 'people') {
    const selected = new Set((value as string[] | null) ?? []);
    return (
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <button
            type="button"
            aria-label={field.name}
            disabled={disabled}
            className="flex h-7 items-center gap-1 rounded-md border border-hairline px-2 hover:bg-surface-2 disabled:pointer-events-none"
          >
            {selected.size ? (
              <span className="inline-flex -space-x-1">
                {[...selected].slice(0, 4).map((id) => (
                  <PersonAvatar key={id} id={id} />
                ))}
              </span>
            ) : (
              <span className="text-sm text-muted-2">{EMPTY}</span>
            )}
          </button>
        </PopoverTrigger>
        <PopoverContent className="w-56 p-1">
          <PeopleList
            label={field.name}
            selected={selected}
            onToggle={(id) => {
              const next = new Set(selected);
              if (next.has(id)) next.delete(id);
              else next.add(id);
              onChange([...next]);
            }}
          />
        </PopoverContent>
      </Popover>
    );
  }

  return null;
}

function PeopleList({
  label,
  selected,
  onToggle,
}: {
  label: string;
  selected: Set<string>;
  onToggle: (id: string) => void;
}) {
  const people = usePeople().data ?? [];
  return (
    <ul role="listbox" aria-label={`${label} people`} aria-multiselectable className="max-h-56 overflow-auto">
      {people.map((p) => (
        <li key={p.id}>
          <button
            type="button"
            role="option"
            aria-selected={selected.has(p.id)}
            onClick={() => onToggle(p.id)}
            className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-surface-2"
          >
            <Avatar name={p.name} src={p.avatar_url} size={20} />
            <span className="flex-1 truncate">{p.name}</span>
            {selected.has(p.id) ? <Icon icon={Check} size={14} /> : null}
          </button>
        </li>
      ))}
    </ul>
  );
}

function TextEditor({
  label,
  value,
  onCommit,
  type = 'text',
  disabled,
}: {
  label: string;
  value: string;
  onCommit: (v: string) => void;
  type?: 'text' | 'number';
  disabled?: boolean;
}) {
  const [draft, setDraft] = useState(value);
  const [editing, setEditing] = useState(false);
  return (
    <Input
      aria-label={label}
      type={type}
      value={editing ? draft : value}
      disabled={disabled}
      onFocus={() => {
        setDraft(value);
        setEditing(true);
      }}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => {
        setEditing(false);
        if (draft !== value) onCommit(draft);
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter') e.currentTarget.blur();
        if (e.key === 'Escape') {
          setDraft(value);
          e.currentTarget.blur();
        }
      }}
      className="h-7 w-full text-sm"
    />
  );
}
