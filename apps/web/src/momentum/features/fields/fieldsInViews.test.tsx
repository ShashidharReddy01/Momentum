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

async function boot() {
  server.use(
    ...authHandlers({ loggedIn: true }).handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, [{ name: 'Website Revamp', my_role: 'admin' }]),
    ...sectionHandlers('', { 'seed-1': ['Backlog'] }),
    ...taskHandlers('', { 'seed-1': { 'sec-1': ['First'] } }),
    ...fieldHandlers(),
  );
  window.history.replaceState(null, '', '/projects/seed-1');
  render(<MomentumApp />);
  const user = userEvent.setup();
  await screen.findByRole('button', { name: 'Fields' });
  return user;
}

/** Create a field of the given type via the Fields dialog, then close it. */
async function addField(
  user: ReturnType<typeof userEvent.setup>,
  name: string,
  type: string,
  options?: string[],
) {
  await user.click(screen.getByRole('button', { name: 'Fields' }));
  await user.click(await screen.findByRole('button', { name: 'New field' }));
  await user.type(screen.getByRole('textbox', { name: 'New field name' }), name);
  if (type !== 'text') await user.selectOptions(screen.getByRole('combobox', { name: 'Field type' }), type);
  for (const [i, label] of (options ?? []).entries()) {
    const input = screen.queryByRole('textbox', { name: `Option ${i + 1}` });
    if (input) await user.type(input, label);
    else {
      await user.click(screen.getByRole('button', { name: 'Add option' }));
      await user.type(screen.getByRole('textbox', { name: `Option ${i + 1}` }), label);
    }
  }
  await user.click(screen.getByRole('button', { name: 'Add field' }));
  await waitFor(() =>
    expect(
      within(screen.getByRole('list', { name: 'Fields on this project' })).getByText(name),
    ).toBeInTheDocument(),
  );
  await user.keyboard('{Escape}');
}

describe('Fields in views (S2.3.2)', () => {
  it('the pane lets you set a text field and a checkbox field', async () => {
    const user = await boot();
    await addField(user, 'Notes', 'text');
    await addField(user, 'Done externally', 'checkbox');

    await user.click(screen.getByRole('button', { name: 'Open details for First' }));
    const pane = await screen.findByRole('complementary', { name: 'Task details' });

    const notes = within(pane).getByRole('textbox', { name: 'Notes' });
    await user.type(notes, 'Ship it');
    await user.tab();
    await waitFor(() => expect(within(pane).getByRole('textbox', { name: 'Notes' })).toHaveValue('Ship it'));

    const check = within(pane).getByRole('checkbox', { name: 'Done externally' });
    expect(check).toHaveAttribute('aria-checked', 'false');
    await user.click(check);
    await waitFor(() =>
      expect(within(pane).getByRole('checkbox', { name: 'Done externally' })).toHaveAttribute(
        'aria-checked',
        'true',
      ),
    );
  });

  it('the pane lets you pick a single_select option', async () => {
    const user = await boot();
    await addField(user, 'Priority', 'single_select', ['High', 'Low']);

    await user.click(screen.getByRole('button', { name: 'Open details for First' }));
    const pane = await screen.findByRole('complementary', { name: 'Task details' });

    await user.click(within(pane).getByRole('button', { name: 'Priority' }));
    await user.click(await screen.findByRole('option', { name: 'High' }));
    await waitFor(() =>
      expect(within(pane).getByRole('button', { name: 'Priority' })).toHaveTextContent('High'),
    );
  });

  it("a set field value shows as a chip on the task's list row", async () => {
    const user = await boot();
    await addField(user, 'Priority', 'single_select', ['High', 'Low']);

    await user.click(screen.getByRole('button', { name: 'Open details for First' }));
    const pane = await screen.findByRole('complementary', { name: 'Task details' });
    await user.click(within(pane).getByRole('button', { name: 'Priority' }));
    await user.click(await screen.findByRole('option', { name: 'High' }));
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('complementary', { name: 'Task details' })).toBeNull());

    const row = screen.getByRole('listitem', { name: 'First' });
    await waitFor(() => expect(within(row).getByText('High')).toBeInTheDocument());
  });
});
