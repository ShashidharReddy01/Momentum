import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { authHandlers } from '@/mocks/handlers';
import { dependencyHandlers } from '@/mocks/dependencies';
import { fieldHandlers } from '@/mocks/fields';
import { projectHandlers } from '@/mocks/projects';
import { ruleHandlers } from '@/mocks/rules';
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

async function boot(seed: Record<string, unknown> = { my_role: 'admin' }, sections = ['Backlog'], ai = true) {
  server.use(
    ...authHandlers({ loggedIn: true, config: { ai_enabled: ai } }).handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, [{ name: 'Website Revamp', ...seed }]),
    ...sectionHandlers('', { 'seed-1': sections }),
    ...taskHandlers(),
    ...fieldHandlers(),
    ...dependencyHandlers('', [{ id: 'task-1', title: 'Ship it', completed_at: null }]),
    ...ruleHandlers(),
  );
  window.history.replaceState(null, '', '/projects/seed-1');
  render(<MomentumApp />);
  const user = userEvent.setup();
  await screen.findByRole('button', { name: 'Fields' });
  return user;
}

const openDialog = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.click(screen.getByRole('button', { name: 'Project actions' }));
  await user.click(screen.getByRole('menuitem', { name: 'Rules' }));
  return screen.findByRole('dialog', { name: 'Rules' });
};

const newRule = async (user: ReturnType<typeof userEvent.setup>, name: string) => {
  await user.click(screen.getByRole('button', { name: 'New rule' }));
  await user.type(screen.getByRole('textbox', { name: 'Rule name' }), name);
  await user.click(screen.getByRole('button', { name: 'Create rule' }));
  await waitFor(() => screen.getByText(name));
};

