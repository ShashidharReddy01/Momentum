import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { authHandlers } from '@/mocks/handlers';
import { projectHandlers } from '@/mocks/projects';
import { sectionHandlers } from '@/mocks/sections';
import { taskHandlers } from '@/mocks/tasks';
import { teamHandlers } from '@/mocks/teams';
import { UndoStack } from './undo';

describe('UndoStack', () => {
  it('keeps newest last, ignores actions without a handle, dedupes, removes, and expires', () => {
    const s = new UndoStack();
    expect(s.push('nothing', {})).toBeNull();
    s.push('a', { activity_id: 'a1' });
    s.push('b', { batch_id: 'b1' });
    s.push('a again', { activity_id: 'a1' }); // same action: moves to the top
    expect(s.size).toBe(2);
    expect(s.pop()?.label).toBe('a again');
    s.remove('b1');
    expect(s.pop()).toBeUndefined();
    vi.useFakeTimers({ toFake: ['Date'] });
    s.push('old', { activity_id: 'o1' });
    vi.setSystemTime(Date.now() + 25 * 3600_000);
    expect(s.pop()).toBeUndefined(); // past the server's 24h window
    vi.useRealTimers();
  });
});

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe('⌘Z', () => {
  it('undoes the last action outside text fields, and leaves text fields alone', async () => {
    const undos: unknown[] = [];
    server.use(
      http.post('*/api/v1/undo', async ({ request }) => {
        undos.push(await request.json());
        return HttpResponse.json({ undone: [] });
      }),
      ...authHandlers({ loggedIn: true }).handlers,
      ...teamHandlers(),
      ...projectHandlers('', undefined, [{ name: 'Website Revamp', my_role: 'admin' }]),
      ...sectionHandlers('', { 'seed-1': ['Backlog'] }),
      ...taskHandlers('', { 'seed-1': { 'sec-1': ['One', 'Two'] } }),
    );
    window.history.replaceState(null, '', '/projects/seed-1');
    render(<MomentumApp />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Two' }));
    const input = screen.getByRole('textbox', { name: 'Task name' });
    await user.keyboard('{Control>}z{/Control}'); // inside a text field: native undo, no API call
    expect(undos).toHaveLength(0);
    await user.type(input, '!{Enter}{Escape}');
    await waitFor(() => expect(screen.getByRole('listitem', { name: 'Two!' })).toBeInTheDocument());
    const row = screen.getByRole('listitem', { name: 'Two!' });
    row.focus();
    await user.keyboard('{Control>}z{/Control}');
    await waitFor(() => expect(undos).toHaveLength(1));
    expect(await screen.findByText('Undone: Task renamed')).toBeInTheDocument();
    await user.keyboard('{Control>}z{/Control}');
    expect(await screen.findByText('Nothing to undo')).toBeInTheDocument();
    expect(within(document.body).queryAllByText(/Couldn't undo/)).toHaveLength(0);
  });
});
