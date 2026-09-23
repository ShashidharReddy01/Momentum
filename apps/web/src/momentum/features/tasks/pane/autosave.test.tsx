import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import type { ReactNode } from 'react';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { createApiClient } from '@/lib/api/client';
import { mockHash } from '@/mocks/tasks';
import { ApiContext } from '@/providers/api';
import type { TaskDetail } from '../detail';
import { useDescriptionAutosave } from './useDescriptionAutosave';

const doc = (text: string) => ({
  type: 'doc',
  content: [{ type: 'paragraph', content: [{ type: 'text', text }] }],
});
const draftKey = 'momentum.draft.description.t1';

function task(description: unknown = null): TaskDetail {
  return {
    id: 't1',
    number: 1,
    key: 'T-1',
    title: 'Spec',
    type: 'task',
    project_id: 'p',
    section_id: 's',
    position: 'a',
    assignee_id: null,
    start_on: null,
    due_on: null,
    due_at: null,
    completed_at: null,
    parent_id: null,
    priority: null,
    version: 1,
    created_at: '2026-09-01T00:00:00Z',
    subtask_count: 0,
    completed_subtask_count: 0,
    description: description as TaskDetail['description'],
    description_hash: mockHash(description),
    project: null,
    section: null,
    created_by: null,
    completed_by: null,
    updated_at: '2026-09-01T00:00:00Z',
  };
}

// A tiny server holding one task's description, with the API's conflict rule.
let server_doc: unknown = null;
let mode: 'ok' | 'down' | 'signed-out' = 'ok';
const saves: { base: unknown; description: unknown }[] = [];
const server = setupServer(
  http.patch('*/api/v1/tasks/t1', async ({ request }) => {
    if (mode === 'down') return HttpResponse.error();
    if (mode === 'signed-out')
      return HttpResponse.json({ code: 'unauthenticated', status: 401 }, { status: 401 });
    const body = (await request.json()) as { description: unknown; description_base?: string };
    saves.push({ base: body.description_base, description: body.description });
    if (body.description_base !== undefined && body.description_base !== mockHash(server_doc))
      return HttpResponse.json({ code: 'version_conflict', status: 409 }, { status: 409 });
    server_doc = body.description;
    return HttpResponse.json({ data: task(server_doc), meta: {} });
  }),
  http.get('*/api/v1/tasks/t1', () => HttpResponse.json(task(server_doc))),
);
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  // unmount first: an unmounting editor (correctly) persists its draft
  cleanup();
  server.resetHandlers();
  localStorage.clear();
  saves.length = 0;
  server_doc = null;
  mode = 'ok';
});
afterAll(() => server.close());

function setup(initial: unknown = null, canEdit = true) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const api = createApiClient('');
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>
      <ApiContext.Provider value={api}>{children}</ApiContext.Provider>
    </QueryClientProvider>
  );
  return renderHook(({ t }) => useDescriptionAutosave(t, canEdit, { saveAfterMs: 20, retryMs: [30] }), {
    wrapper,
    initialProps: { t: task(initial) },
  });
}