describe('Rule builder and run history (S4.1.3)', () => {
  it('creates a rule and shows its readable sentence', async () => {
    const user = await boot();
    await openDialog(user);
    await user.click(screen.getByRole('button', { name: 'New rule' }));
    await user.type(screen.getByRole('textbox', { name: 'Rule name' }), 'Assign new work');
    await user.selectOptions(screen.getByRole('combobox', { name: 'Action' }), 'Assign to');
    await user.selectOptions(screen.getByRole('combobox', { name: 'Person' }), 'Ravi Kumar');
    await user.click(screen.getByRole('button', { name: 'Create rule' }));
    await waitFor(() => expect(screen.getByText('Assign new work')).toBeInTheDocument());
    expect(screen.getByText(/assign to Ravi Kumar/)).toBeInTheDocument();
  });

  it('toggles a rule on and off', async () => {
    const user = await boot();
    await openDialog(user);
    await newRule(user, 'R');
    const off = await screen.findByRole('switch', { name: 'Turn off R' });
    await user.click(off);
    await waitFor(() => expect(screen.getByRole('switch', { name: 'Turn on R' })).toBeInTheDocument());
  });

  it('edits and deletes a rule', async () => {
    const user = await boot();
    await openDialog(user);
    await newRule(user, 'Old name');

    await user.click(screen.getByRole('button', { name: 'Edit' }));
    const nameBox = screen.getByRole('textbox', { name: 'Rule name' });
    await user.clear(nameBox);
    await user.type(nameBox, 'New name');
    await user.click(screen.getByRole('button', { name: 'Save rule' }));
    await waitFor(() => expect(screen.getByText('New name')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: 'New name actions' }));
    await user.click(screen.getByRole('menuitem', { name: 'Delete rule' }));
    await waitFor(() => expect(screen.queryByText('New name')).toBeNull());
  });

  it('test-runs a rule against a chosen task without persisting anything', async () => {
    const user = await boot();
    await openDialog(user);
    await newRule(user, 'Ping on complete');

    await user.click(screen.getByRole('button', { name: "Ping on complete's history" }));
    await user.click(screen.getByRole('button', { name: 'Test on a task…' }));
    await user.type(screen.getByPlaceholderText('Search tasks to test on…'), 'Ship');
    await user.click(await screen.findByText('Ship it'));
    await waitFor(() =>
      expect(within(screen.getByRole('dialog')).getByText('mark_complete')).toBeInTheDocument(),
    );
  });

  it('drafts a rule from a sentence and saves it with the prompt that made it (S4.1.4)', async () => {
    const user = await boot({ my_role: 'admin' }, ['Review']);
    let posted: Record<string, unknown> | null = null;
    server.use(
      http.post('*/api/v1/rules', async ({ request }) => {
        posted = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(
          { data: { ...posted, id: 'rule-9', version: 1 }, meta: { version: 1 } },
          { status: 201 },
        );
      }),
    );
    await openDialog(user);

    const sentence = 'when a task moves to Review assign it to Ravi';
    await user.type(screen.getByRole('textbox', { name: 'Describe a rule' }), sentence);
    await user.click(screen.getByRole('button', { name: 'Draft it' }));

    // the draft opens in the ordinary builder, prefilled and marked as Mo's
    await waitFor(() =>
      expect(screen.getByRole('textbox', { name: 'Rule name' })).toHaveValue('Review goes to Ravi'),
    );
    expect(screen.getByText(/Mo drafted this/)).toBeInTheDocument();
    expect(screen.getByText(/moves to Review, then assign to Ravi Kumar/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Create rule' }));
    await waitFor(() => expect(posted).not.toBeNull());
    expect(posted).toMatchObject({ name: 'Review goes to Ravi', created_from_prompt: sentence });
    await waitFor(() => expect(screen.getByRole('button', { name: 'New rule' })).toBeInTheDocument());
  });

  it('asks a question instead of guessing, and drafts nothing (S4.1.4)', async () => {
    const user = await boot();
    await openDialog(user);
    await user.type(screen.getByRole('textbox', { name: 'Describe a rule' }), 'post it to Slack');
    await user.click(screen.getByRole('button', { name: 'Draft it' }));
    await waitFor(() =>
      expect(screen.getByText(/Which section should the task move into/)).toBeInTheDocument(),
    );
    expect(screen.queryByRole('textbox', { name: 'Rule name' })).toBeNull();
  });

  it('builds an AI step and shows its own status in the run history (S4.1.5)', async () => {
    const user = await boot();
    server.use(
      http.get('*/api/v1/rules/rule-1/runs', () =>
        HttpResponse.json({
          data: [
            {
              id: 'run-1',
              rule_id: 'rule-1',
              outbox_event_id: 1,
              status: 'success',
              depth: 0,
              actions_run: 1,
              error: null,
              started_at: '2026-09-27T00:00:00Z',
              finished_at: '2026-09-27T00:00:01Z',
              activity_batch_id: null,
              ai_steps: [
                {
                  id: 'step-1',
                  task_id: 'task-1',
                  kind: 'classify_field',
                  field_id: 'priority',
                  status: 'done',
                  result: 'Set priority to high',
                  error: null,
                  created_at: '2026-09-27T00:00:01Z',
                  finished_at: '2026-09-27T00:00:20Z',
                },
              ],
            },
          ],
          meta: { next_cursor: null },
        }),
      ),
    );
    await openDialog(user);
    await user.click(screen.getByRole('button', { name: 'New rule' }));
    await user.type(screen.getByRole('textbox', { name: 'Rule name' }), 'Mo triages');
    await user.selectOptions(screen.getByRole('combobox', { name: 'Action' }), 'Let Mo do a step (AI)');
    await user.selectOptions(
      screen.getByRole('combobox', { name: 'AI step' }),
      'Set a field from what the task says',
    );
    await user.selectOptions(screen.getByRole('combobox', { name: 'Field' }), 'Priority');
    expect(screen.getByText(/let Mo set priority from what the task says/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Create rule' }));

    // the saved rule reads back as an AI step (so kind and field made it through the API)
    await waitFor(() => expect(screen.getByText('Mo triages')).toBeInTheDocument());
    expect(screen.getByText(/let Mo set priority from what the task says/)).toBeInTheDocument();

    await user.click(await screen.findByRole('button', { name: "Mo triages's history" }));
    const steps = await screen.findByRole('list', { name: 'AI steps' });
    expect(within(steps).getByText(/Set a field from what the task says/)).toBeInTheDocument();
    expect(within(steps).getByText(/done/)).toBeInTheDocument();
    expect(within(steps).getByText(/Set priority to high/)).toBeInTheDocument();
  });

  it('hides "describe a rule" while AI is off', async () => {
    const user = await boot({ my_role: 'admin' }, ['Backlog'], false);
    await openDialog(user);
    expect(screen.queryByRole('textbox', { name: 'Describe a rule' })).toBeNull();
    expect(screen.getByRole('button', { name: 'New rule' })).toBeInTheDocument();
  });

  it('a non-admin editor sees no project-actions menu (Rules is admin-only)', async () => {
    await boot({ my_role: 'editor' });
    expect(screen.queryByRole('button', { name: 'Project actions' })).toBeNull();
  });
});
