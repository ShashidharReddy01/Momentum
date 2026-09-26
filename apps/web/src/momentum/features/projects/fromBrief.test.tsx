import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { aiActionFixture, aiChatHandlers, aiHandlers } from '@/mocks/ai';
import { authHandlers } from '@/mocks/handlers';
import { notificationHandlers } from '@/mocks/notifications';
import { projectHandlers } from '@/mocks/projects';
import { teamHandlers } from '@/mocks/teams';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const TEAMS = [
  {
    id: 'team-p',
    name: 'Product',
    description: null,
    color: 'proj-7',
    version: 1,
    my_role: 'lead',
    member_count: 3,
  },
  {
    id: 'team-m',
    name: 'Marketing',
    description: null,
    color: null,
    version: 1,
    my_role: null,
    member_count: 2,
  },
];
const ACTION = aiActionFixture({
  id: 'act-brief',
  source: 'inline',
  risk: 'medium',
  summary: 'Create project Relaunch (3 sections, 6 tasks)',
  operations: [
    {
      tool: 'create_project_from_plan',
      args: {},
      summary: 'Would create project Relaunch with 3 section(s) and 6 task(s)',
      risk: 'medium',
      diff: [
        {
          entity_type: 'project',
          entity_id: 'p-new',
          label: 'Relaunch',
          verb: 'project.created',
          changes: { name: [null, 'Relaunch'] },
          display: { name: [null, 'Relaunch'] },
        },
      ],
    },
  ],
});

function boot(opts: { aiEnabled?: boolean } = {}) {
  const requests: unknown[] = [];
  const ai = aiHandlers([ACTION]);
  server.use(
    ...authHandlers({ loggedIn: true, config: { ai_enabled: opts.aiEnabled ?? true } }).handlers,
    ...teamHandlers(),
    ...projectHandlers(),
    ...ai.handlers,
    ...aiChatHandlers([]).handlers,
    ...notificationHandlers(),
    http.post('*/api/v1/ai/projects/from-brief', async ({ request }) => {
      requests.push(await request.json());
      return HttpResponse.json({
        action_id: 'act-brief',
        name: 'Relaunch',
        team: 'Product',
        start_on: '2026-10-01',
        end_on: '2026-10-31',
        tasks: 6,
        notes: ['Zed Unknown (legal) isn’t a member of Product; their tasks are unassigned.'],
        open_questions: ['Who signs off on pricing?'],
      });
    }),
  );
  server.use(
    http.get('*/api/v1/teams', () => HttpResponse.json({ data: TEAMS, meta: { next_cursor: null } })),
  );
  window.history.replaceState(null, '', '/ask'); // a page that needs nothing else
  render(<MomentumApp />);
  // applyAccept off: the test uploads a file the input's `accept` would hide, like a drag-drop
  return { requests, ai, user: userEvent.setup({ applyAccept: false }) };
}

async function openDialog(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: /Create/ }));
  await user.click(await screen.findByRole('menuitem', { name: /Project from a brief/ }));
  return screen.findByRole('dialog', { name: 'Project from a brief' });
}

describe('Project from a brief (S3.4.6)', () => {
  it('plans from a pasted brief with a deadline, shows notes and questions, applies', async () => {
    const { user, requests, ai } = boot();
    const dialog = await openDialog(user);
    await user.type(within(dialog).getByRole('textbox', { name: 'Brief' }), 'Relaunch the site by October.');
    await user.type(within(dialog).getByLabelText('Must finish by (optional)'), '2026-10-31');
    expect(within(dialog).getByRole('combobox')).toHaveValue('team-p'); // only teams I'm in
    expect(within(dialog).queryByRole('option', { name: 'Marketing' })).toBeNull();
    await user.click(within(dialog).getByRole('button', { name: /Plan it/ }));
    expect(await within(dialog).findByText(/6 tasks, 2026-10-01 to/)).toBeInTheDocument();
    expect(within(dialog).getByRole('list', { name: 'Mo adjusted' })).toHaveTextContent('Zed Unknown');
    expect(within(dialog).getByRole('list', { name: 'Open questions' })).toHaveTextContent('pricing');
    expect(requests).toEqual([
      {
        brief: 'Relaunch the site by October.',
        team_id: 'team-p',
        name: null,
        start_on: null,
        end_on: '2026-10-31',
      },
    ]);
    const card = within(dialog).getByRole('region', { name: 'Mo suggests (AI)' });
    await user.click(within(card).getByRole('button', { name: 'Apply' }));
    expect(await within(card).findByText('Applied')).toBeInTheDocument();
    expect(ai.calls.map((c) => c.path)).toEqual(['apply']);
  });

  it('reads an uploaded text file and refuses other files', async () => {
    const { user } = boot();
    const dialog = await openDialog(user);
    const input = within(dialog).getByLabelText('Upload brief');
    await user.upload(input, new File(['%PDF-1.4'], 'brief.pdf', { type: 'application/pdf' }));
    expect(
      await within(dialog).findByText('Upload a .txt or .md file, or paste the text.'),
    ).toBeInTheDocument();
    await user.upload(input, new File(['# Launch\nShip it.'], 'brief.md', { type: 'text/markdown' }));
    await waitFor(() =>
      expect(within(dialog).getByRole('textbox', { name: 'Brief' })).toHaveValue('# Launch\nShip it.'),
    );
  });

  it('not in the Create menu while AI is off', async () => {
    const { user } = boot({ aiEnabled: false });
    await user.click(await screen.findByRole('button', { name: /Create/ }));
    expect(await screen.findByRole('menuitem', { name: /^Project$/ })).toBeInTheDocument();
    expect(screen.queryByRole('menuitem', { name: /Project from a brief/ })).toBeNull();
  });
});
