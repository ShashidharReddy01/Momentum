import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { authHandlers } from '@/mocks/handlers';
import { projectHandlers } from '@/mocks/projects';
import { sectionHandlers } from '@/mocks/sections';
import { teamHandlers } from '@/mocks/teams';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  server.resetHandlers();
  window.localStorage.clear();
});
afterAll(() => server.close());

function boot(role = 'admin') {
  server.use(
    ...authHandlers({ loggedIn: true }).handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, [{ name: 'Website Revamp', my_role: role }]),
    ...sectionHandlers('', { 'seed-1': ['Backlog', 'In progress', 'Done'] }),
  );
  window.history.replaceState(null, '', '/projects/seed-1');
  render(<MomentumApp />);
  return userEvent.setup();
}

const order = () =>
  screen.getAllByRole('region', { name: /^Section / }).map((r) => r.getAttribute('aria-label'));

describe('Sections', () => {
  it('renames, adds, reorders (menu), collapses and deletes sections', async () => {
    const user = boot();
    await screen.findByRole('region', { name: 'Section Backlog' });
    expect(order()).toEqual(['Section Backlog', 'Section In progress', 'Section Done']);

    // rename inline
    await user.click(screen.getByRole('button', { name: /Section name: Backlog/ }));
    const input = screen.getByRole('textbox', { name: 'Section name' });
    await user.clear(input);
    await user.type(input, 'Ideas{Enter}');
    expect(await screen.findByRole('region', { name: 'Section Ideas' })).toBeInTheDocument();

    // add at the end
    await user.click(screen.getByRole('button', { name: 'Add section' }));
    await user.type(screen.getByRole('textbox', { name: 'New section name' }), 'Archive{Enter}');
    expect(await screen.findByRole('region', { name: 'Section Archive' })).toBeInTheDocument();

    // move Done up via the keyboard-accessible menu
    await user.click(screen.getByRole('button', { name: 'Actions for section Done' }));
    await user.click(await screen.findByRole('menuitem', { name: /Move up/ }));
    await screen.findByText('Section moved');
    expect(order()).toEqual(['Section Ideas', 'Section Done', 'Section In progress', 'Section Archive']);

    // collapse hides the body
    const done = screen.getByRole('region', { name: 'Section Done' });
    expect(within(done).getByText('No tasks yet')).toBeInTheDocument();
    await user.click(within(done).getByRole('button', { name: 'Collapse Done' }));
    expect(within(done).queryByText('No tasks yet')).not.toBeInTheDocument();

    // delete
    await user.click(screen.getByRole('button', { name: 'Actions for section Archive' }));
    await user.click(await screen.findByRole('menuitem', { name: /Delete section/ }));
    expect(await screen.findByText('Section deleted')).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Section Archive' })).not.toBeInTheDocument();
  });

  it('viewers cannot edit sections', async () => {
    boot('viewer');
    await screen.findByRole('region', { name: 'Section Backlog' });
    expect(screen.queryByRole('button', { name: /Section name:/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Add section' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Reorder section/ })).not.toBeInTheDocument();
  });
});
