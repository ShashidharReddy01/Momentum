import { useState } from 'react';
import { MoMark } from '@/components/common/MoMark';
import { Button } from '@/components/ui/Button';
import { errorText } from '@/features/ai';
import { useDraftTemplateFromBrief, useSaveTemplateFromBrief, type TemplateDraft } from './queries';

/** S4.3.3 "Template from description": describe a repeatable process in a sentence or two, get
 * a draft template back (sections, tasks, role placeholders), and save it — the saved template
 * then works exactly like a hand-built one everywhere else (picking it in "New project"). */
export function DraftTemplateFromBrief({ onSaved }: { onSaved: (templateId: string) => void }) {
  const [brief, setBrief] = useState('');
  const [draft, setDraft] = useState<TemplateDraft | null>(null);
  const [name, setName] = useState('');
  const compile = useDraftTemplateFromBrief();
  const save = useSaveTemplateFromBrief();

  const askMo = () => {
    const text = brief.trim();
    if (!text) return;
    compile.mutate(text, {
      onSuccess: (d) => {
        setDraft(d);
        setName(d.name);
      },
    });
  };

  const taskCount = (d: TemplateDraft) => d.sections.reduce((n, s) => n + s.tasks.length, 0);

  if (draft) {
    return (
      <div className="flex flex-col gap-2 rounded-md border border-dashed border-amber bg-amber-2/40 p-3">
        <p className="flex items-center gap-1.5 text-xs font-semibold text-amber-ink">
          <MoMark size={13} /> Mo drafted this — check it before saving.
        </p>
        <input
          aria-label="Template name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={200}
          className="h-8 rounded-md border border-hairline bg-surface px-2.5 text-sm"
        />
        <ul className="flex flex-col gap-1 text-sm text-ink">
          {draft.sections.map((s, i) => (
            <li key={i}>
              <span className="font-medium">{s.name}</span>
              <span className="text-muted"> — {s.tasks.map((t) => t.title).join(', ')}</span>
            </li>
          ))}
        </ul>
        <p className="text-xs text-muted">
          {draft.sections.length} sections, {taskCount(draft)} tasks
        </p>
        <div className="flex justify-end gap-2">
          <Button size="sm" variant="ghost" onClick={() => setDraft(null)}>
            Discard
          </Button>
          <Button
            size="sm"
            variant="primary"
            loading={save.isPending}
            disabled={!name.trim()}
            onClick={() =>
              save.mutate(
                { name: name.trim(), description: draft.description, draft },
                { onSuccess: (res) => onSaved(res.data.id) },
              )
            }
          >
            Save template
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex gap-2">
        <input
          aria-label="Describe the process"
          placeholder="Describe a process: onboard a new hire, run a launch checklist…"
          value={brief}
          maxLength={1000}
          onChange={(e) => setBrief(e.target.value)}
          className="h-8 min-w-0 flex-1 rounded-md border border-hairline bg-surface px-2 text-sm outline-none placeholder:text-muted-2 focus:border-focus"
        />
        <Button size="sm" variant="ai" loading={compile.isPending} disabled={!brief.trim()} onClick={askMo}>
          <MoMark size={13} /> Draft it
        </Button>
      </div>
      {compile.isError ? (
        <p role="alert" className="text-sm text-crit">
          {errorText(compile.error)}
        </p>
      ) : null}
    </div>
  );
}
