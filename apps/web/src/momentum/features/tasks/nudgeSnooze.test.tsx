import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { authHandlers } from '@/mocks/handlers';
import { projectHandlers } from '@/mocks/projects';
import { sectionHandlers } from '@/mocks/sections';
import { taskHandlers } from '@/mocks/tasks';
import { teamHandlers } from '@/mocks/teams';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  server.resetHandlers();
  window.localStorage.clear();
});
afterAll(() => server.close());

describe('Snooze Nudge reminders (S5.3.4)', () => {
  it('offers the snooze on my own task and sends the date', async () => {
    const sent: unknown[] = [];
    server.use(
      ...authHandlers({ loggedIn: true }).handlers,
      ...teamHandlers(),
      ...projectHandlers('', undefined, [{ name: 'Website Revamp', my_role: 'admin' }]),
      ...sectionHandlers('', { 'seed-1': ['Backlog'] }),
      ...taskHandlers('', { 'seed-1': { 'sec-1': ['First'] } }),
      http.put('*/api/v1/me/tasks/:taskId/nudge-snooze', async ({ request }) => {
        sent.push(await request.json());
        return HttpResponse.json({
          data: { ok: true },
          meta: { activity_id: 'a1', batch_id: null, version: null },
        });
      }),
    );
    window.history.replaceState(null, '', '/projects/seed-1');
    render(<MomentumApp />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Open details for First' }));
    const pane = await screen.findByRole('complementary', { name: 'Task details' });

    // not mine yet: no snooze
    await user.click(within(pane).getByRole('button', { name: 'More actions' }));
    expect(screen.queryByRole('menuitem', { name: /Snooze Nudge/ })).toBeNull();
    await user.keyboard('{Escape}');

    await user.click(within(pane).getByRole('button', { name: 'Assign' }));
    await user.click(await screen.findByRole('option', { name: /Assign to me/ }));
    await user.click(within(pane).getByRole('button', { name: 'More actions' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Snooze Nudge reminders for a week' }));
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toEqual({ until: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/) });

    await user.click(within(pane).getByRole('button', { name: 'More actions' }));
    expect(await screen.findByRole('menuitem', { name: /Resume Nudge reminders/ })).toBeInTheDocument();
  });
});
