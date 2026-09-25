import { Download } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { useAsanaImport, type ImportJob } from './queries';

/** S2.7.1: a minimal, functional import form — not the spec's fuller "browse your Asana
 * workspace and pick teams/projects visually" wizard (that needs a `GET /integrations/asana/...`
 * discovery endpoint this slice doesn't build either; disclosed in STATUS.md). The PAT field is
 * never stored: it's sent once in this POST body and used only for the duration of this request. */
export function AsanaImportPage() {
  const [pat, setPat] = useState('');
  const [workspaceGid, setWorkspaceGid] = useState('');
  const [teamGid, setTeamGid] = useState('');
  const [teamName, setTeamName] = useState('');
  const [projectGids, setProjectGids] = useState('');
  const m = useAsanaImport();
  const [result, setResult] = useState<ImportJob | null>(null);

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    setResult(null);
    m.mutate(
      {
        pat,
        workspace_gid: workspaceGid,
        team_gid: teamGid,
        team_name: teamName || 'Imported Team',
        project_gids: projectGids.trim()
          ? projectGids
              .split(',')
              .map((s) => s.trim())
              .filter(Boolean)
          : null,
      },
      { onSuccess: setResult },
    );
  };

  return (
    <div className="min-w-0 flex-1 overflow-auto px-4 md:px-8 py-6">
      <h1 className="page-title mb-1 flex items-center gap-2">
        <Icon icon={Download} size={20} /> Import from Asana
      </h1>
      <p className="mb-6 max-w-lg text-sm text-muted">
        Paste a Personal Access Token from Asana (Settings → Apps → Manage Developer Apps). It's used once for
        this import and never stored.
      </p>

      <form onSubmit={onSubmit} className="flex max-w-lg flex-col gap-3">
        <label className="flex flex-col gap-1 text-sm">
          Personal Access Token
          <input
            type="password"
            required
            value={pat}
            onChange={(e) => setPat(e.target.value)}
            className="h-9 rounded-md border border-hair bg-surface px-2 text-sm"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Asana workspace gid
          <input
            required
            value={workspaceGid}
            onChange={(e) => setWorkspaceGid(e.target.value)}
            className="h-9 rounded-md border border-hair bg-surface px-2 text-sm"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Asana team gid
          <input
            required
            value={teamGid}
            onChange={(e) => setTeamGid(e.target.value)}
            className="h-9 rounded-md border border-hair bg-surface px-2 text-sm"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Team name in Momentum
          <input
            value={teamName}
            onChange={(e) => setTeamName(e.target.value)}
            placeholder="Imported Team"
            className="h-9 rounded-md border border-hair bg-surface px-2 text-sm"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Project gids (comma-separated — leave blank for every project in the team)
          <input
            value={projectGids}
            onChange={(e) => setProjectGids(e.target.value)}
            className="h-9 rounded-md border border-hair bg-surface px-2 text-sm"
          />
        </label>
        <Button type="submit" disabled={m.isPending} className="mt-2 w-fit">
          {m.isPending ? 'Importing…' : 'Run import'}
        </Button>
      </form>

      {result ? (
        <div className="mt-6 max-w-lg rounded-md border border-hair bg-surface-2 p-4 text-sm">
          <p className="mb-2 font-medium">Import {result.status === 'done' ? 'finished' : result.status}</p>
          <ul className="flex flex-col gap-0.5 text-muted">
            {Object.entries(result.stats ?? {}).map(([k, v]) => (
              <li key={k}>
                {k}: {Array.isArray(v) ? v.length : String(v)}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
