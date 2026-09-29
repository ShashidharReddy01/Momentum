import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { aiActionFixture, aiHandlers } from '@/mocks/ai';
import { agentFixture, agentHandlers, runFixture, statsFixture } from '@/mocks/agents';
import { authHandlers } from '@/mocks/handlers';
import { projectHandlers } from '@/mocks/projects';
import { teamHandlers } from '@/mocks/teams';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function boot(
  path: string,
  agents: ReturnType<typeof agentHandlers>,
  extra: Parameters<typeof server.use> = [],
  role = 'member',
  projects: Parameters<typeof projectHandlers>[2] = [],
) {
  server.use(
    ...authHandlers({ loggedIn: true, me: { role } }).handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, projects),
    ...agents.handlers,
    ...extra,
  );
  window.history.replaceState(null, '', path);
  render(<MomentumApp />);
  return userEvent.setup();
}

describe('Agent runs (S5.1.3)', () => {
  it('explains a run: why, each step, the answer, cost, and what waits for you', async () => {
    const action = aiActionFixture({ id: 'act-1' });
    const ai = aiHandlers([action]);
    const run = runFixture({
      actions: [
        {
          id: 'act-1',
          summary: 'Would set priority high',
          state: 'proposed',
          risk: 'low',
          proposed_for: { id: 'u-1', name: 'Ravi Kumar' },
          mine: true,
        },
      ],
    });
    boot('/agents/runs/run-1', agentHandlers({ run }), ai.handlers);

    expect(await screen.findByRole('heading', { name: 'Run · Assigned a task' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Teammate/ })).toHaveAttribute('href', '/agents/agent-1');
    expect(screen.getByText('Done')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'T-12 Research competitor pricing' })).toHaveAttribute(
      'href',
      '/task/t-1',
    );
    expect(screen.getByText(/1,500 tokens · <\$0\.01/)).toBeInTheDocument();
    const steps = screen.getByRole('region', { name: 'Steps' });
    expect(within(steps).getByText('search_tasks')).toBeInTheDocument();
    expect(within(steps).getByText('Found 3 tasks')).toBeInTheDocument();
    // AI-authored answer carries the amber AI marking
    expect(screen.getByRole('region', { name: 'Teammate answered (AI)' })).toHaveTextContent(
      'three competitors',
    );
    // the proposal waiting for me is decidable right here
    const waiting = screen.getByRole('region', { name: 'Waiting for you' });
    expect(await within(waiting).findByRole('button', { name: 'Apply' })).toBeInTheDocument();
  });

  it('hides step details from someone the run was not for', async () => {
    const run = runFixture({
      detail: 'summary',
      answer: null,
      trace: [
        { at: '2026-09-28T10:00:05Z', kind: 'trigger', summary: 'event trigger', name: null, ok: null },
        { at: '2026-09-28T10:00:09Z', kind: 'tool', summary: '', name: 'search_tasks', ok: true },
      ],
    });
    boot('/agents/runs/run-1', agentHandlers({ run }));
    expect(await screen.findByText(/step details are shown only to admins/)).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: /answered/ })).toBeNull();
    expect(screen.getByText('search_tasks')).toBeInTheDocument();
  });

  it('shows a failed run’s error plainly', async () => {
    const run = runFixture({
      status: 'budget_exceeded',
      error: 'Teammate has used $5.00 of its $5.00 monthly budget.',
      answer: null,
    });
    boot('/agents/runs/run-1', agentHandlers({ run }));
    expect(await screen.findByRole('alert')).toHaveTextContent('monthly budget');
    expect(screen.getByText('Budget used up')).toBeInTheDocument();
  });

  it('lists an agent’s runs with status and trigger filters', async () => {
    const ok = runFixture();
    const failed = runFixture({
      id: 'run-2',
      status: 'failed',
      trigger: 'mentioned',
      error: 'No access',
      task: null,
    });
    const agents = agentHandlers({ agent: agentFixture(), runs: [ok, failed] });
    const user = boot('/agents/agent-1', agents);
    expect(await screen.findByRole('heading', { name: 'Teammate' })).toBeInTheDocument();
    expect(
      screen.getByText(/Asks before changing · budget \$5\.00\/month · works in Website Revamp/),
    ).toBeInTheDocument();
    const list = await screen.findByRole('list', { name: 'Runs' });
    expect(within(list).getAllByRole('link')).toHaveLength(2);
    expect(within(list).getAllByRole('link')[0]).toHaveAttribute('href', '/agents/runs/run-1');

    await user.selectOptions(screen.getByLabelText('Status'), 'failed');
    expect(await screen.findByText(/No access/)).toBeInTheDocument();
    expect(within(screen.getByRole('list', { name: 'Runs' })).getAllByRole('link')).toHaveLength(1);
    expect(agents.queries.at(-1)?.get('status')).toBe('failed');

    await user.selectOptions(screen.getByLabelText('Trigger'), 'schedule');
    expect(await screen.findByText('No runs match these filters.')).toBeInTheDocument();
  });

  it('shows members no settings, and admins the controls with the promotion rule', async () => {
    boot('/agents/agent-1', agentHandlers());
    expect(await screen.findByRole('heading', { name: 'Teammate' })).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Agent settings' })).toBeNull();
  });

  it('lets an admin turn the agent off and set its budget, but not promote it before it has earned it', async () => {
    const agents = agentHandlers();
    const user = boot('/agents/agent-1', agents, [], 'admin');
    const panel = await screen.findByRole('region', { name: 'Agent settings' });
    expect(
      await within(panel).findByText(/Accepted 11 of its last 12 proposals \(92%\)/),
    ).toBeInTheDocument();
    expect(within(panel).getByText(/Needs 30 decided proposals/)).toBeInTheDocument();
    expect(
      within(panel).getByRole('option', { name: /Acts on low-risk changes \(not earned yet\)/ }),
    ).toBeDisabled();
    expect(
      within(panel).getByText(/This month: \$1\.25 · 120,000 tokens\. The dollar budget applies\./),
    ).toBeInTheDocument();

    await user.click(within(panel).getByRole('checkbox', { name: /Teammate is on/ }));
    await user.clear(within(panel).getByLabelText('Monthly budget (USD)'));
    await user.type(within(panel).getByLabelText('Monthly budget (USD)'), '8');
    await user.click(within(panel).getByRole('button', { name: 'Save budget' }));
    await waitFor(() => expect(agents.patches).toHaveLength(2));
    expect(agents.patches[0]).toMatchObject({ enabled: false });
    expect(agents.patches[1]).toMatchObject({ budget_monthly_usd: '8', budget_monthly_tokens: 2000000 });
  });

  it('offers promotion once the stats allow it', async () => {
    const agents = agentHandlers({
      stats: statsFixture({
        decided: 30,
        accepted: 28,
        acceptance_rate: 28 / 30,
        eligible_for_auto: true,
        reasons: [],
      }),
    });
    const user = boot('/agents/agent-1', agents, [], 'admin');
    const panel = await screen.findByRole('region', { name: 'Agent settings' });
    expect(await within(panel).findByText('It can be promoted to act on its own.')).toBeInTheDocument();
    await user.selectOptions(within(panel).getByLabelText('Autonomy'), 'auto');
    await waitFor(() => expect(agents.patches).toEqual([{ autonomy: 'auto', expected_version: 1 }]));
  });
});

