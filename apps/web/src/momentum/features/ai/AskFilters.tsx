import { useMutation } from '@tanstack/react-query';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { MoMark } from '@/components/common/MoMark';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import type { components } from '@/lib/api/schema';
import { useApi } from '@/providers/api';
import { errorText } from './errors';

/** Phase 7.5 (spec §9.2): plain-English filters. A sentence becomes a draft in the view's own
 * filter schema, shown as amber chips; nothing applies until Apply (or Enter on the chips). Once
 * applied, an amber "Filtered with Mo" marker stays until the person edits the filters. */

export type FilterDraft = components['schemas']['FilterDraftOut'];
export type FilterSurface = components['schemas']['FiltersIn']['surface'];

export function AskFilters({
  surface,
  projectId,
  portfolioId,
  applied,
  onApply,
  onClear,
  label = 'Describe what to show',
}: {
  surface: FilterSurface;
  projectId?: string;
  portfolioId?: string;
  /** The draft currently applied (shows the marker), or null. */
  applied: FilterDraft | null;
  onApply: (d: FilterDraft) => void;
  onClear: () => void;
  label?: string;
}) {
  const api = useApi();
  const [text, setText] = useState('');
  const ask = useMutation({
    mutationFn: async (t: string) =>
      (
        await api.POST('/api/v1/ai/filters', {
          body: { text: t, surface, project_id: projectId ?? null, portfolio_id: portfolioId ?? null },
        })
      ).data!,
  });
  const draft = ask.data && !ask.data.question ? ask.data : null;
  // Enter applies: the draft's Apply button takes focus when the chips appear
  const applyRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (draft) applyRef.current?.focus();
  }, [draft]);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (text.trim()) ask.mutate(text.trim());
  };
  const apply = () => {
    if (!draft) return;
    onApply(draft);
    ask.reset();
    setText('');
  };
  if (applied)
    return (
      <div className="mb-2 flex flex-wrap items-center gap-1.5 text-xs" role="status">
        <span className="flex items-center gap-1 font-medium text-amber-ink">
          <MoMark size={12} /> Filtered with Mo
        </span>
        {applied.chips.map((c) => (
          <span key={c.key} className="rounded-full border border-hairline bg-surface-2 px-2 py-0.5">
            {c.label}
          </span>
        ))}
        <Button size="sm" variant="text" onClick={onClear} aria-label="Clear Mo's filters">
          Clear
        </Button>
      </div>
    );
  return (
    <div className="mb-2 space-y-1.5">
      <form onSubmit={submit} className="flex items-center gap-2">
        <MoMark size={13} />
        <Input
          aria-label={label}
          placeholder="Describe what to show…"
          value={text}
          onChange={(e) => setText(e.target.value)}
          className="h-8 max-w-md"
          maxLength={300}
        />
        <Button size="sm" variant="ai" type="submit" loading={ask.isPending} disabled={!text.trim()}>
          Ask
        </Button>
      </form>
      {ask.isError ? (
        <p role="alert" className="text-sm text-crit">
          {errorText(ask.error)}
        </p>
      ) : null}
      {ask.data?.question ? (
        <p className="text-sm text-amber-ink" role="status">
          {ask.data.question}
          {ask.data.options?.length ? (
            <span className="block text-xs text-muted">Options: {ask.data.options.join(', ')}</span>
          ) : null}
        </p>
      ) : null}
      {draft ? (
        <div className="flex flex-wrap items-center gap-1.5 text-xs" aria-label="Mo's filters" role="group">
          {draft.chips.map((c) => (
            <span
              key={c.key}
              className="rounded-full border border-amber bg-amber-2 px-2 py-0.5 text-amber-ink"
            >
              {c.label}
            </span>
          ))}
          <Button ref={applyRef} size="sm" variant="primary" onClick={apply}>
            Apply
          </Button>
          <Button size="sm" variant="text" onClick={() => ask.reset()}>
            Cancel
          </Button>
        </div>
      ) : null}
    </div>
  );
}
