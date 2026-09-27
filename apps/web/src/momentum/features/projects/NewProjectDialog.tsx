import { useEffect, useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { Input } from '@/components/ui/Input';
import { Segmented } from '@/components/ui/Tabs';
import { usePeople } from '@/features/people';
import { ColorPicker, useTeams } from '@/features/teams';
import { useNewProjectFromTemplate, useTemplates, type RoleMapping } from '@/features/templates';
import { useCreateProject } from './queries';

function FromTemplateForm({
  team,
  privacy,
  color,
  onCreated,
}: {
  team: string;
  privacy: 'team' | 'private';
  color: string;
  onCreated: (projectId: string) => void;
}) {
  const templates = useTemplates('project');
  const people = usePeople();
  const [templateId, setTemplateId] = useState('');
  const [name, setName] = useState('');
  const [startDate, setStartDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const create = useNewProjectFromTemplate(templateId);
  const template = (templates.data ?? []).find((t) => t.id === templateId);

  useEffect(() => {
    if (!templateId && templates.data && templates.data.length > 0) {
      setTemplateId(templates.data[0]!.id);
      setName(templates.data[0]!.name);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [templates.data]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !team || !templateId) return;
    const role_mapping: RoleMapping[] = Object.entries(mapping)
      .filter(([, v]) => v)
      .map(([role_id, user_id]) => ({ role_id, user_id }));
    create.mutate(
      { team_id: team, name: name.trim(), start_date: startDate, privacy, color, role_mapping },
      { onSuccess: (res) => onCreated(res.data.id) },
    );
  };

  if (templates.isPending) return <p className="p-5 text-sm text-muted">Loading templates…</p>;
  if ((templates.data ?? []).length === 0) {
    return (
      <p className="p-5 text-sm text-muted">
        No project templates yet — save one from a project's ⋯ menu first.
      </p>
    );
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4 p-5">
      <div className="flex flex-col gap-1.5 text-sm font-medium">
        <label htmlFor="template-pick">Template</label>
        <select
          id="template-pick"
          value={templateId}
          onChange={(e) => {
            setTemplateId(e.target.value);
            const t = templates.data?.find((x) => x.id === e.target.value);
            if (t) setName(t.name);
          }}
          className="h-8 rounded-md border border-hairline bg-surface-2 px-2 text-sm"
        >
          {(templates.data ?? []).map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
      </div>
      <div className="flex flex-col gap-1.5 text-sm font-medium">
        <label htmlFor="template-project-name">Name</label>
        <Input
          id="template-project-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={200}
          required
        />
      </div>
      <div className="flex flex-col gap-1.5 text-sm font-medium">
        <label htmlFor="template-start-date">Start date</label>
        <Input
          id="template-start-date"
          type="date"
          value={startDate}
          onChange={(e) => setStartDate(e.target.value)}
          required
        />
      </div>
      {(template?.payload.roles.length ?? 0) > 0 ? (
        <div className="flex flex-col gap-1.5">
          <span className="text-sm font-medium">Who's doing what</span>
          {template!.payload.roles.map((role) => (
            <label key={role.id} className="flex items-center gap-2 text-sm text-muted">
              <span className="w-32 shrink-0 truncate text-ink">{role.label}</span>
              <select
                aria-label={`Assign ${role.label} to`}
                value={mapping[role.id] ?? ''}
                onChange={(e) => setMapping((m) => ({ ...m, [role.id]: e.target.value }))}
                className="h-8 flex-1 rounded-md border border-hairline bg-surface-2 px-2 text-sm"
              >
                <option value="">Leave unassigned</option>
                {(people.data ?? []).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
          ))}
        </div>
      ) : null}
      <div className="flex justify-end gap-2 pt-1">
        <Button type="submit" variant="primary" loading={create.isPending} disabled={!name.trim()}>
          Create project
        </Button>
      </div>
    </form>
  );
}

export function NewProjectDialog({
  open,
  onOpenChange,
  teamId,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  teamId?: string;
}) {
  const teams = useTeams();
  const [mode, setMode] = useState<'blank' | 'template'>('blank');
  const [name, setName] = useState('');
  const [team, setTeam] = useState(teamId ?? '');
  const [privacy, setPrivacy] = useState<'team' | 'private'>('team');
  const [color, setColor] = useState('proj-6');
  const create = useCreateProject();
  const navigate = useNavigate();
  const myTeams = (teams.data ?? []).filter((t) => t.my_role !== null);

  useEffect(() => {
    if (open) {
      setTeam(teamId ?? myTeams[0]?.id ?? '');
      setMode('blank');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, teamId, teams.data]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !team) return;
    create.mutate(
      { team_id: team, name: name.trim(), privacy, color },
      {
        onSuccess: (res) => {
          onOpenChange(false);
          setName('');
          navigate(`/projects/${res.data.id}`);
        },
      },
    );
  };

  const onCreatedFromTemplate = (projectId: string) => {
    onOpenChange(false);
    navigate(`/projects/${projectId}`);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="New project">
      {myTeams.length === 0 && !teams.isPending ? (
        <p className="p-5 text-sm text-muted">Create or join a team first. Projects belong to a team.</p>
      ) : (
        <>
          <div className="px-5 pt-4">
            <Segmented
              label="How to start"
              value={mode}
              onChange={setMode}
              options={[
                { value: 'blank', label: 'Blank' },
                { value: 'template', label: 'From template' },
              ]}
            />
          </div>
          <div className="flex flex-col gap-1.5 px-5 pt-3 text-sm font-medium">
            <label htmlFor="project-team">Team</label>
            <select
              id="project-team"
              value={team}
              onChange={(e) => setTeam(e.target.value)}
              className="h-8 rounded-md border border-hairline bg-surface-2 px-2 text-sm"
            >
              {myTeams.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          </div>
          {mode === 'template' ? (
            <FromTemplateForm team={team} privacy={privacy} color={color} onCreated={onCreatedFromTemplate} />
          ) : (
            <form onSubmit={submit} className="flex flex-col gap-4 p-5">
              <div className="flex flex-col gap-1.5 text-sm font-medium">
                <label htmlFor="project-name">Name</label>
                <Input
                  id="project-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Website Revamp"
                  maxLength={200}
                  required
                />
              </div>
              <div className="flex flex-col gap-1.5 text-sm font-medium">
                <span id="project-privacy">Who can see it</span>
                <Segmented
                  label="Privacy"
                  value={privacy}
                  onChange={setPrivacy}
                  options={[
                    { value: 'team', label: 'Everyone in the team' },
                    { value: 'private', label: 'Only invited members' },
                  ]}
                />
              </div>
              <div className="flex flex-col gap-1.5 text-sm font-medium">
                Color
                <ColorPicker value={color} onChange={setColor} />
              </div>
              <div className="flex justify-end gap-2 pt-1">
                <Button onClick={() => onOpenChange(false)}>Cancel</Button>
                <Button
                  type="submit"
                  variant="primary"
                  loading={create.isPending}
                  disabled={!name.trim() || !team}
                >
                  Create project
                </Button>
              </div>
            </form>
          )}
        </>
      )}
    </Dialog>
  );
}
