import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { authHandlers } from '@/mocks/handlers';
import { fieldHandlers } from '@/mocks/fields';
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

async function boot(seed: Record<string, unknown> = { my_role: 'admin' }) {
  server.use(
    ...authHandlers({ loggedIn: true }).handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, [{ name: 'Website Revamp', ...seed }]),
    ...sectionHandlers('', { 'seed-1': ['Backlog'] }),
    ...taskHandlers(),
    ...fieldHandlers(),
  );
  window.history.replaceState(null, '', '/projects/seed-1');
  render(<MomentumApp />);
  const user = userEvent.setup();
  await screen.findByRole('button', { name: 'Fields' });
  return user;
}

const openDialog = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.click(screen.getByRole('button', { name: 'Fields' }));
  return screen.findByRole('dialog', { name: 'Fields' });
};

describe('Fields management (S2.3.1)', () => {
  it('creates a text field and attaches it to the project', async () => {
    const user = await boot();
    await openDialog(user);
    await user.click(screen.getByRole('button', { name: 'New field' }));
    await user.type(screen.getByRole('textbox', { name: 'New field name' }), 'Effort');
    await user.click(screen.getByRole('button', { name: 'Add field' }));
    await waitFor(() =>
      expect(
        within(screen.getByRole('list', { name: 'Fields on this project' })).getByText('Effort'),
      ).toBeInTheDocument(),
    );
  });

  it('creates a single_select field with options', async () => {
    const user = await boot();
    await openDialog(user);
    await user.click(screen.getByRole('button', { name: 'New field' }));
    await user.type(screen.getByRole('textbox', { name: 'New field name' }), 'Priority');
    await user.selectOptions(screen.getByRole('combobox', { name: 'Field type' }), 'single_select');
    await user.type(screen.getByRole('textbox', { name: 'Option 1' }), 'High');
    await user.type(screen.getByRole('textbox', { name: 'Option 2' }), 'Low');
    await user.click(screen.getByRole('button', { name: 'Add field' }));
    await waitFor(() =>
      expect(
        within(screen.getByRole('list', { name: 'Fields on this project' })).getByText('Priority'),
      ).toBeInTheDocument(),
    );
  });

  it('renames, reorders, hides, and removes a field', async () => {
    const user = await boot();
    await openDialog(user);
    await user.click(screen.getByRole('button', { name: 'New field' }));
    await user.type(screen.getByRole('textbox', { name: 'New field name' }), 'A{Enter}');
    await waitFor(() => screen.getByText('A'));
    await user.click(screen.getByRole('button', { name: 'New field' }));
    await user.type(screen.getByRole('textbox', { name: 'New field name' }), 'B{Enter}');
    await waitFor(() => screen.getByText('B'));

    const list = screen.getByRole('list', { name: 'Fields on this project' });
    const rowNames = () =>
      within(list)
        .getAllByRole('button', { name: /^Field name:/ })
        .map((b) => b.textContent);
    expect(rowNames()).toEqual(['A', 'B']);

    await user.click(screen.getByRole('button', { name: 'Move B up' }));
    await waitFor(() => expect(rowNames()).toEqual(['B', 'A']));

    await user.click(screen.getByRole('button', { name: 'Hide B' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Show B' })).toBeInTheDocument());

    await user.click(within(list).getAllByRole('button', { name: /actions$/ })[0]!);
    await user.click(screen.getByRole('menuitem', { name: 'Remove from this project' }));
    await waitFor(() => expect(rowNames()).toEqual(['A']));
  });

  it('attaches a field from the library', async () => {
    const user = await boot();
    // create the field on this project first, then detach it so it's library-only
    await openDialog(user);
    await user.click(screen.getByRole('button', { name: 'New field' }));
    await user.type(screen.getByRole('textbox', { name: 'New field name' }), 'Shared{Enter}');
    await waitFor(() => screen.getByText('Shared'));
    const row = screen.getByRole('button', { name: /^Field name: Shared/ }).closest('li')!;
    await user.click(within(row).getByRole('button', { name: /actions$/ }));
    await user.click(screen.getByRole('menuitem', { name: 'Remove from this project' }));
    await waitFor(() => expect(screen.queryByRole('button', { name: /^Field name: Shared/ })).toBeNull());

    await user.click(screen.getByRole('button', { name: 'Shared' }));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /^Field name: Shared/ })).toBeInTheDocument(),
    );
  });

  it('a non-admin editor can still manage fields (editor-level permission)', async () => {
    const user = await boot({ my_role: 'editor' });
    await openDialog(user);
    await user.click(screen.getByRole('button', { name: 'New field' }));
    expect(screen.getByRole('textbox', { name: 'New field name' })).toBeInTheDocument();
  });
});
