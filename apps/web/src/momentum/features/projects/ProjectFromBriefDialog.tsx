import { useEffect, useState, type ChangeEvent, type FormEvent } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { MoMark } from '@/components/common/MoMark';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { Input } from '@/components/ui/Input';
import { errorText, PreviewCard, useProjectFromBrief } from '@/features/ai';
import { useTeams } from '@/features/teams';

const MAX_BRIEF = 20000;
const TEXT_FILE = /\.(txt|md|markdown)$/i;

/**
 * S3.4.6 "Project from a brief": paste or upload (.txt / .md) a brief, pick the team and
 * optionally the dates; Mo plans sections, tasks, dates and people, shown as a PreviewCard.
 * Applying creates the project (one undo). People who aren't on the team are left unassigned,
 * and the notes say who; a plan longer than the requested end date is compressed to fit.
 */
export function ProjectFromBriefDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const teams = useTeams();
  const qc = useQueryClient();
  const plan = useProjectFromBrief();
  const myTeams = (teams.data ?? []).filter((t) => t.my_role !== null);
  const [brief, setBrief] = useState('');
  const [name, setName] = useState('');
  const [team, setTeam] = useState('');
  const [startOn, setStartOn] = useState('');
  const [endOn, setEndOn] = useState('');
  const [fileError, setFileError] = useState<string | null>(null);

  useEffect(() => {
    if (open && !team) setTeam(myTeams[0]?.id ?? '');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, teams.data]);

  const close = (o: boolean) => {
    onOpenChange(o);
    if (!o) {
      plan.reset();
      setBrief('');
      setName('');
      setStartOn('');
      setEndOn('');
      setFileError(null);
    }
  };

  const upload = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    if (!TEXT_FILE.test(file.name)) {
      setFileError('Upload a .txt or .md file, or paste the text.');
      return;
    }
    const text = await file.text();
    setFileError(text.length > MAX_BRIEF ? `Only the first ${MAX_BRIEF} characters are used.` : null);
    setBrief(text.slice(0, MAX_BRIEF));
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!brief.trim() || !team) return;
    plan.mutate({
      brief: brief.trim(),
      team_id: team,
      name: name.trim() || null,
      start_on: startOn || null,
      end_on: endOn || null,
    });
  };

  return (
    <Dialog open={open} onOpenChange={close} title="Project from a brief" className="max-w-2xl">
      <div className="max-h-[75vh] overflow-auto p-5">
        {!plan.data ? (
          <form onSubmit={submit} className="flex flex-col gap-3" aria-label="Brief">
            <label className="flex flex-col gap-1.5 text-sm font-medium">
              Brief
              <textarea
                value={brief}
                maxLength={MAX_BRIEF}
                rows={8}
                onChange={(e) => setBrief(e.target.value)}
                placeholder="Paste the brief: goals, scope, people, deadlines…"
                className="rounded-md border border-hairline bg-surface p-2 text-sm font-normal outline-none focus:border-focus"
              />
            </label>
            <label className="text-sm">
              <span className="text-muted">Or upload a text file: </span>
              <input
                type="file"
                accept=".txt,.md,.markdown,text/plain,text/markdown"
                aria-label="Upload brief"
                onChange={(e) => void upload(e)}
              />
            </label>
            {fileError ? <p className="text-xs text-warn">{fileError}</p> : null}
            <div className="grid grid-cols-2 gap-3 max-sm:grid-cols-1">
              <div className="flex flex-col gap-1.5 text-sm font-medium">
                <label htmlFor="brief-name">Name (optional)</label>
                <Input
                  id="brief-name"
                  value={name}
                  maxLength={120}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Mo names it"
                />
              </div>
              <label className="flex flex-col gap-1.5 text-sm font-medium">
                Team
                <select
                  value={team}
                  onChange={(e) => setTeam(e.target.value)}
                  className="h-8 rounded-md border border-hairline bg-surface-2 px-2 text-sm font-normal"
                >
                  {myTeams.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}
                    </option>
                  ))}
                </select>
              </label>
              <div className="flex flex-col gap-1.5 text-sm font-medium">
                <label htmlFor="brief-start">Starts (default today)</label>
                <Input
                  id="brief-start"
                  type="date"
                  value={startOn}
                  onChange={(e) => setStartOn(e.target.value)}
                />
              </div>
              <div className="flex flex-col gap-1.5 text-sm font-medium">
                <label htmlFor="brief-end">Must finish by (optional)</label>
                <Input
                  id="brief-end"
                  type="date"
                  value={endOn}
                  min={startOn || undefined}
                  onChange={(e) => setEndOn(e.target.value)}
                />
              </div>
            </div>
            {plan.isError ? (
              <p role="alert" className="text-sm text-crit">
                {errorText(plan.error)}
              </p>
            ) : null}
            <div className="flex justify-end gap-2">
              <Button onClick={() => close(false)}>Cancel</Button>
              <Button type="submit" variant="ai" loading={plan.isPending} disabled={!brief.trim() || !team}>
                <MoMark size={13} /> Plan it
              </Button>
            </div>
          </form>
        ) : (
          <div className="space-y-3">
            <p className="text-sm">
              <strong>{plan.data.name}</strong> in {plan.data.team}: {plan.data.tasks} tasks,{' '}
              {plan.data.start_on} to {plan.data.end_on}.
            </p>
            {plan.data.notes.length ? (
              <ul aria-label="Mo adjusted" className="list-disc space-y-0.5 pl-5 text-xs text-muted">
                {plan.data.notes.map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ul>
            ) : null}
            {plan.data.open_questions.length ? (
              <div>
                <h3 className="section-label">Open questions</h3>
                <ul aria-label="Open questions" className="list-disc space-y-0.5 pl-5 text-sm">
                  {plan.data.open_questions.map((q) => (
                    <li key={q}>{q}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            <PreviewCard actionId={plan.data.action_id} onEdit={() => plan.reset()} />
            <div className="flex justify-end">
              <Button
                onClick={() => {
                  void qc.invalidateQueries({ queryKey: ['projects'] });
                  close(false);
                }}
              >
                Done
              </Button>
            </div>
          </div>
        )}
      </div>
    </Dialog>
  );
}
