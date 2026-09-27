import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { authHandlers } from '@/mocks/handlers';
import { dependencyHandlers } from '@/mocks/dependencies';
import { fieldHandlers } from '@/mocks/fields';
import { formHandlers } from '@/mocks/forms';
import { multiHomingHandlers } from '@/mocks/multiHoming';
import { notificationHandlers } from '@/mocks/notifications';
import { projectHandlers } from '@/mocks/projects';
import { sectionHandlers } from '@/mocks/sections';
import { tagHandlers } from '@/mocks/tags';
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
    ...formHandlers(),
    ...tagHandlers(),
    ...notificationHandlers(),
    ...multiHomingHandlers(),
  );
  window.history.replaceState(null, '', '/projects/seed-1');
  render(<MomentumApp />);
  const user = userEvent.setup();
  await screen.findByRole('button', { name: 'Fields' });
  return user;
}

const openDialog = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.click(screen.getByRole('button', { name: 'Project actions' }));
  await user.click(screen.getByRole('menuitem', { name: 'Forms' }));
  return screen.findByRole('dialog', { name: 'Forms' });
};

describe('Form builder (S4.2.1)', () => {
  it('creates a form with the default title question and lists it', async () => {
    const user = await boot();
    await openDialog(user);
    await user.click(screen.getByRole('button', { name: 'New form' }));
    await user.type(screen.getByRole('textbox', { name: 'Form name' }), 'Bug report');
    await user.click(screen.getByRole('button', { name: 'Create form' }));
    await waitFor(() => expect(screen.getByText('Bug report')).toBeInTheDocument());
    expect(screen.getByText('1 questions')).toBeInTheDocument();
  });

  it('marks a form public once the toggle is on, and lets an admin delete it', async () => {
    const user = await boot();
    await openDialog(user);
    await user.click(screen.getByRole('button', { name: 'New form' }));
    await user.type(screen.getByRole('textbox', { name: 'Form name' }), 'Intake');
    await user.click(screen.getByRole('switch', { name: 'Public link' }));
    await user.click(screen.getByRole('button', { name: 'Create form' }));
    await waitFor(() => expect(screen.getByText('Public')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: 'Intake actions' }));
    await user.click(screen.getByRole('menuitem', { name: 'Delete form' }));
    await waitFor(() => expect(screen.queryByText('Intake')).not.toBeInTheDocument());
  });

  it('marks a form conversational once the toggle is on (S4.2.2)', async () => {
    const user = await boot();
    await openDialog(user);
    await user.click(screen.getByRole('button', { name: 'New form' }));
    await user.type(screen.getByRole('textbox', { name: 'Form name' }), 'Chat intake');
    await user.click(screen.getByRole('switch', { name: 'Conversational' }));
    await user.click(screen.getByRole('button', { name: 'Create form' }));
    await waitFor(() => expect(screen.getByText('Conversational')).toBeInTheDocument());
  });

  it('an editor has no access to project settings, so no Forms entry either', async () => {
    await boot({ my_role: 'editor' });
    expect(screen.queryByRole('button', { name: 'Project actions' })).not.toBeInTheDocument();
  });
});
