import { useState } from 'react';
import { MoMark } from '@/components/common/MoMark';
import { Button } from '@/components/ui/Button';
import { errorText } from '@/features/ai';
import { useTestRun, type Agent } from './queries';
import { STEP_LABEL } from './runMeta';

const field =
  'rounded-md border border-hairline bg-surface px-2.5 py-1.5 text-sm outline-none focus:border-focus';

/** S5.2.3 (admins): try an agent on a task or project before switching it on. A dry run: it
 * reads for real, but nothing it wants to change is applied, proposed or posted. */
export function TestRunPanel({ agent }: { agent: Agent }) {
  const [task, setTask] = useState('');
  const [projectId, setProjectId] = useState('');
  const [text, setText] = useState('');
  const run = useTestRun(agent.id);
  const projects = agent.projects ?? [];
  const ready = !!task.trim() || !!projectId;
  const out = run.data;
  return (
    <section aria-label="Test run" className="flex flex-col gap-3 rounded-lg border border-hairline p-4">
      <h2 className="text-sm font-semibold">Test run</h2>
      <p className="-mt-2 text-xs text-muted">
        See what {agent.name} would do, without changing anything. It can only reach projects it has been
        added to.
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 text-xs text-muted">
          Task key
          <input
            className={`${field} w-28`}
            placeholder="T-12"
            value={task}
            onChange={(e) => setTask(e.target.value)}
          />
        </label>
        <span className="pb-2 text-xs text-muted">or</span>
        <label className="flex flex-col gap-1 text-xs text-muted">
          Project
          <select
            className={field}
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
            disabled={!!task.trim()}
          >
            <option value="">—</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      <label className="flex flex-col gap-1 text-xs text-muted">
        What you’d ask it (optional)
        <textarea
          className={`${field} min-h-14`}
          value={text}
          maxLength={20_000}
          onChange={(e) => setText(e.target.value)}
        />
      </label>
      <div className="flex items-center justify-end gap-2">
        {run.isError ? (
          <p role="alert" className="mr-auto text-sm text-crit">
            {errorText(run.error)}
          </p>
        ) : null}
        <Button
          size="sm"
          variant="ai"
          loading={run.isPending}
          disabled={!ready}
          onClick={() =>
            run.mutate(
              task.trim()
                ? { task: task.trim(), text: text.trim() || null }
                : { project_id: projectId, text: text.trim() || null },
            )
          }
        >
          <MoMark size={13} /> Test run
        </Button>
      </div>
      {out ? (
        <div className="flex flex-col gap-2 rounded-md border border-dashed border-amber bg-amber-2/40 p-3 text-sm">
          <p className="flex items-center gap-1.5 text-xs font-semibold text-amber-ink">
            <MoMark size={13} /> Test run by {agent.name} — nothing was changed.
          </p>
          <p className="whitespace-pre-wrap text-ink">{out.text || '(no answer)'}</p>
          {out.changes.length ? (
            <ul aria-label="Changes it would make" className="flex flex-col gap-0.5 text-xs">
              {out.changes.map((c, i) => (
                <li key={i}>
                  <span className="font-medium">{c.summary}</span>{' '}
                  <span className="text-muted">
                    — {c.decision} ({c.risk} risk)
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-muted">It wouldn’t change anything.</p>
          )}
          <details className="text-xs text-muted">
            <summary>
              {out.steps} model steps · {out.tokens_in + out.tokens_out} tokens
            </summary>
            <ol className="mt-1 list-decimal pl-5">
              {out.trace.map((s, i) => (
                <li key={i}>
                  {STEP_LABEL[s.kind] ?? s.kind}
                  {s.name ? ` ${s.name}` : ''}: {s.summary}
                </li>
              ))}
            </ol>
          </details>
        </div>
      ) : null}
    </section>
  );
}
