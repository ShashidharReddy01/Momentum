import { X } from 'lucide-react';
import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { useProjects } from '@/features/projects';
import { useAgentProjects, type Agent } from './queries';

/** Where the agent works (kickoff Q1: explicit project membership, never implied). Adding a
 * project makes the agent's account an editor there, like sharing it with a person: anyone who
 * is an admin of a project can add the agent to it or remove it (the server checks the same). */
export function AgentProjects({ agent }: { agent: Agent }) {
  const projects = useProjects().data ?? [];
  const { add, remove } = useAgentProjects(agent.id);
  const [pick, setPick] = useState('');
  const current = agent.projects ?? [];
  const has = new Set(current.map((p) => p.id));
  const manage = new Set(projects.filter((p) => p.my_role === 'admin').map((p) => p.id));
  const options = projects.filter((p) => !has.has(p.id) && manage.has(p.id));
  if (!current.length && !options.length) return null;
  return (
    <section aria-label="Works in" className="flex flex-col gap-2 rounded-lg border border-hairline p-4">
      <h2 className="text-sm font-semibold">Works in</h2>
      <p className="-mt-1 text-xs text-muted">
        {agent.name} can only see and act in these projects. It joins each as an editor, visible in Share.
      </p>
      {current.length ? (
        <ul className="flex flex-col gap-1 text-sm">
          {current.map((p) => (
            <li key={p.id} className="flex items-center gap-2">
              <span className="flex-1">{p.name}</span>
              <span className="text-xs text-muted">{p.role}</span>
              {manage.has(p.id) ? (
                <button
                  type="button"
                  aria-label={`Remove ${agent.name} from ${p.name}`}
                  className="text-muted hover:text-ink"
                  onClick={() => remove.mutate(p.id)}
                >
                  <X size={14} />
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted">No projects yet.</p>
      )}
      {options.length ? (
        <div className="flex items-center gap-2">
          <select
            aria-label="Add to project"
            className="rounded-md border border-hairline bg-surface px-2 py-1 text-sm"
            value={pick}
            onChange={(e) => setPick(e.target.value)}
          >
            <option value="">Add to a project you manage…</option>
            {options.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          <Button
            size="sm"
            disabled={!pick}
            loading={add.isPending}
            onClick={() => add.mutate(pick, { onSuccess: () => setPick('') })}
          >
            Add
          </Button>
        </div>
      ) : null}
    </section>
  );
}
