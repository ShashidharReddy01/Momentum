import { Command } from 'cmdk';
import { Plus, Tag as TagIcon, X } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { Link } from 'react-router';
import { IconButton } from '@/components/ui/IconButton';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/Popover';
import { cn } from '@/lib/cn';
import { useTagLibrary, type Tag } from './queries';

const ITEM =
  'flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm data-[selected=true]:bg-surface-2';

/** A tag chip. Text-colored per the ux-spec (not a filled pill, unlike a select-field option).
 * The name links to the tag page (every visible task with this tag, across projects). */
export function TagChip({
  tag,
  onRemove,
  className,
}: {
  tag: Pick<Tag, 'id' | 'name' | 'color'>;
  onRemove?: () => void;
  className?: string;
}) {
  return (
    <span
      className={cn(
        'inline-flex h-6 items-center gap-1 rounded-md bg-surface-2 px-1.5 text-xs font-medium',
        className,
      )}
      style={{ color: tag.color }}
    >
      <Link to={`/tags/${tag.id}`} className="hover:underline" onClick={(e) => e.stopPropagation()}>
        {tag.name}
      </Link>
      {onRemove ? (
        <button
          type="button"
          aria-label={`Remove tag: ${tag.name}`}
          onClick={onRemove}
          className="grid h-4 w-4 place-items-center rounded-sm text-current opacity-60 hover:bg-black/10 hover:opacity-100"
        >
          <X size={11} />
        </button>
      ) : null}
    </span>
  );
}

/** Searchable tag list (cmdk): pick an existing tag, or create one by typing a new name. */
export function TagCommand({
  onSelect,
  onCreate,
  exclude = [],
}: {
  onSelect: (tag: Tag) => void;
  onCreate: (name: string) => void;
  exclude?: string[];
}) {
  const [q, setQ] = useState('');
  const library = useTagLibrary();
  const options = (library.data ?? []).filter((t) => !exclude.includes(t.id));
  const clean = q.trim();
  const exactMatch = options.some((t) => t.name.toLowerCase() === clean.toLowerCase());
  return (
    <Command label="Tags" loop shouldFilter={false}>
      <Command.Input
        value={q}
        onValueChange={setQ}
        placeholder="Search or create a tag…"
        className="h-10 w-full border-b border-hair-soft bg-transparent px-3 text-sm outline-none placeholder:text-muted-2"
      />
      <Command.List className="max-h-64 overflow-auto p-1">
        {clean && !exactMatch ? (
          <Command.Item value={`__create__${clean}`} onSelect={() => onCreate(clean)} className={ITEM}>
            <Plus size={14} /> Create "{clean}"
          </Command.Item>
        ) : null}
        <Command.Empty className="px-3 py-4 text-center text-sm text-muted">
          {library.isPending ? 'Loading…' : clean ? null : 'No tags yet'}
        </Command.Empty>
        {options
          .filter((t) => !clean || t.name.toLowerCase().includes(clean.toLowerCase()))
          .map((t) => (
            <Command.Item key={t.id} value={t.id} onSelect={() => onSelect(t)} className={ITEM}>
              <span aria-hidden className="h-2 w-2 shrink-0 rounded-full" style={{ background: t.color }} />
              <span className="truncate">{t.name}</span>
            </Command.Item>
          ))}
      </Command.List>
    </Command>
  );
}

export function TagPicker({
  onSelect,
  onCreate,
  exclude,
  children,
}: {
  onSelect: (tag: Tag) => void;
  onCreate: (name: string) => void;
  exclude?: string[];
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>{children}</PopoverTrigger>
      <PopoverContent className="w-64 p-0">
        <TagCommand
          exclude={exclude}
          onSelect={(t) => {
            setOpen(false);
            onSelect(t);
          }}
          onCreate={(name) => {
            setOpen(false);
            onCreate(name);
          }}
        />
      </PopoverContent>
    </Popover>
  );
}

/** A row of tag chips plus an "add tag" button — the pane's "Tags" field and reusable wherever a
 * task's tags need to be shown and edited (not just the pane). */
export function TagList({
  tags,
  canEdit,
  onAdd,
  onCreate,
  onRemove,
}: {
  tags: Tag[];
  canEdit: boolean;
  onAdd: (tag: Tag) => void;
  onCreate: (name: string) => void;
  onRemove: (tagId: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1">
      {tags.map((t) => (
        <TagChip key={t.id} tag={t} onRemove={canEdit ? () => onRemove(t.id) : undefined} />
      ))}
      {canEdit ? (
        <TagPicker exclude={tags.map((t) => t.id)} onSelect={onAdd} onCreate={onCreate}>
          <IconButton icon={tags.length ? Plus : TagIcon} label="Add tag" size="icon-sm" />
        </TagPicker>
      ) : null}
    </div>
  );
}
