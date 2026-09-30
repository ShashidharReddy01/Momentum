import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { authHandlers } from '@/mocks/handlers';
import { projectHandlers } from '@/mocks/projects';
import { teamHandlers } from '@/mocks/teams';
import { quarters } from './queries';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'bypass' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const q = quarters()[1]!;
const goal = (id: string, name: string, extra: Record<string, unknown> = {}) => ({
  id,
  name,
  description: null,
  owner_id: 'u1',
  parent_id: null,
  period_start: q.start,
  period_end: q.end,
  period_label: q.label,
  metric: null,
  progress_source: 'manual',
  status: null,
  version: 1,
  can_edit: true,
  progress: null,
  created_at: new Date().toISOString(),
  ...extra,
});
const PARENT = goal('g1', 'Win the quarter', {
  progress_source: 'subgoals',
  progress: 0.5,
  status: 'on_track',
});
const CHILD = goal('g2', 'Grow paying customers', {
  parent_id: 'g1',
  metric: { type: 'number', start: 100, target: 200, current: 150, unit: 'customers' },
  progress: 0.5,
});
const BARE = goal('g3', 'Be delightful');

function boot(path: string) {
  const posted: { url: string; body: unknown }[] = [];
  server.use(...authHandlers({ loggedIn: true }).handlers, ...teamHandlers(), ...projectHandlers());
  server.use(
    http.get('*/api/v1/goals', () => HttpResponse.json({ data: [PARENT, CHILD, BARE] })),
    http.get('*/api/v1/goals/:id', ({ params }) =>
      HttpResponse.json({
        ...(params.id === 'g2' ? CHILD : PARENT),
        links: [],
        hidden_links: params.id === 'g2' ? 1 : 0,
        children: params.id === 'g1' ? [CHILD] : [],
      }),
    ),
    http.get('*/api/v1/goals/:id/check-ins', () => HttpResponse.json({ data: [] })),
    http.post('*/api/v1/ai/goals/:id/check-in-draft', () =>
      HttpResponse.json({
        draft: { status: 'at_risk', title: 'Behind pace on customers', summary: 'Webinar leads are slow.' },
        ai: true,
      }),
    ),
    http.post('*/api/v1/ai/goals/:id/suggest-links', () =>
      HttpResponse.json({
        suggestions: [
          { entity_type: 'project', id: 'p9', name: 'Webinar series', reason: 'Task T-4 “Customer webinar”' },
        ],
      }),
    ),
    http.post('*/api/v1/goals/:id/links', async ({ request }) => {
      posted.push({ url: 'link', body: await request.json() });
      return HttpResponse.json(
        {
          data: { ...CHILD, links: [], hidden_links: 0, children: [] },
          meta: { activity_id: 'a3', version: 3 },
        },
        { status: 201 },
      );
    }),
    http.post('*/api/v1/goals', async ({ request }) => {
      posted.push({ url: 'goals', body: await request.json() });
      return HttpResponse.json(
        {
          data: { ...goal('g9', 'New'), links: [], hidden_links: 0, children: [] },
          meta: { activity_id: 'a1', version: 1 },
        },
        { status: 201 },
      );
    }),
    http.post('*/api/v1/goals/:id/check-ins', async ({ request }) => {
      posted.push({ url: 'check-in', body: await request.json() });
      return HttpResponse.json(
        {
          data: {
            id: 'c1',
            status: 'on_track',
            title: 'x',
            summary: '',
            sections: {},
            created_at: new Date().toISOString(),
            citations: [],
          },
          meta: { activity_id: 'a2', version: 2 },
        },
        { status: 201 },
      );
    }),
  );
  window.history.replaceState(null, '', path);
  render(<MomentumApp />);
  return { posted, user: userEvent.setup() };
}

describe('Goals (S6.3.1)', () => {
  it('lists this quarter’s goals as a tree, with honest progress', async () => {
    boot('/goals');
    const list = await screen.findByRole('list', { name: 'Goals' });
    const parentRow = within(list).getByRole('link', { name: 'Win the quarter' }).closest('li')!;
    expect(parentRow).toHaveTextContent('50%');
    expect(parentRow).toHaveTextContent('On track');
    expect(within(parentRow).getByRole('link', { name: 'Grow paying customers' })).toBeInTheDocument(); // nested
    const bare = within(list).getByRole('link', { name: 'Be delightful' }).closest('li')!;
    expect(bare).toHaveTextContent('No data yet'); // not a fake 0%
  });

  it('creates a goal measured by a metric', async () => {
    const { posted, user } = boot('/goals');
    await user.click(await screen.findByRole('button', { name: 'New goal' }));
    const form = await screen.findByRole('form', { name: 'New goal' });
    await user.type(within(form).getByLabelText('Goal'), 'Reach 200 customers');
    await user.type(within(form).getByLabelText('From'), '{Backspace}100');
    await user.type(within(form).getByLabelText('Target'), '200');
    await user.click(within(form).getByRole('button', { name: 'Create goal' }));
    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0]!.body).toMatchObject({
      name: 'Reach 200 customers',
      progress_source: 'manual',
      metric: { start: 100, target: 200, current: 100 },
      period_label: q.label,
    });
  });

  it('shows a goal’s metric and moves it with a check-in', async () => {
    const { posted, user } = boot('/goals/g2');
    expect(
      await screen.findByText('of 200 customers · started at 100', { exact: false }),
    ).toBeInTheDocument();
    expect(screen.getByText(/1 linked project is in projects you can’t see/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Check in' }));
    const form = await screen.findByRole('form', { name: 'New check-in' });
    await user.type(within(form).getByRole('textbox', { name: 'Headline' }), 'Webinar converted');
    await user.type(within(form).getByRole('textbox', { name: 'Current value' }), '170');
    await user.click(within(form).getByRole('button', { name: 'Post check-in' }));
    await waitFor(() => expect(posted.find((p) => p.url === 'check-in')).toBeTruthy());
    expect(posted.find((p) => p.url === 'check-in')!.body).toMatchObject({
      title: 'Webinar converted',
      current: 170,
    });
  });

  it('lets Mo draft a check-in, marked as AI, that the owner posts', async () => {
    const { posted, user } = boot('/goals/g2');
    await user.click(await screen.findByRole('button', { name: /Draft with Mo/ }));
    const form = await screen.findByRole('form', { name: 'New check-in' });
    expect(within(form).getByRole('textbox', { name: 'Headline' })).toHaveValue('Behind pace on customers');
    expect(form).toHaveTextContent('Drafted by Mo');
    await user.click(within(form).getByRole('button', { name: 'Post check-in' }));
    await waitFor(() => expect(posted.find((x) => x.url === 'check-in')).toBeTruthy());
    expect(posted.find((x) => x.url === 'check-in')!.body).toMatchObject({
      status: 'at_risk',
      generated_by_ai: true,
    });
  });

  it('suggests supporting projects that link only when chosen', async () => {
    const { posted, user } = boot('/goals/g2');
    await user.click(await screen.findByRole('button', { name: /Suggest/ }));
    const list = await screen.findByRole('list', { name: 'Suggested projects' });
    expect(list).toHaveTextContent('Webinar series');
    expect(posted.find((x) => x.url === 'link')).toBeUndefined();
    await user.click(within(list).getByRole('button', { name: 'Link' }));
    await waitFor(() =>
      expect(posted.find((x) => x.url === 'link')!.body).toEqual({ entity_type: 'project', entity_id: 'p9' }),
    );
  });
});
