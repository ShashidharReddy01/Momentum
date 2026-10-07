import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { authHandlers } from '@/mocks/handlers';
import { homeHandlers } from '@/mocks/home';
import { projectHandlers } from '@/mocks/projects';
import { sectionHandlers } from '@/mocks/sections';
import { lastCreated, taskHandlers } from '@/mocks/tasks';
import { teamHandlers } from '@/mocks/teams';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'bypass' }));
beforeEach(() => {
  lastCreated.length = 0;
});
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const ana = '01a0ccaf-8f68-77d2-a888-584ea1e80eb1'; // mocks/teams.ts

function boot() {
  const asked: Record<string, unknown>[] = [];
  const tagged: unknown[] = [];
  server.use(
    http.post('*/api/v1/ai/task-suggestions', async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      asked.push(body);
      return HttpResponse.json({
        enabled: true,
        duplicates: [
          {
            id: 't-dup',
            key: 'T-123',
            title: 'Prepare press kit',
            completed: false,
            assignee: 'Mei Chen',
            score: 0.91,
          },
        ],
        suggestions: [
          {
            kind: 'assignee',
            label: 'Ana Souza',
            reason: '8 of 12 similar tasks were assigned to Ana',
            value: ana,
          },
          {
            kind: 'tag',
            label: 'Launch',
            reason: '7 of 12 similar tasks were tagged Launch',
            value: 'tag-1',
          },
        ],
        neighbours: 12,
      });
    }),
    http.post('*/api/v1/tasks/:id/tags', async ({ request }) => {
      tagged.push(await request.json());
      return HttpResponse.json(
        { data: { id: 'tag-1', name: 'Launch', color: 'tag-1' }, meta: { activity_id: null } },
        { status: 201 },
      );
    }),
    ...authHandlers({ loggedIn: true }).handlers,
    ...homeHandlers().handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, [{ name: 'Website Revamp', my_role: 'admin' }]),
    ...sectionHandlers('', { 'seed-1': ['Backlog'] }),
    ...taskHandlers('', { 'seed-1': { 'sec-1': ['Existing'] } }),
  );
  window.history.replaceState(null, '', '/projects/seed-1');
  render(<MomentumApp />);
  return { asked, tagged, user: userEvent.setup() };
}

describe('Smart task creation (S75-12)', () => {
  it('quick add: warns about a duplicate and applies only the chips clicked', async () => {
    const { asked, tagged, user } = boot();
    await screen.findByRole('listitem', { name: 'Existing' });
    act(() => (document.activeElement as HTMLElement | null)?.blur());
    await user.keyboard('q');
    const dialog = await screen.findByRole('dialog', { name: 'New task' });
    await user.type(within(dialog).getByRole('textbox', { name: 'Task name' }), 'Prepare the press kit');
    const warning = await within(dialog).findByText(/Looks like T-123/);
    expect(warning.closest('[role="status"]')).toHaveTextContent('(open, Mei Chen)');
    expect(within(dialog).getByRole('link', { name: 'Open' })).toHaveAttribute('href', '/task/t-dup');
    expect(asked.at(-1)).toMatchObject({ project_id: 'seed-1', title: 'Prepare the press kit' });

    const strip = within(dialog).getByRole('group', { name: 'Suggestions' });
    await user.click(within(strip).getByRole('button', { name: /Ana Souza: 8 of 12/ }));
    await user.click(within(strip).getByRole('button', { name: /Launch: 7 of 12/ }));
    await user.click(within(dialog).getByRole('button', { name: 'Not a duplicate' }));
    expect(within(dialog).queryByText(/Looks like T-123/)).toBeNull();
    await user.click(within(dialog).getByRole('button', { name: /Add task|Create/ }));
    await waitFor(() =>
      expect(lastCreated[0]).toMatchObject({ title: 'Prepare the press kit', assignee_id: ana }),
    );
    await waitFor(() => expect(tagged).toEqual([{ tag_id: 'tag-1' }]));
  });
});
