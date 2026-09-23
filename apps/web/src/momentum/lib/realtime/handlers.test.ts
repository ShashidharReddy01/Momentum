import { QueryClient } from '@tanstack/react-query';
import { describe, expect, it } from 'vitest';
import { taskKeys, type Task } from '@/features/tasks';
import { myTasksKey } from '@/features/mytasks';
import { homeKey } from '@/features/home';
import { applyRealtimeEvent, applyUserChannelEvent } from './handlers';
import { markMine } from './mine';
import type { RealtimeEvent } from './types';

function makeQc(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    id: 't1',
    number: 1,
    key: 'T-1',
    title: 'Original',
    type: 'task',
    project_id: 'p1',
    section_id: 's1',
    position: '1',
    assignee_id: null,
    start_on: null,
    due_on: null,
    due_at: null,
    completed_at: null,
    parent_id: null,
    priority: null,
    version: 1,
    created_at: new Date().toISOString(),
    ...overrides,
  } as Task;
}

function makeEvent(overrides: Partial<RealtimeEvent> = {}): RealtimeEvent {
  return {
    type: 'event',
    id: 1,
    event: 'task.updated',
    entity_type: 'task',
    entity_id: 't1',
    channel: 'project:p1',
    data: {},
    actor: { id: 'someone-else', kind: 'user' },
    request_id: null,
    activity_id: null,
    ...overrides,
  };
}

describe('applyRealtimeEvent: task.updated patches the cached list row and pane in place', () => {
  it('patches a field without touching the rest of the row', () => {
    const qc = makeQc();
    const key = taskKeys.byProject('p1');
    qc.setQueryData(key, [makeTask({ title: 'Before' })]);
    qc.setQueryData(taskKeys.detail('t1'), makeTask({ title: 'Before' }));

    applyRealtimeEvent(qc, makeEvent({ data: { changes: { title: ['Before', 'After'] } } }), {
      projectId: 'p1',
    });

    expect(qc.getQueryData<Task[]>(key)?.[0]?.title).toBe('After');
    expect((qc.getQueryData(taskKeys.detail('t1')) as Task).title).toBe('After');
  });

  it("does nothing for the actor's own echo (markMine consumes it once)", () => {
    const qc = makeQc();
    qc.setQueryData(taskKeys.byProject('p1'), [makeTask({ title: 'Before' })]);
    markMine('act-1');

    applyRealtimeEvent(
      qc,
      makeEvent({ activity_id: 'act-1', data: { changes: { title: ['Before', 'After'] } } }),
    );
    expect(qc.getQueryData<Task[]>(taskKeys.byProject('p1'))?.[0]?.title).toBe('Before');

    // a *second* event with the same activity_id (shouldn't normally happen, but the
    // registry is single-use by design) is no longer suppressed
    applyRealtimeEvent(
      qc,
      makeEvent({ activity_id: 'act-1', data: { changes: { title: ['Before', 'After'] } } }),
    );
    expect(qc.getQueryData<Task[]>(taskKeys.byProject('p1'))?.[0]?.title).toBe('After');
  });
});

describe('applyRealtimeEvent: completion and deletion', () => {
  it('task.completed marks it done, invalidates task lists, and refreshes the feed', async () => {
    const qc = makeQc();
    qc.setQueryData(taskKeys.detail('t1'), makeTask());
    qc.setQueryData(taskKeys.byProject('p1'), [makeTask()]);
    qc.setQueryData(['tasks', 't1', 'feed'], []);
    const invalidatedKeys: unknown[][] = [];
    qc.getQueryCache().subscribe((e) => {
      if (e.type === 'updated' && e.action.type === 'invalidate') invalidatedKeys.push(e.query.queryKey);
    });
    applyRealtimeEvent(qc, makeEvent({ event: 'task.completed', data: {} }));
    expect((qc.getQueryData(taskKeys.detail('t1')) as Task).completed_at).not.toBeNull();
    expect(invalidatedKeys).toContainEqual(['tasks', 't1', 'feed']);
    expect(invalidatedKeys.length).toBeGreaterThan(0);
  });

  it('task.deleted removes the row from every cached project list', () => {
    const qc = makeQc();
    qc.setQueryData(taskKeys.byProject('p1'), [makeTask(), makeTask({ id: 't2', title: 'Keep me' })]);
    applyRealtimeEvent(qc, makeEvent({ event: 'task.deleted' }));
    const rows = qc.getQueryData<Task[]>(taskKeys.byProject('p1'));
    expect(rows?.map((t) => t.id)).toEqual(['t2']);
  });
});

describe('applyRealtimeEvent: comments', () => {
  it('invalidates the comment list and feed for the right task', () => {
    const qc = makeQc();
    const commentsKey = ['tasks', 't1', 'comments'];
    const feedKeyValue = ['tasks', 't1', 'feed'];
    qc.setQueryData(commentsKey, []);
    qc.setQueryData(feedKeyValue, []);
    const invalidatedKeys: unknown[][] = [];
    qc.getQueryCache().subscribe((e) => {
      if (e.type === 'updated' && e.action.type === 'invalidate') invalidatedKeys.push(e.query.queryKey);
    });
    applyRealtimeEvent(
      qc,
      makeEvent({
        event: 'comment.created',
        entity_type: 'comment',
        entity_id: 'c1',
        data: { task_id: 't1' },
      }),
    );
    expect(invalidatedKeys).toContainEqual(commentsKey);
    expect(invalidatedKeys).toContainEqual(feedKeyValue);
  });
});

describe('applyUserChannelEvent: My Tasks / Home', () => {
  it('refreshes My Tasks and Home for a task.assigned reaching me, but not for a non-task entity', () => {
    const qc = makeQc();
    qc.setQueryData(myTasksKey(false), []);
    qc.setQueryData(homeKey, {});
    let invalidatedKeys: unknown[][] = [];
    qc.getQueryCache().subscribe((e) => {
      if (e.type === 'updated' && e.action.type === 'invalidate') invalidatedKeys.push(e.query.queryKey);
    });

    applyUserChannelEvent(qc, makeEvent({ event: 'task.assigned', channel: 'user:me', data: {} }));
    expect(invalidatedKeys).toContainEqual(myTasksKey(false));
    expect(invalidatedKeys).toContainEqual(homeKey);

    invalidatedKeys = [];
    applyUserChannelEvent(
      qc,
      makeEvent({ event: 'comment.created', entity_type: 'comment', entity_id: 'c1', channel: 'user:me' }),
    );
    expect(invalidatedKeys).toEqual([]); // not a task event: nothing to do on this channel
  });

  it('skips its own echo too', () => {
    const qc = makeQc();
    qc.setQueryData(myTasksKey(false), []);
    markMine('act-2');
    const invalidatedKeys: unknown[][] = [];
    qc.getQueryCache().subscribe((e) => {
      if (e.type === 'updated' && e.action.type === 'invalidate') invalidatedKeys.push(e.query.queryKey);
    });
    applyUserChannelEvent(
      qc,
      makeEvent({ event: 'task.assigned', activity_id: 'act-2', channel: 'user:me' }),
    );
    expect(invalidatedKeys).toEqual([]);
  });
});
