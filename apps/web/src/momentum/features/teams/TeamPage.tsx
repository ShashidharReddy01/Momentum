import {
  Archive,
  Crown,
  FolderPlus,
  Lock,
  LogOut,
  MoreHorizontal,
  Trash2,
  UserMinus,
  UserPlus,
  Users,
} from 'lucide-react';
import { useState } from 'react';
import { Link, useParams, useNavigate } from 'react-router';
import { InlineText } from '@/components/common/InlineText';
import { EmptyState, ErrorState } from '@/components/common/States';
import { Avatar } from '@/components/ui/Avatar';
import { Button } from '@/components/ui/Button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu';
import { Icon } from '@/components/ui/Icon';
import { IconButton } from '@/components/ui/IconButton';
import { Skeleton } from '@/components/ui/Skeleton';
import { useMe } from '@/features/auth';
import { PeoplePicker } from '@/features/people';
import { NewProjectDialog, useProjects } from '@/features/projects';
import { useCrumbs } from '@/lib/crumbs';
import { colorVar } from './ColorPicker';
import { useDeleteTeam, useTeam, useTeamMembers, useUpdateTeam } from './queries';

export function TeamPage() {
  const { teamId = '' } = useParams();
  const team = useTeam(teamId);
  const me = useMe();
  const update = useUpdateTeam(teamId);
  const del = useDeleteTeam(teamId);
  const members = useTeamMembers(teamId);
  const navigate = useNavigate();
  const [newProject, setNewProject] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const projects = useProjects({ teamId });
  const archived = useProjects({ teamId, archived: true });
  useCrumbs(team.data ? ['Teams', team.data.name] : null);

  if (team.isPending) {
    return (
      <div className="mx-auto max-w-3xl px-4 md:px-8 py-8">
        <Skeleton className="h-7 w-48" />
        <Skeleton className="mt-6 h-40" />
      </div>
    );
  }
  if (team.isError) return <ErrorState error={team.error} onRetry={() => void team.refetch()} />;

  const t = team.data;
  const myId = me.data?.user.id;
  const canManage = t.my_role === 'lead' || me.data?.user.role === 'admin';
  const leads = t.members.filter((m) => m.role === 'lead').length;

  return (
    <div className="mx-auto max-w-3xl px-4 md:px-8 py-8">
      <header className="flex items-start gap-3">
        <span
          aria-hidden
          className="mt-2 h-3 w-3 shrink-0 rounded-full"
          style={{ background: colorVar(t.color) }}
        />
        <div className="min-w-0 flex-1">
          <InlineText
            aria-label="Team name"
            value={t.name}
            disabled={!canManage}
            onCommit={(name) => update.mutate({ name })}
            className="page-title"
          />
          <InlineText
            aria-label="Team description"
            value={t.description ?? ''}
            required={false}
            placeholder={canManage ? 'Add a description' : ''}
            disabled={!canManage}
            onCommit={(description) => update.mutate({ description: description || null })}
            className="mt-1 block text-sm text-muted"
          />
        </div>
        {canManage ? (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <IconButton icon={MoreHorizontal} label="Team actions" />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem
                className="text-crit"
                onSelect={() => del.mutate(undefined, { onSuccess: () => navigate('/') })}
              >
                <Icon icon={Trash2} /> Delete team
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        ) : null}
      </header>

      <section className="mt-8">
        <div className="flex items-center justify-between">
          <h2 className="text-[15px] font-semibold">
            Members <span className="font-normal text-muted">{t.member_count}</span>
          </h2>
          {canManage ? (
            <PeoplePicker
              exclude={t.members.map((m) => m.user.id)}
              onSelect={(p) => members.add.mutate(p.id)}
            >
              <Button size="sm">
                <Icon icon={UserPlus} /> Add member
              </Button>
            </PeoplePicker>
          ) : null}
        </div>
        <ul className="mt-3 divide-y divide-hair-soft rounded-lg border border-hairline bg-surface">
          {t.members.map((m) => {
            const isMe = m.user.id === myId;
            const lastLead = m.role === 'lead' && leads <= 1;
            return (
              <li key={m.user.id} className="flex items-center gap-3 px-3 py-2">
                <Avatar name={m.user.name} src={m.user.avatar_url} size={28} />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">
                    {m.user.name} {isMe ? <span className="font-normal text-muted">(you)</span> : null}
                  </p>
                  <p className="truncate text-xs text-muted">{m.user.email}</p>
                </div>
                <span className="text-xs text-muted">{m.role === 'lead' ? 'Lead' : 'Member'}</span>
                {canManage || isMe ? (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <IconButton icon={MoreHorizontal} label={`Actions for ${m.user.name}`} size="icon-sm" />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      {canManage ? (
                        <DropdownMenuItem
                          disabled={lastLead && m.role === 'lead'}
                          hint={lastLead ? 'last lead' : undefined}
                          onSelect={() =>
                            members.setRole.mutate({
                              userId: m.user.id,
                              role: m.role === 'lead' ? 'member' : 'lead',
                            })
                          }
                        >
                          <Icon icon={Crown} /> {m.role === 'lead' ? 'Make member' : 'Make lead'}
                        </DropdownMenuItem>
                      ) : null}
                      {canManage ? <DropdownMenuSeparator /> : null}
                      <DropdownMenuItem
                        disabled={lastLead}
                        hint={lastLead ? 'last lead' : undefined}
                        onSelect={() =>
                          members.remove.mutate(m.user.id, {
                            onSuccess: () => (isMe ? navigate('/') : undefined),
                          })
                        }
                      >
                        <Icon icon={isMe ? LogOut : UserMinus} /> {isMe ? 'Leave team' : 'Remove from team'}
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                ) : (
                  <span className="w-7" />
                )}
              </li>
            );
          })}
        </ul>
      </section>

      <section className="mt-8">
        <div className="flex items-center justify-between">
          <h2 className="text-[15px] font-semibold">
            Projects <span className="font-normal text-muted">{projects.data?.length ?? ''}</span>
          </h2>
          {t.my_role || me.data?.user.role === 'admin' ? (
            <Button size="sm" onClick={() => setNewProject(true)}>
              <Icon icon={FolderPlus} /> New project
            </Button>
          ) : null}
        </div>
        {(projects.data ?? []).length === 0 ? (
          <div className="mt-3 rounded-lg border border-dashed border-hairline">
            <EmptyState icon={Users} title="No projects yet">
              Create the first project for this team.
            </EmptyState>
          </div>
        ) : (
          <ul className="mt-3 divide-y divide-hair-soft rounded-lg border border-hairline bg-surface">
            {projects.data?.map((p) => (
              <li key={p.id}>
                <Link
                  to={`/projects/${p.id}`}
                  className="flex items-center gap-3 px-3 py-2.5 hover:bg-surface-2"
                >
                  <span
                    aria-hidden
                    className="h-3 w-3 rounded-[4px]"
                    style={{ background: colorVar(p.color) }}
                  />
                  <span className="flex-1 text-sm font-medium">{p.name}</span>
                  {p.privacy === 'private' ? <Icon icon={Lock} size={13} className="text-muted" /> : null}
                  <span className="text-xs capitalize text-muted">{p.my_role}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
        {(archived.data ?? []).length > 0 ? (
          <div className="mt-3">
            <Button
              size="sm"
              variant="text"
              onClick={() => setShowArchived(!showArchived)}
              aria-expanded={showArchived}
            >
              <Icon icon={Archive} /> Archived ({archived.data?.length})
            </Button>
            {showArchived ? (
              <ul className="mt-2 divide-y divide-hair-soft rounded-lg border border-hairline bg-surface">
                {archived.data?.map((p) => (
                  <li key={p.id}>
                    <Link
                      to={`/projects/${p.id}`}
                      className="flex items-center gap-3 px-3 py-2 text-sm text-muted hover:bg-surface-2"
                    >
                      <span
                        aria-hidden
                        className="h-3 w-3 rounded-[4px] opacity-60"
                        style={{ background: colorVar(p.color) }}
                      />
                      {p.name}
                    </Link>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}
      </section>
      <NewProjectDialog open={newProject} onOpenChange={setNewProject} teamId={teamId} />
    </div>
  );
}
