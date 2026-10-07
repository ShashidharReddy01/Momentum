import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, Check } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import { MoMark } from '@/components/common/MoMark';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import type { components } from '@/lib/api/schema';
import { useMomentumConfig } from '@/lib/config';
import { useApi } from '@/providers/api';

/** Phase 7.5 (spec §9.3): smart task creation while you type, with no AI model call: possible
 * duplicates and suggested assignee / due / fields / tags from similar tasks, each with its
 * reason. Nothing applies by itself: each chip is a click. */

export type TaskSuggestions = components['schemas']['TaskSuggestionsOut'];
export type TaskSuggestion = components['schemas']['SuggestionOut'];

const DEBOUNCE_MS = 400;
const MIN_WORDS = 3;

export function useTaskSuggestions(
  projectId: string | null | undefined,
  title: string,
  sectionId?: string | null,
) {
  const api = useApi();
  const { ai_enabled: aiEnabled } = useMomentumConfig();
  const [debounced, setDebounced] = useState(title);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(title), DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [title]);
  const text = debounced.trim().replace(/\s+/g, ' ');
  const enough = text.split(' ').filter(Boolean).length >= MIN_WORDS;
  return useQuery({
    queryKey: ['ai', 'task-suggestions', projectId, sectionId ?? null, text],
    enabled: aiEnabled && !!projectId && enough,
    staleTime: 30_000,
    retry: false,
    queryFn: async () =>
      (
        await api.POST('/api/v1/ai/task-suggestions', {
          body: { project_id: projectId!, section_id: sectionId ?? null, title: text },
        })
      ).data!,
  });
}

/** "Looks like T-123 Prepare press kit (open, Mei)" with Open / Not a duplicate. */
export function DuplicateWarning({
  data,
  excludeId,
}: {
  data: TaskSuggestions | undefined;
  excludeId?: string;
}) {
  const [dismissed, setDismissed] = useState<ReadonlySet<string>>(new Set());
  const dup = (data?.duplicates ?? []).find((d) => d.id !== excludeId && !dismissed.has(d.id));
  if (!dup) return null;
  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-2 rounded-md bg-warn/10 px-2.5 py-1.5 text-xs"
    >
      <Icon icon={AlertTriangle} size={13} className="text-warn" />
      <span className="min-w-0 flex-1">
        Looks like {dup.key} <em className="not-italic font-medium">{dup.title}</em> (
        {dup.completed ? 'completed' : 'open'}
        {dup.assignee ? `, ${dup.assignee}` : ''})
      </span>
      <Link to={`/task/${dup.id}`} className="font-medium underline-offset-2 hover:underline">
        Open
      </Link>
      <Button size="sm" variant="text" onClick={() => setDismissed((s) => new Set([...s, dup.id]))}>
        Not a duplicate
      </Button>
    </div>
  );
}

/** The amber "Suggestions" strip: one chip per suggestion, with its reason as the hint. */
export function SuggestionStrip({
  data,
  onApply,
  skip = [],
}: {
  data: TaskSuggestions | undefined;
  onApply: (s: TaskSuggestion) => void;
  /** kinds already set by hand (not offered again) */
  skip?: TaskSuggestion['kind'][];
}) {
  const [applied, setApplied] = useState<ReadonlySet<string>>(new Set());
  const items = (data?.suggestions ?? []).filter((s) => !skip.includes(s.kind) || applied.has(s.label));
  if (!data?.enabled || !items.length) return null;
  return (
    <div role="group" aria-label="Suggestions" className="flex flex-wrap items-center gap-1.5 text-xs">
      <span className="flex items-center gap-1 font-medium text-amber-ink">
        <MoMark size={12} /> Suggestions
      </span>
      {items.map((s) => {
        const done = applied.has(s.label);
        return (
          <button
            key={`${s.kind}:${s.label}`}
            type="button"
            title={s.reason}
            aria-label={`${s.label}: ${s.reason}`}
            aria-pressed={done}
            disabled={done}
            onClick={() => {
              onApply(s);
              setApplied((a) => new Set([...a, s.label]));
            }}
            className="inline-flex items-center gap-1 rounded-full border border-dashed border-amber bg-amber-2 px-2 py-0.5 text-amber-ink hover:bg-amber-hi/40 disabled:opacity-70"
          >
            {done ? <Icon icon={Check} size={11} /> : null}
            {s.label}
          </button>
        );
      })}
    </div>
  );
}
