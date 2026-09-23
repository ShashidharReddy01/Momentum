import { Command } from 'cmdk';
import { UserMinus, UserRound } from 'lucide-react';
import type { ReactNode } from 'react';
import { Icon } from '@/components/ui/Icon';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/Popover';
import { useMe } from '@/features/auth';
import { PeopleCommand, peopleItemClass } from '@/features/people';

/** Assignee combobox: "Assign to me", search people, "Unassign". Controlled so `A` can open it. */
export function AssigneePicker({
  open,
  onOpenChange,
  assigneeId,
  onChange,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  assigneeId: string | null;
  onChange: (user: { id: string; name: string } | null) => void;
  children: ReactNode;
}) {
  const me = useMe().data?.user;
  const pick = (user: { id: string; name: string } | null) => {
    onOpenChange(false);
    if ((user?.id ?? null) !== assigneeId) onChange(user);
  };
  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <PopoverTrigger asChild>{children}</PopoverTrigger>
      <PopoverContent className="w-72 p-0" align="start">
        <PeopleCommand
          placeholder="Assign to…"
          selectedId={assigneeId}
          onSelect={(p) => pick(p)}
          before={
            <>
              {me && me.id !== assigneeId ? (
                <Command.Item
                  value="__me assign to me"
                  onSelect={() => pick({ id: me.id, name: 'you' })}
                  className={peopleItemClass}
                >
                  <Icon icon={UserRound} className="text-muted" /> Assign to me
                </Command.Item>
              ) : null}
              {assigneeId ? (
                <Command.Item
                  value="__none unassign remove"
                  onSelect={() => pick(null)}
                  className={peopleItemClass}
                >
                  <Icon icon={UserMinus} className="text-muted" /> Unassign
                </Command.Item>
              ) : null}
            </>
          }
        />
      </PopoverContent>
    </Popover>
  );
}
