import { Command } from 'cmdk';
import { useState, type ReactNode } from 'react';
import { Avatar } from '@/components/ui/Avatar';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/Popover';
import { usePeople, type Person } from './queries';

const ITEM =
  'flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm data-[selected=true]:bg-surface-2';

/** Searchable people list (cmdk). `before` renders extra items above the people (e.g. "Assign to me"). */
export function PeopleCommand({
  onSelect,
  exclude = [],
  placeholder = 'Search people…',
  before,
  selectedId,
}: {
  onSelect: (person: Person) => void;
  exclude?: string[];
  placeholder?: string;
  before?: ReactNode;
  selectedId?: string | null;
}) {
  const people = usePeople();
  const options = (people.data ?? []).filter((p) => !exclude.includes(p.id));
  return (
    <Command label="People" loop>
      <Command.Input
        placeholder={placeholder}
        className="h-10 w-full border-b border-hair-soft bg-transparent px-3 text-sm outline-none placeholder:text-muted-2"
      />
      <Command.List className="max-h-64 overflow-auto p-1">
        <Command.Empty className="px-3 py-4 text-center text-sm text-muted">
          {people.isPending ? 'Loading…' : 'No one found'}
        </Command.Empty>
        {before}
        {options.map((p) => (
          <Command.Item
            key={p.id}
            value={`${p.name} ${p.email}`}
            onSelect={() => onSelect(p)}
            className={ITEM}
            aria-current={selectedId === p.id ? 'true' : undefined}
          >
            <Avatar name={p.name} src={p.avatar_url} size={22} />
            <span className="min-w-0 flex-1 truncate">{p.name}</span>
            <span className="truncate text-xs text-muted">{p.email}</span>
          </Command.Item>
        ))}
      </Command.List>
    </Command>
  );
}

export const peopleItemClass = ITEM;

export interface PeoplePickerProps {
  onSelect: (person: Person) => void;
  exclude?: string[];
  children: ReactNode;
  placeholder?: string;
}

/** Searchable people picker in a popover (keyboard: type, ↑/↓, Enter). */
export function PeoplePicker({ onSelect, exclude, children, placeholder }: PeoplePickerProps) {
  const [open, setOpen] = useState(false);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>{children}</PopoverTrigger>
      <PopoverContent className="w-72 p-0">
        <PeopleCommand
          exclude={exclude}
          placeholder={placeholder}
          onSelect={(p) => {
            setOpen(false);
            onSelect(p);
          }}
        />
      </PopoverContent>
    </Popover>
  );
}
