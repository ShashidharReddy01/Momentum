import { ChevronDown, ChevronUp, Eye, EyeOff, MoreHorizontal, Plus, Trash2, X } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
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
import { InlineText } from '@/components/common/InlineText';
import {
  useFieldLibrary,
  useFieldMutations,
  useProjectFields,
  type FieldCreate,
  type FieldType,
  type ProjectField,
} from './queries';

const TYPE_LABEL: Record<FieldType, string> = {
  text: 'Text',
  number: 'Number',
  single_select: 'Single select',
  multi_select: 'Multi select',
  date: 'Date',
  people: 'People',
  checkbox: 'Checkbox',
  url: 'URL',
  currency: 'Currency',
  percent: 'Percent',
};
const TYPES = Object.keys(TYPE_LABEL) as FieldType[];
const SELECT_TYPES: FieldType[] = ['single_select', 'multi_select'];

/** S2.3.1: manage a project's custom fields — attach from the shared library, create new ones,
 * reorder, hide, remove from this project, or archive everywhere. Editing a field's type/options
 * once created, and using fields as list/board columns with inline editors, is S2.3.2 (the
 * fields exist and can be attached/valued via the API already — this dialog just doesn't have
 * that editor UI yet). */
export function FieldsDialog({
  projectId,
  canEdit,
  open,
  onOpenChange,
}: {
  projectId: string;
  canEdit: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const attached = useProjectFields(projectId, open);
  const library = useFieldLibrary(open);
  const m = useFieldMutations(projectId);
  const [adding, setAdding] = useState(false);

  const attachedIds = new Set((attached.data ?? []).map((f) => f.field.id));
  const available = (library.data ?? []).filter((f) => !attachedIds.has(f.id));

  const moveTo = (list: ProjectField[], index: number, dir: 1 | -1) => {
    const target = list[index + dir];
    const item = list[index];
    if (!target || !item) return;
    m.move.mutate(
      dir === 1
        ? { id: item.field.id, afterId: target.field.id }
        : { id: item.field.id, beforeId: target.field.id },
    );
  };

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Fields"
      className="w-[min(480px,calc(100vw-32px))]"
    >
      <div className="flex flex-col gap-4 p-5">
        {attached.isPending ? (
          <p className="text-sm text-muted">Loading…</p>
        ) : (
          <ul aria-label="Fields on this project" className="flex flex-col gap-1">
            {(attached.data ?? []).map((pf, i) => (
              <li
                key={pf.field.id}
                className="flex items-center gap-1.5 rounded-md px-1.5 py-1 hover:bg-surface-2"
              >
                <div className="flex flex-col">
                  <IconButton
                    icon={ChevronUp}
                    label={`Move ${pf.field.name} up`}
                    size="icon-sm"
                    disabled={!canEdit || i === 0}
                    onClick={() => moveTo(attached.data!, i, -1)}
                  />
                  <IconButton
                    icon={ChevronDown}
                    label={`Move ${pf.field.name} down`}
                    size="icon-sm"
                    disabled={!canEdit || i === attached.data!.length - 1}
                    onClick={() => moveTo(attached.data!, i, 1)}
                  />
                </div>
                <InlineText
                  aria-label="Field name"
                  value={pf.field.name}
                  disabled={!canEdit}
                  onCommit={(name) => m.update.mutate({ id: pf.field.id, patch: { name } })}
                  className="min-w-0 flex-1 text-sm"
                />
                <span className="text-xs text-muted-2">{TYPE_LABEL[pf.field.type]}</span>
                {canEdit ? (
                  <>
                    <IconButton
                      icon={pf.is_visible ? Eye : EyeOff}
                      label={pf.is_visible ? `Hide ${pf.field.name}` : `Show ${pf.field.name}`}
                      size="icon-sm"
                      onClick={() => m.setVisible.mutate({ id: pf.field.id, visible: !pf.is_visible })}
                    />
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <IconButton icon={MoreHorizontal} label={`${pf.field.name} actions`} size="icon-sm" />
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onSelect={() => m.detach.mutate(pf.field.id)}>
                          <Icon icon={X} /> Remove from this project
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                          className="text-crit"
                          onSelect={() => m.archive.mutate(pf.field.id)}
                        >
                          <Icon icon={Trash2} /> Archive everywhere
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </>
                ) : null}
              </li>
            ))}
            {attached.data?.length === 0 ? (
              <p className="px-1.5 py-1 text-sm text-muted">No fields on this project yet.</p>
            ) : null}
          </ul>
        )}

        {canEdit ? (
          adding ? (
            <NewFieldForm
              onCancel={() => setAdding(false)}
              onCreate={(v) => {
                // `color`/`archived` on each option, and `is_library`, all have server-side
                // defaults (Pydantic), but the generated types still mark them required — a
                // known openapi-typescript quirk for fields with defaults, not a real API
                // requirement. Casting here rather than fabricating values (which would also
                // need a literal color, blocked by the design-token lint rule) keeps this
                // honest about which fields the user actually chose.
                m.create.mutate({ ...v, is_library: true } as FieldCreate);
                setAdding(false);
              }}
            />
          ) : (
            <div className="flex flex-col gap-2 border-t border-hair-soft pt-3">
              <Button size="sm" variant="ghost" className="justify-start" onClick={() => setAdding(true)}>
                <Icon icon={Plus} /> New field
              </Button>
              {available.length ? (
                <div className="flex flex-col gap-1">
                  <span className="section-label px-0.5">From the library</span>
                  {available.map((f) => (
                    <button
                      key={f.id}
                      type="button"
                      aria-label={f.name}
                      onClick={() => m.attach.mutate({ fieldId: f.id })}
                      className="flex h-8 items-center justify-between rounded-md px-2 text-left text-sm hover:bg-surface-2"
                    >
                      <span aria-hidden>{f.name}</span>
                      <span aria-hidden className="text-xs text-muted-2">
                        {TYPE_LABEL[f.type]}
                      </span>
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          )
        ) : null}
      </div>
    </Dialog>
  );
}

function NewFieldForm({
  onCancel,
  onCreate,
}: {
  onCancel: () => void;
  onCreate: (v: { name: string; type: FieldType; options?: { label: string }[] }) => void;
}) {
  const [name, setName] = useState('');
  const [type, setType] = useState<FieldType>('text');
  const [options, setOptions] = useState<{ label: string }[]>([{ label: '' }, { label: '' }]);
  const isSelect = SELECT_TYPES.includes(type);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const n = name.trim();
    if (!n) return;
    const opts = isSelect
      ? options
          .map((o) => o.label.trim())
          .filter(Boolean)
          .map((label) => ({ label }))
      : undefined;
    onCreate({ name: n, type, options: opts });
  };

  return (
    <form onSubmit={submit} className="flex flex-col gap-2 border-t border-hair-soft pt-3">
      <Input
        aria-label="New field name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Field name"
        // eslint-disable-next-line jsx-a11y/no-autofocus -- user just asked to add a field
        autoFocus
      />
      <select
        aria-label="Field type"
        value={type}
        onChange={(e) => setType(e.target.value as FieldType)}
        className="h-8 rounded-md border border-hairline bg-surface-2 px-2.5 text-sm focus:border-focus focus:outline-none"
      >
        {TYPES.map((t) => (
          <option key={t} value={t}>
            {TYPE_LABEL[t]}
          </option>
        ))}
      </select>
      {isSelect ? (
        <div className="flex flex-col gap-1.5">
          {options.map((o, i) => (
            <div key={i} className="flex items-center gap-1.5">
              <Input
                aria-label={`Option ${i + 1}`}
                value={o.label}
                onChange={(e) =>
                  setOptions((prev) => prev.map((p, j) => (j === i ? { label: e.target.value } : p)))
                }
                placeholder={`Option ${i + 1}`}
              />
              <IconButton
                icon={X}
                label={`Remove option ${i + 1}`}
                size="icon-sm"
                onClick={() => setOptions((prev) => prev.filter((_, j) => j !== i))}
              />
            </div>
          ))}
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="justify-start"
            onClick={() => setOptions((prev) => [...prev, { label: '' }])}
          >
            <Icon icon={Plus} /> Add option
          </Button>
        </div>
      ) : null}
      <div className="flex justify-end gap-2 pt-1">
        <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" size="sm" disabled={!name.trim()}>
          Add field
        </Button>
      </div>
    </form>
  );
}