describe('Agent gallery and creation (S5.2.3)', () => {
  it('lists agents with what wakes them', async () => {
    boot('/agents', agentHandlers());
    const list = await screen.findByRole('list', { name: 'Agents' });
    expect(within(list).getByRole('link', { name: /Teammate/ })).toHaveAttribute('href', '/agents/agent-1');
    expect(within(list).getByText(/Assigned a task · Asks before changing/)).toBeInTheDocument();
    // members can't create agents
    expect(screen.queryByRole('link', { name: /Create agent/ })).not.toBeInTheDocument();
  });

  it('drafts an agent from a description, marks it as Mo’s, and saves it', async () => {
    const agents = agentHandlers();
    const user = boot('/agents/new', agents, [], 'admin');
    await user.type(await screen.findByLabelText(/Describe what you want/), 'A weekly bug sweeper');
    await user.click(screen.getByRole('button', { name: /Draft it/ }));
    expect(await screen.findByText(/Mo drafted this/)).toBeInTheDocument();
    expect(screen.getByText(/Left out delete_task/)).toBeInTheDocument();
    expect(screen.getByLabelText('Name')).toHaveValue('(mock) Bug Sweeper');
    expect(screen.getByLabelText('Schedule (cron)')).toHaveValue('0 9 * * MON');
    await user.click(screen.getByRole('button', { name: 'Create agent' }));
    await waitFor(() => expect(agents.creates).toHaveLength(1));
    expect(agents.creates[0]).toMatchObject({
      name: '(mock) Bug Sweeper',
      triggers: [{ type: 'mentioned' }, { type: 'schedule', cron: '0 9 * * MON', timezone: 'workspace' }],
      tools: ['search_tasks', 'add_comment'],
      autonomy: 'confirm',
      model_alias: 'fast',
    });
  });

  it('test-runs an agent and says nothing was changed', async () => {
    const agents = agentHandlers();
    const user = boot('/agents/agent-1', agents, [], 'admin');
    await user.type(await screen.findByLabelText('Task key'), 'T-12');
    await user.click(screen.getByRole('button', { name: /Test run/ }));
    expect(await screen.findByText(/nothing was changed/)).toBeInTheDocument();
    expect(screen.getByText('(mock) I would raise the priority.')).toBeInTheDocument();
    expect(screen.getByText('Set priority to high on T-12')).toBeInTheDocument();
    expect(agents.testRuns).toEqual([{ task: 'T-12', text: null }]);
  });
});

