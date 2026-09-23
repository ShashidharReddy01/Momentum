import type { QueryClient } from '@tanstack/react-query';
import { homeKey } from '@/features/home';
import { myTasksKey } from '@/features/mytasks';
import { projectKeys } from '@/features/projects';
import { sectionKeys } from '@/features/sections';
import {
  commentKey,
  dropTask,
  feedKey,
  isTaskList,
  subtaskKey,
  syncTask,
  taskKeys,
  type TaskDetail,
} from '@/features/tasks';
import { teamKeys } from '@/features/teams';
import { isMine } from './mine';
import type { RealtimeEvent } from './types';

/** Context a caller already knows, so handlers don't need to guess it from event payloads
 * that don't always carry it (e.g. section.updated has no project_id in `data`). Omit what
 * you don't have — every field is optional. */
export interface RealtimeContext {
  projectId?: string;
}

const str = (v: unknown): string | undefined => (typeof v === 'string' ? v : undefined);

function changesToPatch(data: Record<string, unknown>): Partial<TaskDetail> {
  const changes = data.changes;
  if (!changes || typeof changes !== 'object') return {};
  // (guarded above; `changes` is a non-null object from here on)
  const patch: Record<string, unknown> = {};
  for (const [field, pair] of Object.entries(changes as Record<string, unknown>)) {
    if (Array.isArray(pair) && pair.length === 2) patch[field] = pair[1];
  }
  return patch as Partial<TaskDetail>;
}

/**
 * Reconciles the TanStack Query cache for one realtime event. Prefers in-place patches
 * (`syncTask`, already used by Phase 1's own mutations — no flicker, no round trip) and falls
 * back to a targeted `invalidateQueries` only where there's no cheaper way to know the new
 * state (e.g. a subtask count, or which list page a completed task moved to).
 *
 * Skips the actor's own echo (see mine.ts) — their own mutation's onSuccess already applied
 * it. Known gap: bulk operations aren't covered by that skip yet (see mine.ts's docstring).
 */
export function applyRealtimeEvent(qc: QueryClient, event: RealtimeEvent, ctx: RealtimeContext = {}): void {
  if (isMine(event.activity_id)) return;
  applyRegardlessOfOwnEcho(qc, event, ctx);
}

/** The reconciliation itself, without the "was this my own change" check — for callers
 * (applyUserChannelEvent) that need to check that once and branch on it themselves. */
function applyRegardlessOfOwnEcho(qc: QueryClient, event: RealtimeEvent, ctx: RealtimeContext): void {
  const { event: type, entity_type: entityType, entity_id: id, data } = event;

  if (entityType === 'task') {
    applyTaskEvent(qc, type, id, data, ctx);
    return;
  }
  if (entityType === 'section' && ctx.projectId) {
    void qc.invalidateQueries({ queryKey: sectionKeys.byProject(ctx.projectId) });
    if (type === 'section.deleted' || type === 'section.created')
      void qc.invalidateQueries({ predicate: (q) => isTaskList(q.queryKey) });
    return;
  }
  if (entityType === 'comment') {
    const taskId = str(data.task_id);
    if (!taskId) return;
    void qc.invalidateQueries({ queryKey: commentKey(taskId) });
    void qc.invalidateQueries({ queryKey: feedKey(taskId) });
    if (type === 'comment.created') void qc.invalidateQueries({ queryKey: taskKeys.detail(taskId) });
    return;
  }
  if (entityType === 'project') {
    void qc.invalidateQueries({ queryKey: projectKeys.detail(id) });
    void qc.invalidateQueries({ queryKey: projectKeys.all });
    return;
  }
  if (entityType === 'team') {
    void qc.invalidateQueries({ queryKey: teamKeys.detail(id) });
    void qc.invalidateQueries({ queryKey: teamKeys.all });
  }
}

function applyTaskEvent(
  qc: QueryClient,
  type: string,
  id: string,
  data: Record<string, unknown>,
  ctx: RealtimeContext,
): void {
  const parentId = str(data.parent_id);
  // every task.* type can show up as a line in the Activity feed (S1.4.2); cheap when the
  // feed isn't mounted (React Query just marks it stale, no refetch happens)
  void qc.invalidateQueries({ queryKey: feedKey(id) });
  const refreshSubtasksOf = (pid: string | undefined) => {
    if (!pid) return;
    void qc.invalidateQueries({ queryKey: subtaskKey(pid) });
    void qc.invalidateQueries({ queryKey: taskKeys.detail(pid) }); // subtask_count badge
  };

  switch (type) {
    case 'task.updated': {
      const patch = changesToPatch(data);
      syncTask(qc, id, patch);
      // an assignee change (part of the same changes) may move it in/out of My Tasks/Home
      if ('assignee_id' in patch) refreshMineAndHome(qc);
      return;
    }
    case 'task.assigned':
      refreshMineAndHome(qc);
      return;
    case 'task.completed':
    case 'task.uncompleted':
      syncTask(qc, id, { completed_at: type === 'task.completed' ? new Date().toISOString() : null });
      void qc.invalidateQueries({ predicate: (q) => isTaskList(q.queryKey) });
      refreshSubtasksOf(parentId);
      refreshMineAndHome(qc);
      return;
    case 'task.deleted':
      dropTask(qc, id);
      refreshSubtasksOf(parentId);
      refreshMineAndHome(qc);
      return;
    case 'task.restored':
      void qc.invalidateQueries({ predicate: (q) => isTaskList(q.queryKey) });
      refreshSubtasksOf(parentId);
      return;
    case 'task.created':
      if (ctx.projectId) void qc.invalidateQueries({ queryKey: ['projects', ctx.projectId, 'tasks'] });
      refreshSubtasksOf(parentId);
      refreshMineAndHome(qc);
      return;
    case 'task.moved':
      if (ctx.projectId) void qc.invalidateQueries({ queryKey: ['projects', ctx.projectId, 'tasks'] });
      refreshSubtasksOf(parentId);
      return;
    case 'task.follower_added':
    case 'task.follower_removed':
      void qc.invalidateQueries({ queryKey: taskKeys.detail(id) });
      return;
    default:
      return;
  }
}

/**
 * For a `user:<id>` channel subscription (My Tasks, Home): any task event that reached me
 * personally (I'm the assignee, or — for task.assigned — I was) means My Tasks and/or Home
 * may need to change membership or order, which a plain field-level `syncTask` patch can't
 * express, so this always refreshes both rather than trying to special-case which change
 * qualifies. Also applies the normal in-place patch, in case the task's own pane or a
 * project list happens to be open elsewhere too.
 */
export function applyUserChannelEvent(qc: QueryClient, event: RealtimeEvent): void {
  if (event.entity_type !== 'task') return;
  if (isMine(event.activity_id)) return;
  applyRegardlessOfOwnEcho(qc, event, {});
  refreshMineAndHome(qc);
}

function refreshMineAndHome(qc: QueryClient): void {
  void qc.invalidateQueries({ queryKey: ['me', 'tasks'] });
  void qc.invalidateQueries({ queryKey: myTasksKey(false) });
  void qc.invalidateQueries({ queryKey: myTasksKey(true) });
  void qc.invalidateQueries({ queryKey: homeKey });
}
