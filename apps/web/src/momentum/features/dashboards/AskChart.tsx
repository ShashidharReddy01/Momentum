import { useMutation } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { AICallout } from '@/components/common/AI';
import { MoMark } from '@/components/common/MoMark';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { Input } from '@/components/ui/Input';
import { errorText } from '@/features/ai';
import type { components } from '@/lib/api/schema';
import { useApi } from '@/providers/api';
import { DEFAULT_SIZE } from './model';
import type { WidgetIn } from './queries';
import { WidgetCard, type WidgetItem } from './WidgetCard';

type Answer = components['schemas']['ChartAskOut'];

const EXAMPLES = [
  'How many tasks are overdue?',
  'Open tasks by assignee',
  'Completed per week, last 3 months',
  "What's due in the next 7 days?",
];

const FILTER_WORDS: Record<string, string> = {
  people: 'For',
  projects: 'In',
  sections: 'Sections',
  tags: 'Tagged',
  field: 'Split by',
};

/**
 * ✦ Ask for a chart (S6.5.2): say what you want to see; Mo picks the chart and its filters (the
 * server counts, as you), you see the live preview, then add it, adjust it in the chart editor,
 * or ask again. When Mo can't tell, it asks back instead of guessing.
 */
export function AskChart({
  open,
  onOpenChange,
  projectId,
  editable,
  onAdd,
  onAdjust,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string | null;
  editable: boolean;
  onAdd: (body: WidgetIn) => void;
  onAdjust: (item: WidgetItem, prompt: string) => void;
}) {
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Ask for a chart"
      description="Say what you want to see. Mo picks the chart; the numbers are counted as you."
      className="top-[8vh] w-[min(760px,calc(100vw-32px))]"
    >
      {open ? <AskBody projectId={projectId} editable={editable} onAdd={onAdd} onAdjust={onAdjust} /> : null}
    </Dialog>
  );
}

function AskBody({
  projectId,
  editable,
  onAdd,
  onAdjust,
}: {
  projectId: string | null;
  editable: boolean;
  onAdd: (body: WidgetIn) => void;
  onAdjust: (item: WidgetItem, prompt: string) => void;
}) {
  const api = useApi();
  const [text, setText] = useState('');
  const [asked, setAsked] = useState('');
  const ask = useMutation({
    mutationFn: async (q: string) =>
      (await api.POST('/api/v1/ai/dashboards/query', { body: { text: q, project_id: projectId } })).data!,
  });
  const submit = (q: string) => {
    const t = q.trim();
    if (!t) return;
    setAsked(t);
    ask.mutate(t);
  };
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    submit(text);
  };
  const answer: Answer | undefined = ask.data;
  const item = answer ? itemOf(answer) : null;

  return (
    <div className="space-y-4 px-5 py-4">
      <form onSubmit={onSubmit} className="flex gap-2">
        <Input
          aria-label="What do you want to see?"
          placeholder="e.g. Open tasks by assignee"
          value={text}
          maxLength={300}
          onChange={(e) => setText(e.target.value)}
        />
        <Button type="submit" variant="ai" loading={ask.isPending} disabled={!text.trim()}>
          <MoMark size={13} /> Ask
        </Button>
      </form>
      {!answer && !ask.isPending && !ask.isError ? (
        <div className="flex flex-wrap gap-1.5">
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              type="button"
              onClick={() => {
                setText(ex);
                submit(ex);
              }}
              className="rounded-full border border-hairline px-2.5 py-0.5 text-[13px] text-ink-2 hover:bg-surface-2"
            >
              {ex}
            </button>
          ))}
        </div>
      ) : null}
      {ask.isError ? (
        <p role="alert" className="text-sm text-crit">
          {errorText(ask.error)}
        </p>
      ) : null}
      {answer?.question ? (
        <AICallout label="Mo asks">
          <p>{answer.question}</p>
        </AICallout>
      ) : null}
      {item && answer ? (
        <div className="space-y-3">
          <AICallout label="Mo made this chart">
            <p>{answer.result?.description}</p>
            <Filters named={answer.named ?? {}} />
          </AICallout>
          <div className="grid grid-cols-2 rounded-xl bg-canvas p-3">
            <WidgetCard
              item={{ ...item, size: item.size === 'sm' ? 'sm' : 'md' }}
              projectId={projectId}
              editable={false}
              onDrill={() => undefined}
              onOpenTask={() => undefined}
            />
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2">
            <Button variant="text" onClick={() => onAdjust(item, asked)} disabled={!editable}>
              Adjust first
            </Button>
            <Button
              variant="primary"
              disabled={!editable}
              onClick={() =>
                onAdd({
                  kind: item.kind,
                  title: item.title,
                  query_spec: item.spec,
                  viz: { size: item.size },
                  created_from_prompt: asked,
                })
              }
            >
              Add to dashboard
            </Button>
          </div>
          {!editable ? (
            <p className="text-right text-xs text-muted">You can view this dashboard but not add to it.</p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function itemOf(a: Answer): WidgetItem | null {
  if (!a.kind || !a.query_spec) return null;
  return {
    id: null,
    kind: a.kind,
    title: a.title ?? 'Chart',
    spec: a.query_spec,
    size: DEFAULT_SIZE[a.kind],
    version: 0,
  };
}

function Filters({ named }: { named: Record<string, unknown> }) {
  const parts = Object.entries(FILTER_WORDS)
    .map(([key, word]) => {
      const v = named[key];
      const text = Array.isArray(v) ? v.join(', ') : typeof v === 'string' ? v : '';
      return text ? `${word}: ${text}` : null;
    })
    .filter((x): x is string => x !== null);
  if (!parts.length) return null;
  return (
    <ul className="mt-1.5 flex flex-wrap gap-1.5">
      {parts.map((p) => (
        <li key={p} className="rounded-full bg-surface px-2 py-0.5 text-xs text-ink-2">
          {p}
        </li>
      ))}
    </ul>
  );
}