describe('Run now (S5.3.5/S5.3.6)', () => {
  it('runs an agent with pasted text on a task and opens the run', async () => {
    const agents = agentHandlers({
      agent: agentFixture({ name: 'Scribe · Meeting Notes', triggers: [{ type: 'manual' }] }),
    });
    const user = boot('/agents/agent-1', agents);
    await user.type(
      await screen.findByLabelText(/Text for Scribe/),
      'Decided: ship Friday. Ana to write notes.',
    );
    await user.type(screen.getByLabelText('On a task (optional)'), 'T-12');
    await user.click(screen.getByRole('button', { name: /Run Scribe/ }));
    await waitFor(() => expect(agents.runsNow).toHaveLength(1));
    expect(agents.runsNow[0]).toEqual({ task: 'T-12', text: 'Decided: ship Friday. Ana to write notes.' });
    expect(await screen.findByRole('heading', { name: /Run ·/ })).toBeInTheDocument();
  });

  it('is not offered for agents without a manual trigger', async () => {
    boot('/agents/agent-1', agentHandlers());
    await screen.findByRole('heading', { name: 'Teammate' });
    expect(screen.queryByRole('region', { name: 'Run now' })).toBeNull();
  });
});

describe('Where an agent works (kickoff Q1)', () => {
  it('lets an admin add the agent to a project they manage', async () => {
    const agents = agentHandlers({ agent: agentFixture({ projects: [] }) });
    const user = boot('/agents/agent-1', agents, [], 'admin', [{ name: 'Website Revamp', my_role: 'admin' }]);
    const section = await screen.findByRole('region', { name: 'Works in' });
    expect(within(section).getByText('No projects yet.')).toBeInTheDocument();
    const select = within(section).getByRole('combobox', { name: 'Add to project' });
    await waitFor(() => expect(within(select).getAllByRole('option').length).toBeGreaterThan(1));
    const option = within(select).getAllByRole('option')[1]!;
    await user.selectOptions(select, option);
    await user.click(within(section).getByRole('button', { name: 'Add' }));
    await waitFor(() => expect(agents.added).toHaveLength(1));
    expect(agents.added[0]).toMatchObject({ role: 'editor' });
  });
});
