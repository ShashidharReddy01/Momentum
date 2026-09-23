import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { Input } from '@/components/ui/Input';
import { ColorPicker } from './ColorPicker';
import { useCreateTeam } from './queries';

export function NewTeamDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [color, setColor] = useState<string>('proj-7');
  const create = useCreateTeam();
  const navigate = useNavigate();

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    create.mutate(
      { name: name.trim(), description: description.trim() || null, color },
      {
        onSuccess: (res) => {
          onOpenChange(false);
          setName('');
          setDescription('');
          navigate(`/teams/${res.data.id}`);
        },
      },
    );
  };

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="New team"
      description="Teams own projects. You'll be the lead."
    >
      <form onSubmit={submit} className="flex flex-col gap-4 p-5">
        <div className="flex flex-col gap-1.5 text-sm font-medium">
          <label htmlFor="team-name">Name</label>
          <Input
            id="team-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Product"
            maxLength={120}
            required
          />
        </div>
        <div className="flex flex-col gap-1.5 text-sm font-medium">
          <label htmlFor="team-description">
            Description <span className="font-normal text-muted">(optional)</span>
          </label>
          <Input
            id="team-description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="What this team works on"
          />
        </div>
        <div className="flex flex-col gap-1.5 text-sm font-medium">
          Color
          <ColorPicker value={color} onChange={setColor} />
        </div>
        <div className="flex justify-end gap-2 pt-1">
          <Button onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button type="submit" variant="primary" loading={create.isPending} disabled={!name.trim()}>
            Create team
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
