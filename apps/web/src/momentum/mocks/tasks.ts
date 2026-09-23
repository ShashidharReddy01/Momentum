import { delay, http, HttpResponse } from 'msw';

type T = {
  id: string;
  number: number;
  key: string;
  title: string;
  type: string;
  project_id: string;
  section_id: string;
  position: string;
  assignee_id: string | null;
  start_on: string | null;
  due_on: string | null;
  due_at: string | null;
  completed_at: string | null;
  parent_id: string | null;
  priority: null;
  subtask_count?: number;
  completed_subtask_count?: number;
  version: number;
  created_at: string;
  description?: unknown;
};

// Same contract as the API: a short fingerprint of the description ('' when empty).
export const mockHash = (doc: unknown) =>
  doc ? `h${JSON.stringify(doc).length}-${JSON.stringify(doc).slice(-12)}` : '';

/** In-memory tasks API with a small network delay (exercises optimistic UI and the create queue). */
/** Bodies of task creates (tests assert on them). */
export const lastCreated: Record<string, unknown>[] = [];

/** Moves made through the My Tasks mock (tests assert on them). */
export const myMoves: { id: string; bucket: string; after_id?: string; before_id?: string }[] = [];

export function taskHandlers(
  base = '',
  initial: Record<string, Record<string, string[]>> = {},
  latency = 15,
  /** Titles assigned to the signed-in user from the start (My Tasks tests). */
  assignedToMe: string[] = [],
) {
  const tasks: T[] = [];
  let n = 0;
  const pos = (i: number) => String(100000 + i * 100).padStart(8, '0');
  const make = (pid: string, sid: string, title: string, position: string): T => {
    n += 1;
    return {
      id: `task-${n}`,
      number: n,
      key: `T-${n}`,
      title,
      type: 'task',
      project_id: pid,
      section_id: sid,
      position,
      assignee_id: null,
      start_on: null,
      due_on: null,
      due_at: null,
      completed_at: null,
      parent_id: null,
      priority: null,
      version: 1,
      created_at: new Date().toISOString(),
    };
  };
  for (const [pid, sections] of Object.entries(initial)) {
    for (const [sid, titles] of Object.entries(sections)) {
      titles.forEach((title, i) => tasks.push(make(pid, sid, title, pos(i))));
    }
  }
  for (const t of tasks)
    if (assignedToMe.includes(t.title)) t.assignee_id = '01a0ccaf-8f68-77d2-a888-584ea1e80ea8';
  const inSection = (sid: string) =>
    tasks.filter((t) => t.section_id === sid).sort((a, b) => (a.position < b.position ? -1 : 1));
  const renumber = (ordered: T[]) => ordered.forEach((t, i) => (t.position = pos(i)));
  const meta = { activity_id: '01a0ccaf-0000-7000-8000-00000000d001', batch_id: null, version: 1 };
  const place = (t: T, afterId?: string | null, beforeId?: string | null) => {
    const rest = inSection(t.section_id).filter((x) => x.id !== t.id);
    const i = afterId
      ? rest.findIndex((x) => x.id === afterId) + 1
      : beforeId
        ? rest.findIndex((x) => x.id === beforeId)
        : rest.length;
    renumber([...rest.slice(0, i), t, ...rest.slice(i)]);
  };
  const moveMany = (ids: string[], sid: string, afterId?: string | null, beforeId?: string | null) => {
    const moving = ids.map((id) => tasks.find((x) => x.id === id)!);
    const sources = new Set(moving.map((t) => t.section_id));
    let after = afterId ?? null;
    let before = beforeId ?? null;
    for (const t of moving) {
      t.section_id = sid;
      place(t, after, after ? null : before);
      after = t.id;
      before = null;
    }
    sources.forEach((s) => renumber(inSection(s)));
    return moving;
  };

  const prefs = new Map<string, unknown>();
  const followers = new Map<string, string[]>();
  type C = {
    id: string;
    task_id: string;
    author_id: string;
    body: unknown;
    is_ai: boolean;
    created_at: string;
    edited_at: string | null;
    reactions: { emoji: string; user_ids: string[] }[];
    can_edit: boolean;
    can_delete: boolean;
  };
  const comments: C[] = [];
  const me = '01a0ccaf-8f68-77d2-a888-584ea1e80ea8';
  const MY_BUCKETS = ['recently_assigned', 'today', 'this_week', 'later'];
  const myPlacements = new Map<string, { bucket: string; pos: number }>();
  let myTop = 0;
  const childrenOf = (id: string) =>
    tasks.filter((t) => t.parent_id === id).sort((a, b) => (a.position < b.position ? -1 : 1));
  const withCounts = (t: T): T => {
    const kids = childrenOf(t.id);
    return {
      ...t,
      subtask_count: kids.length,
      completed_subtask_count: kids.filter((k) => k.completed_at).length,
    };
  };
  const detail = (t: T) => ({
    ...t,
    description: t.description ?? null,
    description_hash: mockHash(t.description),
    project: { id: t.project_id, name: 'Website Revamp', color: 'proj-6' },
    section: t.parent_id ? null : { id: t.section_id, name: t.section_id === 'sec-1' ? 'Backlog' : 'Done' },
    parent: t.parent_id
      ? { id: t.parent_id, name: tasks.find((x) => x.id === t.parent_id)?.title ?? '' }
      : null,
    created_by: '01a0ccaf-8f68-77d2-a888-584ea1e80ea8',
    completed_by: null,
    followers: followers.get(t.id) ?? ['01a0ccaf-8f68-77d2-a888-584ea1e80ea8'],
    my_role: 'admin',
    updated_at: new Date().toISOString(),
  });
  return [
    http.get(`*${base}/api/v1/me/tasks`, ({ request }) => {
      const completed = new URL(request.url).searchParams.get('completed') === 'true';
      const mine = tasks.filter((t) => t.assignee_id === me && !!t.completed_at === completed);
      // same lazy sync as the API: new assignments go to the top of "Recently assigned"
      for (const t of mine)
        if (!myPlacements.has(t.id)) myPlacements.set(t.id, { bucket: 'recently_assigned', pos: -++myTop });
      const rank = (b: string) => MY_BUCKETS.indexOf(b);
      const rows = mine
        .map((t) => ({ t, p: myPlacements.get(t.id)! }))
        .sort((a, b) =>
          completed
            ? (b.t.completed_at ?? '').localeCompare(a.t.completed_at ?? '')
            : rank(a.p.bucket) - rank(b.p.bucket) || a.p.pos - b.p.pos,
        );
      return HttpResponse.json({
        data: rows.map(({ t, p }) => ({
          ...withCounts(t),
          bucket: p.bucket,
          my_position: String(p.pos),
          project: { id: t.project_id, name: 'Website Revamp', color: 'proj-6' },
        })),
        meta: {},
      });
    }),
    http.post(`*${base}/api/v1/me/tasks/:id/move`, async ({ params, request }) => {
      await delay(latency);
      const body = (await request.json()) as { bucket: string; after_id?: string; before_id?: string };
      const id = String(params.id);
      const inBucket = [...myPlacements.entries()]
        .filter(([tid, p]) => p.bucket === body.bucket && tid !== id)
        .sort((a, b) => a[1].pos - b[1].pos)
        .map(([tid]) => tid);
      const i = body.after_id
        ? inBucket.indexOf(body.after_id) + 1
        : body.before_id
          ? inBucket.indexOf(body.before_id)
          : inBucket.length;
      const order = [...inBucket.slice(0, i), id, ...inBucket.slice(i)];
      order.forEach((tid, k) => myPlacements.set(tid, { bucket: body.bucket, pos: k }));
      myMoves.push({ id, ...body });
      return HttpResponse.json({ data: { ok: true }, meta });
    }),
    http.get(`*${base}/api/v1/me/prefs/views/:pid`, ({ params }) =>
      HttpResponse.json(
        prefs.get(String(params.pid)) ?? {
          assignees: [],
          due: 'any',
          show_completed: false,
          sort: 'manual',
          group: 'section',
        },
      ),
    ),
    http.put(`*${base}/api/v1/me/prefs/views/:pid`, async ({ params, request }) => {
      const body = await request.json();
      prefs.set(String(params.pid), body);
      return HttpResponse.json(body);
    }),
    http.get(`*${base}/api/v1/projects/:pid/tasks`, ({ params, request }) => {
      const completed = new URL(request.url).searchParams.get('completed') === 'true';
      const data = tasks
        .filter((t) => t.project_id === params.pid && !t.parent_id && !!t.completed_at === completed)
        .sort((a, b) => (a.section_id + a.position < b.section_id + b.position ? -1 : 1))
        .map(withCounts);
      return HttpResponse.json({ data, meta: { next_cursor: null } });
    }),
    http.post(`*${base}/api/v1/projects/:pid/tasks`, async ({ params, request }) => {
      await delay(latency);
      const b = (await request.json()) as {
        title: string;
        section_id?: string;
        after_id?: string | null;
        assignee_id?: string | null;
        due_on?: string | null;
        due_at?: string | null;
      };
      // like the API: no section → the project's first one
      const sid = b.section_id ?? tasks.find((x) => x.project_id === params.pid)?.section_id ?? 'sec-1';
      const t = make(String(params.pid), sid, b.title, '');
      t.assignee_id = b.assignee_id ?? null;
      t.due_at = b.due_at ?? null;
      t.due_on = b.due_on ?? (b.due_at ? b.due_at.slice(0, 10) : null);
      tasks.push(t);
      lastCreated.push(b);
      place(t, b.after_id);
      return HttpResponse.json({ data: t, meta }, { status: 201 });
    }),
    http.post(`*${base}/api/v1/projects/:pid/tasks/batch`, async ({ params, request }) => {
      const b = (await request.json()) as { titles: string[]; section_id: string; after_id?: string | null };
      let after = b.after_id ?? null;
      const created = b.titles.map((title) => {
        const t = make(String(params.pid), b.section_id, title, '');
        tasks.push(t);
        place(t, after);
        after = t.id;
        return t;
      });
      return HttpResponse.json(
        { data: { data: created, meta: {} }, meta: { ...meta, batch_id: 'batch-1' } },
        { status: 201 },
      );
    }),
    http.post(`*${base}/api/v1/tasks/:id/move`, async ({ params, request }) => {
      await delay(latency);
      const b = (await request.json()) as {
        section_id: string;
        after_id?: string | null;
        before_id?: string | null;
      };
      const [t] = moveMany([String(params.id)], b.section_id, b.after_id, b.before_id);
      return HttpResponse.json({ data: t, meta });
    }),
    http.post(`*${base}/api/v1/tasks/bulk`, async ({ request }) => {
      await delay(latency);
      const b = (await request.json()) as {
        task_ids: string[];
        action: string;
        patch?: Partial<T>;
        section_id?: string;
        after_id?: string | null;
        before_id?: string | null;
      };
      let out: T[] = [];
      if (b.action === 'move') out = moveMany(b.task_ids, b.section_id!, b.after_id, b.before_id);
      else
        for (const id of b.task_ids) {
          const i = tasks.findIndex((x) => x.id === id);
          const t = tasks[i]!;
          if (b.action === 'delete') tasks.splice(i, 1);
          else if (b.action === 'complete') t.completed_at = new Date().toISOString();
          else if (b.action === 'uncomplete') t.completed_at = null;
          else Object.assign(t, b.patch);
          out.push(t);
        }
      return HttpResponse.json({ data: { data: out, meta: {} }, meta: { ...meta, batch_id: 'batch-2' } });
    }),
    http.post(`*${base}/api/v1/tasks/:id/followers`, async ({ params, request }) => {
      const { user_id } = (await request.json()) as { user_id: string };
      const id = String(params.id);
      const list = followers.get(id) ?? ['01a0ccaf-8f68-77d2-a888-584ea1e80ea8'];
      followers.set(id, list.includes(user_id) ? list : [...list, user_id]);
      return HttpResponse.json({ data: { followers: followers.get(id) }, meta });
    }),
    http.delete(`*${base}/api/v1/tasks/:id/followers/:uid`, ({ params }) => {
      const id = String(params.id);
      const list = followers.get(id) ?? ['01a0ccaf-8f68-77d2-a888-584ea1e80ea8'];
      followers.set(
        id,
        list.filter((f) => f !== params.uid),
      );
      return HttpResponse.json({ data: { followers: followers.get(id) }, meta });
    }),
    http.get(`*${base}/api/v1/tasks/:id/comments`, ({ params }) =>
      HttpResponse.json({
        data: comments.filter((c) => c.task_id === params.id),
        meta: { next_cursor: null },
      }),
    ),
    http.post(`*${base}/api/v1/tasks/:id/comments`, async ({ params, request }) => {
      const { body } = (await request.json()) as { body: unknown };
      const c: C = {
        id: `c-${comments.length + 1}`,
        task_id: String(params.id),
        author_id: me,
        body,
        is_ai: false,
        created_at: new Date().toISOString(),
        edited_at: null,
        reactions: [],
        can_edit: true,
        can_delete: true,
      };
      comments.push(c);
      return HttpResponse.json({ data: c, meta }, { status: 201 });
    }),
    http.patch(`*${base}/api/v1/comments/:cid`, async ({ params, request }) => {
      const c = comments.find((x) => x.id === params.cid)!;
      c.body = ((await request.json()) as { body: unknown }).body;
      c.edited_at = new Date().toISOString();
      return HttpResponse.json({ data: c, meta });
    }),
    http.delete(`*${base}/api/v1/comments/:cid`, ({ params }) => {
      comments.splice(
        comments.findIndex((x) => x.id === params.cid),
        1,
      );
      return HttpResponse.json({ data: { ok: true }, meta });
    }),
    http.post(`*${base}/api/v1/comments/:cid/reactions`, async ({ params, request }) => {
      const c = comments.find((x) => x.id === params.cid)!;
      const { emoji, active } = (await request.json()) as { emoji: string; active: boolean };
      const r = c.reactions.find((x) => x.emoji === emoji);
      if (active && !r) c.reactions.push({ emoji, user_ids: [me] });
      else if (active && r && !r.user_ids.includes(me)) r.user_ids.push(me);
      else if (!active && r) r.user_ids = r.user_ids.filter((u) => u !== me);
      c.reactions = c.reactions.filter((x) => x.user_ids.length);
      return HttpResponse.json({ data: c, meta: {} });
    }),
    http.get(`*${base}/api/v1/tasks/:id/feed`, ({ params }) => {
      const t = tasks.find((x) => x.id === params.id);
      const created = t
        ? [
            {
              kind: 'activity',
              at: t.created_at,
              activity: {
                id: `act-${t.id}`,
                verb: 'task.created',
                actor_id: me,
                actor_kind: 'user',
                created_at: t.created_at,
                changes: { title: [null, t.title] },
                subject: null,
              },
            },
          ]
        : [];
      const items = comments
        .filter((c) => c.task_id === params.id)
        .map((c) => ({ kind: 'comment', at: c.created_at, comment: c }));
      return HttpResponse.json({ data: [...created, ...items], truncated: false });
    }),
    http.get(`*${base}/api/v1/mentions/search`, () =>
      HttpResponse.json({
        users: [{ id: me, name: 'Ravi Kumar', email: 'ravi@acme-demo.test' }],
        tasks: [],
        projects: [],
      }),
    ),
    http.get(`*${base}/api/v1/tasks/:id/subtasks`, ({ params }) =>
      HttpResponse.json({ data: childrenOf(String(params.id)).map(withCounts), meta: { next_cursor: null } }),
    ),
    http.post(`*${base}/api/v1/tasks/:id/subtasks`, async ({ params, request }) => {
      await delay(latency);
      const b = (await request.json()) as { title: string; after_id?: string | null };
      const parent = tasks.find((x) => x.id === params.id)!;
      const siblings = childrenOf(parent.id);
      const t = make(parent.project_id, '', b.title, '');
      t.parent_id = parent.id;
      const i = b.after_id ? siblings.findIndex((x) => x.id === b.after_id) + 1 : siblings.length;
      [...siblings.slice(0, i), t, ...siblings.slice(i)].forEach((x, k) => (x.position = pos(k)));
      tasks.push(t);
      return HttpResponse.json({ data: withCounts(t), meta }, { status: 201 });
    }),
    http.post(`*${base}/api/v1/tasks/:id/outdent`, ({ params }) => {
      const t = tasks.find((x) => x.id === params.id)!;
      const parent = tasks.find((x) => x.id === t.parent_id)!;
      t.parent_id = parent.parent_id;
      t.section_id = parent.section_id;
      place(t, parent.id);
      return HttpResponse.json({ data: withCounts(t), meta });
    }),
    http.get(`*${base}/api/v1/tasks/:id`, ({ params }) => {
      const t = tasks.find((x) => x.id === params.id);
      if (!t) return HttpResponse.json({ code: 'not_found', status: 404 }, { status: 404 });
      return HttpResponse.json(withCounts(detail(t) as unknown as T));
    }),
    http.patch(`*${base}/api/v1/tasks/:id`, async ({ params, request }) => {
      await delay(latency);
      const t = tasks.find((x) => x.id === params.id)!;
      const body = (await request.json()) as Record<string, unknown>;
      if (
        'description' in body &&
        typeof body.description_base === 'string' &&
        body.description_base !== mockHash(t.description)
      ) {
        return HttpResponse.json(
          { code: 'version_conflict', status: 409, title: 'Version conflict' },
          { status: 409 },
        );
      }
      const fields = { ...body };
      delete fields.description_base;
      Object.assign(t, fields);
      t.version += 1;
      return HttpResponse.json({ data: detail(t), meta });
    }),
    http.post(`*${base}/api/v1/tasks/:id/complete`, ({ params }) => {
      const t = tasks.find((x) => x.id === params.id)!;
      t.completed_at = new Date().toISOString();
      return HttpResponse.json({ data: t, meta });
    }),
    http.post(`*${base}/api/v1/tasks/:id/uncomplete`, ({ params }) => {
      const t = tasks.find((x) => x.id === params.id)!;
      t.completed_at = null;
      return HttpResponse.json({ data: t, meta });
    }),
    http.post(`*${base}/api/v1/undo`, () => {
      // emulate undo of the last completion in tests
      const t = [...tasks].reverse().find((x) => x.completed_at);
      if (t) t.completed_at = null;
      return HttpResponse.json({ undone: [] });
    }),
    http.delete(`*${base}/api/v1/tasks/:id`, ({ params }) => {
      tasks.splice(
        tasks.findIndex((x) => x.id === params.id),
        1,
      );
      return HttpResponse.json({ data: { ok: true }, meta });
    }),
  ];
}
