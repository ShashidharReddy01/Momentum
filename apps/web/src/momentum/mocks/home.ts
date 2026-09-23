import { http, HttpResponse } from 'msw';
import type { components } from '@/lib/api/schema';

type HomeOut = components['schemas']['HomeOut'];
type MyTask = components['schemas']['MyTaskOut'];

const iso = (offsetDays: number) => {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

let n = 0;
/** A task as the Home endpoint returns it (due in `due` days; negative = overdue). */
export function homeTask(title: string, due: number | null = null, extra: Partial<MyTask> = {}): MyTask {
  n += 1;
  return {
    id: `home-${n}`,
    number: n,
    key: `T-${n}`,
    title,
    type: 'task',
    project_id: 'seed-1',
    section_id: 'sec-1',
    position: '0',
    assignee_id: '01a0ccaf-8f68-77d2-a888-584ea1e80ea8',
    start_on: null,
    due_on: due === null ? null : iso(due),
    due_at: null,
    completed_at: null,
    parent_id: null,
    priority: null,
    subtask_count: 0,
    completed_subtask_count: 0,
    version: 1,
    created_at: new Date().toISOString(),
    bucket: 'today',
    my_position: '0',
    project: { id: 'seed-1', name: 'Website Revamp', color: 'proj-6' },
    ...extra,
  };
}

export const emptyHome = (): HomeOut => ({
  priorities: [],
  counts: { open: 0, due_today: 0, overdue: 0 },
  recent_projects: [],
  waiting: [],
  waiting_total: 0,
  has_projects: true,
});

/** Stateful Home endpoint; completing a listed task removes it (as the API would). */
export function homeHandlers(base = '', initial: Partial<HomeOut> = {}) {
  const state: HomeOut = { ...emptyHome(), ...initial };
  const completed: string[] = [];
  const handlers = [
    http.get(`*${base}/api/v1/home`, () => HttpResponse.json(state)),
    http.post(`*${base}/api/v1/tasks/:id/complete`, ({ params }) => {
      const t = state.priorities.find((x) => x.id === params.id);
      if (!t) return undefined; // not a Home task: let other handlers answer
      completed.push(t.id);
      state.priorities = state.priorities.filter((x) => x.id !== t.id);
      state.counts = { ...state.counts, open: state.counts.open - 1 };
      return HttpResponse.json({
        data: { ...t, completed_at: new Date().toISOString() },
        meta: { activity_id: '01a0ccaf-0000-7000-8000-00000000h001', batch_id: null, version: 2 },
      });
    }),
  ];
  return { handlers, state, completed };
}
