import { Command } from 'cmdk';
import { UserMinus, UserRound } from 'lucide-react';
import type { ReactNode } from 'react';
import { Icon } from '@/components/ui/Icon';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/Popover';
import { useMe } from '@/features/auth';
import { PeopleCommand, peopleItemClass } from '@/features/people';

/** The toast after assigning. An agent starts working within a minute and answers in the task's
 * thread (S5.2.1), so say so. */
export function assignedMessage(
  user: { id: string; name: string; is_agent?: boolean } | null,
  meId: string | undefined,
): string {
  if (!user) return 'Unassigned';
  if (user.is_agent) return `Assigned to ${user.name}. It will reply in the comments shortly.`;
  return `Assigned to ${user.id === meId ? 'you' : user.name}`;
}

/** Assignee combobox: "Assign to me", search people and assignable agents (✦, S5.2.1),
 * "Unassign". Controlled so `A` can open it. */
export function AssigneePicker({
  open,
  onOpenChange,
  assigneeId,
  onChange,
  allowClear = false,
  children,
}: {
  /** Always offer "Unassign" (bulk editing, where there's no single current assignee). */
  allowClear?: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  assigneeId: string | null;
  onChange: (user: { id: string; name: string; is_agent?: boolean } | null) => void;
  children: ReactNode;
}) {
  const me = useMe().data?.user;
  const pick = (user: { id: string; name: string; is_agent?: boolean } | null) => {
    onOpenChange(false);
    if (allowClear || (user?.id ?? null) !== assigneeId) onChange(user);
  };
  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <PopoverTrigger asChild>{children}</PopoverTrigger>
      <PopoverContent className="w-72 p-0" align="start">
        <PeopleCommand
          placeholder="Assign to…"
          agents="assigned"
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
              {assigneeId || allowClear ? (
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
