import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { authHandlers } from '@/mocks/handlers';
import { projectHandlers } from '@/mocks/projects';
import { searchHandlers } from '@/mocks/search';
import { sectionHandlers } from '@/mocks/sections';
import { taskHandlers } from '@/mocks/tasks';
import { teamHandlers } from '@/mocks/teams';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'bypass' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function boot(path: string) {
  const asked: Record<string, unknown>[] = [];
  const saved: Record<string, unknown>[] = [];
  server.use(
    http.post('*/api/v1/ai/filters', async ({ request }) => {
      const body = (await request.json()) as { text: string; surface: string };
      asked.push(body);
      if (body.text.includes('urgent'))
        return HttpResponse.json({
          surface: body.surface,
          filters: {},
          chips: [],
          question: 'There’s no tag called "urgent". Which tag did you mean?',
          options: ['Escalated', 'Needs review'],
        });
      if (body.surface === 'search')
        return HttpResponse.json({
          surface: 'search',
          filters: { q: 'pricing', completed: true, type: ['task', 'comment'] },
          chips: [
            { key: 'q', label: '“pricing”' },
            { key: 'completed', label: 'Completed' },
          ],
          question: null,
          options: [],
        });
      return HttpResponse.json({
        surface: body.surface,
        filters: { assignees: ['me'], due: 'overdue' },
        chips: [
          { key: 'assignees', label: 'Assignee: me' },
          { key: 'due', label: 'Overdue' },
        ],
        question: null,
        options: [],
      });
    }),
    http.put('*/api/v1/me/prefs/views/:pid', async ({ request }) => {
      saved.push((await request.json()) as Record<string, unknown>);
      return HttpResponse.json(saved.at(-1));
    }),
    ...authHandlers({ loggedIn: true }).handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, [{ name: 'Website Revamp', my_role: 'admin' }]),
    ...sectionHandlers('', { 'seed-1': ['Backlog'] }),
    ...taskHandlers('', { 'seed-1': { 'sec-1': ['First'] } }),
    ...searchHandlers(''),
  );
  window.history.replaceState(null, '', path);
  render(<MomentumApp />);
  return { asked, saved, user: userEvent.setup() };
}

describe('Plain-English filters (S75-11)', () => {
  it('a list view: asks back with real options, then applies chips only on Apply (Enter)', async () => {
    const { asked, saved, user } = boot('/projects/seed-1/list');
    const box = await screen.findByRole('textbox', { name: 'Describe what to show' });
    await user.type(box, 'Tasks tagged urgent{Enter}');
    expect(await screen.findByText(/no tag called "urgent"/)).toBeInTheDocument();
    expect(screen.getByText('Options: Escalated, Needs review')).toBeInTheDocument();
    expect(asked[0]).toMatchObject({ surface: 'list', project_id: 'seed-1' });

    await user.clear(box);
    await user.type(box, 'My overdue tasks{Enter}');
    const chips = await screen.findByRole('group', { name: "Mo's filters" });
    expect(within(chips).getByText('Assignee: me')).toHaveClass('text-amber-ink');
    expect(saved.some((b) => (b.assignees as string[] | undefined)?.length)).toBe(false); // not yet
    await waitFor(() => expect(within(chips).getByRole('button', { name: 'Apply' })).toHaveFocus());
    await user.keyboard('{Enter}');
    expect(await screen.findByText('Filtered with Mo')).toBeInTheDocument();
    await waitFor(() => expect(saved.at(-1)).toMatchObject({ assignees: ['me'], due: 'overdue' }), {
      timeout: 2000,
    });
    // Clear puts the view back as it was
    await user.click(screen.getByRole('button', { name: "Clear Mo's filters" }));
    await waitFor(() => expect(screen.queryByText('Filtered with Mo')).toBeNull());
    await waitFor(() => expect(saved.at(-1)).toMatchObject({ assignees: [], due: 'any' }), { timeout: 2000 });
  });

  it('search: the draft becomes the page’s own params', async () => {
    const { asked, user } = boot('/search');
    await user.type(
      await screen.findByRole('textbox', { name: 'Describe what to show' }),
      'Finished tasks and comments about pricing{Enter}',
    );
    const chips = await screen.findByRole('group', { name: "Mo's filters" });
    await user.click(within(chips).getByRole('button', { name: 'Apply' }));
    await waitFor(() => expect(window.location.search).toContain('q=pricing'));
    expect(window.location.search).toContain('completed=true');
    expect(window.location.search).toContain('type=task%2Ccomment');
    expect(screen.getByText('Filtered with Mo')).toBeInTheDocument();
    expect(asked[0]).toMatchObject({ surface: 'search' });
  });
});
