import { CheckCircle2, Plus } from 'lucide-react';
import { useCallback, useMemo, useRef, useState } from 'react';
import { ErrorState } from '@/components/common/States';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { Skeleton } from '@/components/ui/Skeleton';
import { SectionList, type Section } from '@/features/sections';
import { useProjectTasks, useTaskMutations, type Task } from './queries';
import { DraftRow, TaskRow } from './TaskRow';

type Draft = { sectionId: string; afterId: string | null; key: number };
const FADE_MS = 1500;
const CONFIRM_PASTE_OVER = 5;

/** The project list view: sections with their tasks, inline create/edit/complete. */
export function ProjectTasksView({ projectId, canEdit }: { projectId: string; canEdit: boolean }) {
  const [showCompleted, setShowCompleted] = useState(false);
  const open = useProjectTasks(projectId);
  const done = useProjectTasks(projectId, true, showCompleted);
  const m = useTaskMutations(projectId);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [fading, setFading] = useState<Set<string>>(new Set());
  const draftKey = useRef(0);

  const bySection = useMemo(() => {
    const map = new Map<string, Task[]>();
    const visible = (open.data ?? []).filter((t) => !t.completed_at || fading.has(t.id) || showCompleted);
    for (const t of visible) map.set(t.section_id!, [...(map.get(t.section_id!) ?? []), t]);
    if (showCompleted) {
      const ids = new Set(visible.map((t) => t.id));
      for (const t of done.data ?? []) {
        if (ids.has(t.id) || !t.section_id) continue;
        const list = map.get(t.section_id) ?? [];
        // merge by position; temp rows (no position) keep their place
        const i = list.findIndex((x) => x.position && t.position && x.position > t.position);
        map.set(t.section_id, i < 0 ? [...list, t] : [...list.slice(0, i), t, ...list.slice(i)]);
      }
    }
    return map;
  }, [open.data, done.data, fading, showCompleted]);

  const openDraft = useCallback((sectionId: string, afterId: string | null) => {
    draftKey.current += 1;
    setDraft({ sectionId, afterId, key: draftKey.current });
  }, []);

  const onToggle = useCallback(
    (t: Task) => {
      const completing = !t.completed_at;
      m.setCompleted.mutate({ id: t.id, completed: completing });
      if (completing) {
        setFading((s) => new Set(s).add(t.id));
        setTimeout(
          () =>
            setFading((s) => {
              const n = new Set(s);
              n.delete(t.id);
              return n;
            }),
          FADE_MS,
        );
      }
    },
    [m.setCompleted],
  );
  const onRename = useCallback((t: Task, title: string) => m.rename.mutate({ id: t.id, title }), [m.rename]);
  const onEnter = useCallback((t: Task) => canEdit && openDraft(t.section_id!, t.id), [canEdit, openDraft]);
  const onDelete = useCallback((t: Task) => m.remove.mutate(t.id), [m.remove]);

  if (open.isPending) {
    return (
      <div className="flex flex-col gap-2">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-8" />
        ))}
      </div>
    );
  }
  if (open.isError) return <ErrorState error={open.error} onRetry={() => void open.refetch()} />;

  const renderBody = (section: Section) => {
    const tasks = bySection.get(section.id) ?? [];
    const draftHere = draft && draft.sectionId === section.id ? draft : null;
    const draftRow = draftHere ? (
      <DraftRow
        key={`draft-${draftHere.key}`}
        onSubmit={(title) => {
          const id = m.create({ title, sectionId: section.id, afterId: draftHere.afterId });
          openDraft(section.id, id);
        }}
        onPasteLines={(lines) => {
          if (
            lines.length > CONFIRM_PASTE_OVER &&
            !window.confirm(`Create ${lines.length} tasks, one per line?`)
          )
            return;
          m.createMany.mutate({ titles: lines, sectionId: section.id, afterId: draftHere.afterId });
          setDraft(null);
        }}
        onCancel={() => setDraft((d) => (d?.key === draftHere.key ? null : d))}
      />
    ) : null;
    const draftIndex = draftHere
      ? draftHere.afterId
        ? tasks.findIndex((t) => t.id === draftHere.afterId) + 1
        : tasks.length
      : -1;
    return (
      <div role="list" aria-label={`Tasks in ${section.name}`}>
        {draftIndex === 0 ? draftRow : null}
        {tasks.map((t, i) => (
          <div key={t.id}>
            <TaskRow
              task={t}
              canEdit={canEdit}
              fading={fading.has(t.id)}
              onToggle={onToggle}
              onRename={onRename}
              onEnter={onEnter}
              onDelete={onDelete}
            />
            {draftIndex === i + 1 ? draftRow : null}
          </div>
        ))}
        {draftIndex > tasks.length ? draftRow : null}
        {canEdit && !draftHere ? (
          <Button
            variant="text"
            size="sm"
            className="mt-1 text-muted"
            onClick={() => openDraft(section.id, tasks.filter((t) => !t.completed_at).at(-1)?.id ?? null)}
          >
            <Icon icon={Plus} /> Add task
          </Button>
        ) : null}
        {!canEdit && tasks.length === 0 ? <p className="py-1 text-sm text-muted-2">No tasks</p> : null}
      </div>
    );
  };

  return (
    <div>
      <div className="mb-3 flex items-center justify-end">
        <Button
          size="sm"
          variant="text"
          aria-pressed={showCompleted}
          onClick={() => setShowCompleted(!showCompleted)}
        >
          <Icon icon={CheckCircle2} /> {showCompleted ? 'Hide completed' : 'Show completed'}
        </Button>
      </div>
      <SectionList projectId={projectId} canEdit={canEdit} renderBody={renderBody} />
    </div>
  );
}
