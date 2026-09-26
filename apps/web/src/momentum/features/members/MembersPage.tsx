import { useState } from 'react';
import { UserPlus } from 'lucide-react';
import { useMe } from '@/features/auth';
import { Avatar } from '@/components/ui/Avatar';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { Icon } from '@/components/ui/Icon';
import { Skeleton } from '@/components/ui/Skeleton';
import { useInviteMember, useMembers, type UserInvite } from './queries';

const STATUS_LABEL: Record<string, string> = {
  active: 'Active',
  invited: 'Invited',
  disabled: 'Disabled',
};

/** S2.7.3: workspace members roster. Anyone can see who's on the workspace; only an admin sees
 * the "Invite" button (the backend enforces this too — `Action.USERS_MANAGE` — this is purely a
 * UX nicety, not the actual guard). No email is sent: inviting just creates a placeholder member
 * (`status="invited"`) that activates itself the moment that person signs in for the first time
 * and their auth email matches (see `auth/identity.py`). */
export function MembersPage() {
  const me = useMe();
  const members = useMembers();
  const isAdmin = me.data?.user.role === 'admin';
  const [inviteOpen, setInviteOpen] = useState(false);

  return (
    <div className="px-4 py-6 md:px-8">
      <div className="flex items-center justify-between">
        <h1 className="page-title">Members</h1>
        {isAdmin ? (
          <Button size="sm" onClick={() => setInviteOpen(true)}>
            <Icon icon={UserPlus} /> Invite
          </Button>
        ) : null}
      </div>

      {members.isPending ? (
        <div className="mt-6 flex flex-col gap-2">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
        </div>
      ) : (
        <ul className="mt-6 flex flex-col divide-y divide-hair-soft">
          {(members.data ?? []).map((m) => (
            <li key={m.id} className="flex items-center gap-3 py-3">
              <Avatar name={m.name} src={m.avatar_url} size={32} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{m.name}</p>
                <p className="truncate text-xs text-muted">{m.email}</p>
              </div>
              <span className="text-xs capitalize text-muted">{m.role}</span>
              <span
                className="rounded-full bg-surface-2 px-2 py-0.5 text-xs text-muted"
                data-status={m.status}
              >
                {STATUS_LABEL[m.status] ?? m.status}
              </span>
            </li>
          ))}
        </ul>
      )}

      {isAdmin ? <InviteDialog open={inviteOpen} onOpenChange={setInviteOpen} /> : null}
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
