import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { authHandlers } from '@/mocks/handlers';
import { homeHandlers } from '@/mocks/home';
import { notificationHandlers } from '@/mocks/notifications';
import { projectHandlers } from '@/mocks/projects';
import { searchHandlers } from '@/mocks/search';
import { teamHandlers } from '@/mocks/teams';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  server.resetHandlers();
  window.localStorage.clear();
});
afterAll(() => server.close());

describe('Coming from Asana (S7.4.4)', () => {
  it('is one click from Home and explains the words, the keys and the import', async () => {
    server.use(
      ...authHandlers({ loggedIn: true }).handlers,
      ...teamHandlers(),
      ...projectHandlers(),
      ...notificationHandlers(),
      ...searchHandlers(),
      ...homeHandlers().handlers,
    );
    window.history.replaceState(null, '', '/');
    render(<MomentumApp />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole('link', { name: 'Coming from Asana?' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Coming from Asana?' })).toBeInTheDocument();
    const words = screen.getByRole('region', { name: 'Words that differ' });
    expect(within(words).getByRole('cell', { name: 'Reporting' })).toBeInTheDocument();
    expect(within(words).getByRole('cell', { name: 'Dashboards' })).toBeInTheDocument();
    const keys = screen.getByRole('region', { name: 'Your shortcuts' });
    expect(within(keys).getByRole('cell', { name: 'Tab + C' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Import from Asana/ })).toHaveAttribute(
      'href',
      '/settings/import/asana',
    );

    // Asana's ⌘/ opens the shortcut sheet, which lists the new keys
    await user.keyboard('{Control>}/{/Control}');
    const sheet = await screen.findByRole('dialog', { name: 'Keyboard shortcuts' });
    expect(within(sheet).getByText('Comment on the open task')).toBeInTheDocument();
    expect(within(sheet).getByText('Search')).toBeInTheDocument();
  });
});
