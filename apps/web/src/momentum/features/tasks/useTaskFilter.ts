import { useCallback, useMemo } from 'react';
import { useMe } from '@/features/auth';
import { useProjectFieldValues, useProjectFields } from '@/features/fields';
import { useProjectTaskTags } from '@/features/tags';
import type { Task } from './queries';
import { useListView } from './useListView';
import { matches, todayLocal, type FieldContext } from './view';

/**
 * S7.4.1: the project's list filters (assignee, due date, tags, custom fields) applied to the
 * board and calendar too: one saved view per project, so filtering on one tab filters them all
 * (sort and group stay list-only). `keep` says whether a task passes; it passes everything while
 * the field values it needs are still loading, rather than flashing an empty board.
 */
export function useTaskFilter(projectId: string) {
  const { view, setView } = useListView(projectId);
  const meId = useMe().data?.user.id;
  const tagsByTask = useProjectTaskTags(projectId).data;
  const projectFields = useProjectFields(projectId).data;
  const needValues = view.fields.length > 0;
  const values = useProjectFieldValues(projectId, needValues).data;
  const fields = useMemo(() => (projectFields ?? []).map((pf) => pf.field), [projectFields]);
  const fieldCtx = useMemo<FieldContext | undefined>(
    () =>
      projectFields && values
        ? { fields: new Map(fields.map((f) => [f.id, f])), valuesOf: (id) => values.get(id) }
        : undefined,
    [projectFields, values, fields],
  );
  const tagIds = useMemo(() => {
    const map = new Map<string, Set<string>>();
    for (const [taskId, tags] of tagsByTask ?? []) map.set(taskId, new Set(tags.map((t) => t.id)));
    return map;
  }, [tagsByTask]);
  const active =
    view.assignees.length > 0 || view.tags.length > 0 || view.due !== 'any' || view.fields.length > 0;
  const keep = useCallback(
    (t: Task) => {
      if (!active) return true;
      if (needValues && !fieldCtx) return true; // still loading
      return matches(
        t,
        { ...view, fields: fieldCtx ? view.fields : [] },
        meId,
        todayLocal(),
        tagIds.get(t.id),
        fieldCtx,
      );
    },
    [active, needValues, fieldCtx, view, meId, tagIds],
  );
  return { view, setView, keep, fields, active };
}
