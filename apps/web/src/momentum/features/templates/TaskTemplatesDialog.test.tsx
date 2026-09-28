import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { authHandlers } from '@/mocks/handlers';
import { dependencyHandlers } from '@/mocks/dependencies';
import { fieldHandlers } from '@/mocks/fields';
import { multiHomingHandlers } from '@/mocks/multiHoming';
import { notificationHandlers } from '@/mocks/notifications';
import { projectHandlers } from '@/mocks/projects';
import { sectionHandlers } from '@/mocks/sections';
import { tagHandlers } from '@/mocks/tags';
import { taskHandlers } from '@/mocks/tasks';
import { teamHandlers } from '@/mocks/teams';
import { templateHandlers } from '@/mocks/templates';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  server.resetHandlers();
  window.localStorage.clear();
});
afterAll(() => server.close());

async function boot() {
  server.use(
    ...authHandlers({ loggedIn: true }).handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, [{ name: 'Website Revamp', my_role: 'admin' }]),
    ...sectionHandlers('', { 'seed-1': ['Backlog'] }),
    ...taskHandlers(),
    ...fieldHandlers(),
    ...dependencyHandlers('', [{ id: 'task-1', title: 'Ship it', completed_at: null }]),
    ...tagHandlers(),
    ...notificationHandlers(),
    ...multiHomingHandlers(),
    ...templateHandlers(),
  );
  window.history.replaceState(null, '', '/projects/seed-1');
  render(<MomentumApp />);
  const user = userEvent.setup();
  await screen.findByRole('button', { name: 'Fields' });
  return user;
}

describe('Task templates (S4.3.2)', () => {
  it('creates a task template and creates a task from it', async () => {
    const user = await boot();
    await user.click(screen.getByRole('button', { name: 'Project actions' }));
    await user.click(screen.getByRole('menuitem', { name: 'Task templates' }));
    await screen.findByRole('dialog', { name: 'Task templates' });

    await user.click(screen.getByRole('button', { name: 'New task template' }));
    await user.type(screen.getByRole('textbox', { name: 'Template name' }), 'Bug report');
    await user.type(screen.getByRole('textbox', { name: 'Default task title' }), 'Bug: ');
    await user.click(screen.getByRole('button', { name: 'Save template' }));
    await waitFor(() => expect(screen.getByText('Bug report')).toBeInTheDocument());

    await user.click(screen.getByText('Bug report'));
    await user.click(screen.getByRole('button', { name: 'Add task' }));
    await waitFor(() => expect(screen.getByText('Task created')).toBeInTheDocument());
  });
});