describe('description autosave', () => {
  it('writes a local draft first, then saves against the base hash and clears the draft', async () => {
    const { result } = setup();
    act(() => result.current.onChange(doc('Hello')));
    await waitFor(() => expect(localStorage.getItem(draftKey)).toContain('Hello'));
    await waitFor(() => expect(result.current.state).toBe('saved'));
    expect(saves).toEqual([{ base: '', description: doc('Hello') }]);
    expect(localStorage.getItem(draftKey)).toBeNull();
    // the next save uses the new base
    act(() => result.current.onChange(doc('Hello again')));
    await waitFor(() => expect(saves).toHaveLength(2));
    expect(saves[1]!.base).toBe(mockHash(doc('Hello')));
  });

  it('on a concurrent edit shows both versions; "keep mine" saves over theirs knowingly', async () => {
    const { result } = setup();
    server_doc = doc('Theirs'); // someone else saved meanwhile
    act(() => result.current.onChange(doc('Mine')));
    await waitFor(() => expect(result.current.state).toBe('conflict'));
    expect(result.current.conflict?.theirs).toEqual(doc('Theirs'));
    expect(server_doc).toEqual(doc('Theirs')); // nothing overwritten
    expect(localStorage.getItem(draftKey)).toContain('Mine'); // nothing lost
    // typing during a conflict is still kept locally and never auto-saved
    act(() => result.current.onChange(doc('Mine, edited')));
    await new Promise((r) => setTimeout(r, 60));
    expect(saves.at(-1)!.description).toEqual(doc('Mine'));
    act(() => result.current.keepMine());
    await waitFor(() => expect(server_doc).toEqual(doc('Mine, edited')));
    expect(result.current.state).toBe('saved');
  });

  it('"use theirs" loads their text and drops the draft', async () => {
    const { result } = setup();
    server_doc = doc('Theirs');
    act(() => result.current.onChange(doc('Mine')));
    await waitFor(() => expect(result.current.state).toBe('conflict'));
    act(() => result.current.useTheirs());
    expect(result.current.content.doc).toEqual(doc('Theirs'));
    expect(result.current.state).toBe('saved');
    expect(localStorage.getItem(draftKey)).toBeNull();
  });

  it('offline: keeps the draft and retries until the server is back', async () => {
    const { result } = setup();
    mode = 'down';
    act(() => result.current.onChange(doc('Offline text')));
    await waitFor(() => expect(result.current.state).toBe('offline'));
    expect(localStorage.getItem(draftKey)).toContain('Offline text');
    mode = 'ok';
    await waitFor(() => expect(server_doc).toEqual(doc('Offline text')));
    await waitFor(() => expect(result.current.state).toBe('saved'));
  });

  it('signed out: keeps the draft; the next open resumes and saves it', async () => {
    const first = setup();
    mode = 'signed-out';
    act(() => first.result.current.onChange(doc('Typed before expiry')));
    await waitFor(() => expect(first.result.current.state).toBe('signed-out'));
    first.unmount();
    expect(localStorage.getItem(draftKey)).toContain('Typed before expiry');
    // after signing in again
    mode = 'ok';
    const second = setup();
    expect(second.result.current.content.doc).toEqual(doc('Typed before expiry'));
    await waitFor(() => expect(server_doc).toEqual(doc('Typed before expiry')));
    await waitFor(() => expect(localStorage.getItem(draftKey)).toBeNull());
  });

  it('a draft whose base is outdated opens as a conflict instead of overwriting', async () => {
    localStorage.setItem(draftKey, JSON.stringify({ doc: doc('Old draft'), base: '', at: Date.now() }));
    server_doc = doc('Newer server text');
    const { result } = setup(server_doc);
    expect(result.current.state).toBe('conflict');
    expect(result.current.content.doc).toEqual(doc('Old draft'));
    expect(saves).toHaveLength(0);
  });

  it('closing the pane mid-edit saves (and keeps the draft until it lands)', async () => {
    const { result, unmount } = setup();
    act(() => result.current.onChange(doc('Closing fast')));
    unmount();
    expect(localStorage.getItem(draftKey)).toContain('Closing fast');
    await waitFor(() => expect(server_doc).toEqual(doc('Closing fast')));
  });

  it('ignores editor updates that do not change the content (no phantom saves)', async () => {
    const { result } = setup(doc('Same'));
    act(() => result.current.onChange(doc('Same')));
    await new Promise((r) => setTimeout(r, 60));
    expect(saves).toHaveLength(0);
    expect(result.current.state).toBe('saved');
  });

  it('shows another person’s edit when there are no local changes; read-only never saves', async () => {
    const { result, rerender } = setup(doc('v1'));
    rerender({ t: task(doc('v2 from Ana')) });
    await waitFor(() => expect(result.current.content.doc).toEqual(doc('v2 from Ana')));
    const ro = setup(null, false);
    act(() => ro.result.current.onChange(doc('nope')));
    await new Promise((r) => setTimeout(r, 60));
    expect(saves).toHaveLength(0);
  });
});
