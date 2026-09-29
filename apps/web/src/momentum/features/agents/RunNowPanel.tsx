import { useState, type ChangeEvent } from 'react';
import { useNavigate } from 'react-router';
import { MoMark } from '@/components/common/MoMark';
import { Button } from '@/components/ui/Button';
import { errorText } from '@/features/ai';
import { useRunNow, type Agent } from './queries';

const field =
  'rounded-md border border-hairline bg-surface px-2.5 py-1.5 text-sm outline-none focus:border-focus';
const TEXT_FILES = '.txt,.md,.vtt,.srt,text/plain,text/markdown,text/vtt';
const MAX_TEXT = 20_000;

/** S5.3.5/S5.3.6: "Run now" for agents with a manual trigger, for anyone who can see what it runs
 * on. Give it text (a brief, meeting notes: paste or load a .txt/.md/.vtt file), a task or a
 * project. It starts within a minute; the run page shows what it does. */
export function RunNowPanel({ agent }: { agent: Agent }) {
  const navigate = useNavigate();
  const [task, setTask] = useState('');
  const [projectId, setProjectId] = useState('');
  const [text, setText] = useState('');
  const [fileNote, setFileNote] = useState<string | null>(null);
  const run = useRunNow(agent.id);
  const projects = agent.projects ?? [];
  const ready = !!text.trim() || !!task.trim() || !!projectId;

  const load = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    const content = await file.text();
    setText(content.slice(0, MAX_TEXT));
    setFileNote(
      content.length > MAX_TEXT
        ? `${file.name}: kept the first ${MAX_TEXT.toLocaleString()} characters`
        : file.name,
    );
  };

  return (
    <section aria-label="Run now" className="flex flex-col gap-3 rounded-lg border border-hairline p-4">
      <h2 className="text-sm font-semibold">Run now</h2>
      <label className="flex flex-col gap-1 text-xs text-muted">
        Text for {agent.name} (a brief, meeting notes…)
        <textarea
          className={`${field} min-h-24`}
          value={text}
          maxLength={MAX_TEXT}
          onChange={(e) => {
            setText(e.target.value);
            setFileNote(null);
          }}
        />
      </label>
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 text-xs text-muted">
          Or load a text file
          <input type="file" accept={TEXT_FILES} className="text-xs" onChange={(e) => void load(e)} />
        </label>
        {fileNote ? <span className="pb-1 text-xs text-muted">{fileNote}</span> : null}
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 text-xs text-muted">
          On a task (optional)
          <input
            className={`${field} w-28`}
            placeholder="T-12"
            value={task}
            onChange={(e) => setTask(e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted">
          In a project (optional)
          <select className={field} value={projectId} onChange={(e) => setProjectId(e.target.value)}>
            <option value="">—</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
      </div>
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
              {
                ...(task.trim() ? { task: task.trim() } : {}),
                ...(projectId ? { project_id: projectId } : {}),
                ...(text.trim() ? { text: text.trim() } : {}),
              },
              { onSuccess: (res) => void navigate(`/agents/runs/${res.run_id}`) },
            )
          }
        >
          <MoMark size={13} /> Run {agent.name.split(' ·')[0]}
        </Button>
      </div>
    </section>
  );
}
