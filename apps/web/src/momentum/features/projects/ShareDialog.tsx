import { ChevronDown, Lock, UserPlus, Users } from 'lucide-react';
import { Avatar } from '@/components/ui/Avatar';
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
import { Segmented } from '@/components/ui/Tabs';
import { useMe } from '@/features/auth';
import { PeoplePicker } from '@/features/people';
import { useProjectMembers, useUpdateProject, type ProjectDetail, type ProjectRoleName } from './queries';

export const ROLES: { value: ProjectRoleName; label: string; hint: string }[] = [
  { value: 'admin', label: 'Admin', hint: 'Full control, including sharing and deleting' },
  { value: 'editor', label: 'Editor', hint: 'Can add and edit tasks and sections' },
  { value: 'commenter', label: 'Commenter', hint: 'Can comment, but not edit' },
  { value: 'viewer', label: 'Viewer', hint: 'Can only view' },
];

const label = (r: string) => ROLES.find((x) => x.value === r)?.label ?? r;

export function ShareDialog({
  project,
  open,
  onOpenChange,
}: {
  project: ProjectDetail;
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const me = useMe();
  const { add, setRole, remove } = useProjectMembers(project.id);
  const update = useUpdateProject(project.id);
  const isAdmin = project.my_role === 'admin';
  const admins = project.members.filter((m) => m.role === 'admin').length;
  const myId = me.data?.user.id;

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={`Share ${project.name}`}>
      <div className="flex flex-col gap-5 p-5">
        <div className="flex flex-col gap-2">
          <span className="text-sm font-medium">Who can see it</span>
          {isAdmin ? (
            <Segmented
              label="Privacy"
              value={project.privacy as 'team' | 'private'}
              onChange={(privacy) => update.mutate({ privacy })}
              options={[
                { value: 'team', label: `Everyone in ${project.team_name}` },
                { value: 'private', label: 'Only members below' },
              ]}
            />
          ) : (
            <p className="flex items-center gap-2 text-sm text-muted">
              <Icon icon={project.privacy === 'private' ? Lock : Users} />
              {project.privacy === 'private' ? 'Only invited members' : `Everyone in ${project.team_name}`}
            </p>
          )}
          {project.privacy === 'team' ? (
            <p className="text-xs text-muted">
              Team members can edit by default. Add someone below to give them a different role.
            </p>
          ) : null}
        </div>

        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">Members</span>
            {isAdmin ? (
              <PeoplePicker
                exclude={project.members.map((m) => m.user.id)}
                onSelect={(p) => add.mutate({ userId: p.id, role: 'editor' })}
              >
                <Button size="sm">
                  <Icon icon={UserPlus} /> Add people
                </Button>
              </PeoplePicker>
            ) : null}
          </div>
          <ul className="divide-y divide-hair-soft rounded-lg border border-hairline">
            {project.members.map((m) => {
              const isMe = m.user.id === myId;
              const lastAdmin = m.role === 'admin' && admins <= 1;
              return (
                <li key={m.user.id} className="flex items-center gap-3 px-3 py-2">
                  <Avatar name={m.user.name} src={m.user.avatar_url} size={26} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">
                      {m.user.name} {isMe ? <span className="font-normal text-muted">(you)</span> : null}
                    </p>
                    <p className="truncate text-xs text-muted">{m.user.email}</p>
                  </div>
                  {isAdmin || isMe ? (
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button
                          size="sm"
                          variant="text"
                          aria-label={`Role for ${m.user.name}: ${label(m.role)}`}
                        >
                          {label(m.role)} <Icon icon={ChevronDown} size={13} />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" className="w-64">
                        {isAdmin
                          ? ROLES.map((r) => (
                              <DropdownMenuItem
                                key={r.value}
                                disabled={lastAdmin && r.value !== 'admin'}
                                onSelect={() => setRole.mutate({ userId: m.user.id, role: r.value })}
                              >
                                <span className="flex flex-col">
                                  <span className={r.value === m.role ? 'font-semibold' : undefined}>
                                    {r.label}
                                  </span>
                                  <span className="text-xs text-muted">{r.hint}</span>
                                </span>
                              </DropdownMenuItem>
                            ))
                          : null}
                        {isAdmin ? <DropdownMenuSeparator /> : null}
                        <DropdownMenuItem
                          disabled={lastAdmin}
                          hint={lastAdmin ? 'last admin' : undefined}
                          className="text-crit"
                          onSelect={() => remove.mutate(m.user.id)}
                        >
                          {isMe ? 'Leave project' : 'Remove from project'}
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  ) : (
                    <span className="text-xs text-muted">{label(m.role)}</span>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
        <div className="flex justify-end">
          <Button variant="primary" onClick={() => onOpenChange(false)}>
            Done
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
