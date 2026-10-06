import { useMemo, useState } from 'react';
import { MoreHorizontal, UserPlus } from 'lucide-react';
import { toast } from 'sonner';
import { useMe } from '@/features/auth';
import { usePeople } from '@/features/people';
import { Avatar } from '@/components/ui/Avatar';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu';
import { IconButton } from '@/components/ui/IconButton';
import { Icon } from '@/components/ui/Icon';
import { Skeleton } from '@/components/ui/Skeleton';
import {
  useInviteMember,
  useMembers,
  useTransferWork,
  useUpdateMember,
  type Member,
  type UserInvite,
} from './queries';

const STATUS_LABEL: Record<string, string> = {
  active: 'Active',
  invited: 'Invited',
  disabled: 'Disabled',
};

/** S2.7.3: workspace members roster. Anyone can see who's on the workspace (active members, from
 * the pickers' list); an admin sees everyone, invited and disabled included, and the "Invite" button (the backend enforces this too — `Action.USERS_MANAGE` — this is purely a
 * UX nicety, not the actual guard). No email is sent: inviting just creates a placeholder member
 * (`status="invited"`) that activates itself the moment that person signs in for the first time
 * and their auth email matches (see `auth/identity.py`). */
export function MembersPage() {
  const me = useMe();
  const isAdmin = me.data?.user.role === 'admin';
  const roster = useMembers(isAdmin);
  const people = usePeople();
  const members = isAdmin ? roster : people;
  const [inviteOpen, setInviteOpen] = useState(false);
  const [q, setQ] = useState('');
  const [handOn, setHandOn] = useState<Member | null>(null);
  const update = useUpdateMember();
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const all = members.data ?? [];
    return needle ? all.filter((m) => `${m.name} ${m.email}`.toLowerCase().includes(needle)) : all;
  }, [members.data, q]);

  return (
    <div className="px-4 py-6 md:px-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="page-title">Members</h1>
          {members.data ? (
            <p className="mt-1 text-sm text-muted">
              {members.data.length} {members.data.length === 1 ? 'person' : 'people'}
              {isAdmin
                ? '. Anyone with the Momentum admin role in your company directory becomes an admin again when they sign in: remove it there.'
                : ' in this workspace. Admins invite new members.'}
            </p>
          ) : null}
        </div>
        {isAdmin ? (
          <Button size="sm" onClick={() => setInviteOpen(true)}>
            <Icon icon={UserPlus} /> Invite
          </Button>
        ) : null}
      </div>

      {(members.data?.length ?? 0) > 8 ? (
        <input
          aria-label="Find a member"
          placeholder="Find by name or email…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          className="mt-4 h-9 w-full max-w-sm rounded-md border border-hairline bg-surface px-3 text-sm outline-none focus:border-focus"
        />
      ) : null}

      {members.isPending ? (
        <div className="mt-6 flex flex-col gap-2">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
        </div>
      ) : (
        <ul className="mt-6 flex flex-col divide-y divide-hair-soft">
          {shown.map((m) => (
            <li key={m.id} aria-label={m.name} className="flex items-center gap-3 py-3">
              <Avatar name={m.name} src={m.avatar_url} size={32} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{m.name}</p>
                <p className="truncate text-xs text-muted">{m.email}</p>
              </div>
              {isAdmin && m.id !== me.data?.user.id ? (
                <select
                  aria-label={`Role for ${m.name}`}
                  value={m.role}
                  onChange={(e) =>
                    update.mutate({
                      id: m.id,
                      role: e.target.value,
                      message: `${m.name} is now ${e.target.value === 'admin' ? 'an admin' : `a ${e.target.value}`}`,
                    })
                  }
                  className="h-7 rounded-md border border-hairline bg-surface px-1.5 text-xs"
                >
                  <option value="admin">Admin</option>
                  <option value="member">Member</option>
                  <option value="guest">Guest</option>
                </select>
              ) : (
                <span className="text-xs capitalize text-muted">{m.role}</span>
              )}
              <span
                className="rounded-full bg-surface-2 px-2 py-0.5 text-xs text-muted"
                data-status={m.status}
              >
                {STATUS_LABEL[m.status] ?? m.status}
              </span>
              {isAdmin && m.id !== me.data?.user.id ? (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <IconButton icon={MoreHorizontal} label={`More for ${m.name}`} size="icon-sm" />
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onSelect={() => setHandOn(m)}>Hand on their work…</DropdownMenuItem>
                    {m.status === 'disabled' ? (
                      <DropdownMenuItem
                        onSelect={() =>
                          update.mutate({
                            id: m.id,
                            status: 'active',
                            message: `${m.name} can sign in again`,
                          })
                        }
                      >
                        Enable
                      </DropdownMenuItem>
                    ) : (
                      <DropdownMenuItem
                        className="text-crit"
                        onSelect={() =>
                          update.mutate({
                            id: m.id,
                            status: 'disabled',
                            message: `${m.name} is disabled: they can't sign in, and their tokens stop working`,
                          })
                        }
                      >
                        Disable
                      </DropdownMenuItem>
                    )}
                  </DropdownMenuContent>
                </DropdownMenu>
              ) : null}
            </li>
          ))}
        </ul>
      )}

      {isAdmin ? <InviteDialog open={inviteOpen} onOpenChange={setInviteOpen} /> : null}
      {handOn ? (
        <HandOnDialog
          from={handOn}
          people={(members.data ?? []).filter((m) => m.id !== handOn.id && m.status !== 'disabled')}
          onClose={() => setHandOn(null)}
        />
      ) : null}
    </div>
  );
}

function InviteDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const invite = useInviteMember();
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<UserInvite['role']>('member');

  const submit = () => {
    if (!email.trim()) return;
    invite.mutate(
      { email: email.trim(), role },
      {
        onSuccess: () => {
          setEmail('');
          onOpenChange(false);
        },
      },
    );
  };

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Invite a member"
      className="w-[min(420px,calc(100vw-32px))]"
    >
      <div className="flex flex-col gap-3 p-4">
        <label className="flex flex-col gap-1 text-sm">
          Email
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="name@company.com"
            className="h-9 rounded-md border border-hair bg-surface px-2 text-sm"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Role
          <select
            value={role}
            onChange={(e) => setRole(e.target.value as UserInvite['role'])}
            className="h-9 rounded-md border border-hair bg-surface px-2 text-sm"
          >
            <option value="member">Member</option>
            <option value="admin">Admin</option>
            <option value="guest">Guest</option>
          </select>
        </label>
        <Button onClick={submit} disabled={!email.trim() || invite.isPending} className="w-fit">
          {invite.isPending ? 'Inviting…' : 'Send invite'}
        </Button>
      </div>
    </Dialog>
  );
}

/** S7.5.4: give a departing (or moving) member's open tasks and owned projects to someone else. */
function HandOnDialog({ from, people, onClose }: { from: Member; people: Member[]; onClose: () => void }) {
  const transfer = useTransferWork();
  const [to, setTo] = useState('');
  const submit = () =>
    to &&
    transfer.mutate(
      { from: from.id, to },
      {
        onSuccess: (r) => {
          const name = people.find((p) => p.id === to)?.name ?? 'them';
          toast.success(
            `${r.tasks} open task${r.tasks === 1 ? '' : 's'} and ${r.projects} project${r.projects === 1 ? '' : 's'} handed to ${name}` +
              (r.not_visible
                ? `; ${r.not_visible} in private projects stay for their admins to reassign`
                : ''),
          );
          onClose();
        },
      },
    );
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={`Hand on ${from.name}'s work`}
      className="w-[min(440px,calc(100vw-32px))]"
    >
      <div className="flex flex-col gap-3 p-4">
        <p className="text-sm text-ink-2">
          Their open tasks and the projects they own go to the person you choose. Tasks in private projects
          you can't see stay where they are.
        </p>
        <label className="flex flex-col gap-1 text-sm">
          Give it to
          <select
            value={to}
            onChange={(e) => setTo(e.target.value)}
            className="h-9 rounded-md border border-hairline bg-surface px-2 text-sm"
          >
            <option value="">Choose a person…</option>
            {people.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <Button onClick={submit} disabled={!to || transfer.isPending} className="w-fit">
          {transfer.isPending ? 'Handing on…' : 'Hand on'}
        </Button>
      </div>
    </Dialog>
  );
}
