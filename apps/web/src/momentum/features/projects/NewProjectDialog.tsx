import { useEffect, useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { Input } from '@/components/ui/Input';
import { Segmented } from '@/components/ui/Tabs';
import { ColorPicker, useTeams } from '@/features/teams';
import { useCreateProject } from './queries';

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
  const [name, setName] = useState('');
  const [team, setTeam] = useState(teamId ?? '');
  const [privacy, setPrivacy] = useState<'team' | 'private'>('team');
  const [color, setColor] = useState('proj-6');
  const create = useCreateProject();
  const navigate = useNavigate();
  const myTeams = (teams.data ?? []).filter((t) => t.my_role !== null);

  useEffect(() => {
    if (open) setTeam(teamId ?? myTeams[0]?.id ?? '');
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

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="New project">
      {myTeams.length === 0 && !teams.isPending ? (
        <p className="p-5 text-sm text-muted">Create or join a team first. Projects belong to a team.</p>
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
    </Dialog>
  );
}
