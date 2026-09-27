import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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

async function boot(seed: Record<string, unknown> = { my_role: 'admin' }) {
  server.use(
    ...authHandlers({ loggedIn: true }).handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, [{ name: 'Website Revamp', ...seed }]),
    ...sectionHandlers('', { 'seed-1': ['Backlog'] }),
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

  it('a non-admin editor sees no project-actions menu (Rules is admin-only)', async () => {
    await boot({ my_role: 'editor' });
    expect(screen.queryByRole('button', { name: 'Project actions' })).toBeNull();
  });
});
