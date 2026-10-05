import { render, screen } from '@testing-library/react';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { authHandlers } from '@/mocks/handlers';
import { notificationHandlers } from '@/mocks/notifications';
import { projectHandlers } from '@/mocks/projects';
import { teamHandlers } from '@/mocks/teams';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  server.resetHandlers();
  window.localStorage.clear();
});
afterAll(() => server.close());

const boot = (role: 'admin' | 'member') => {
  server.use(
    ...authHandlers({ loggedIn: true, me: { role } }).handlers,
    ...teamHandlers(),
    ...projectHandlers(),
    ...notificationHandlers(),
  );
  window.history.replaceState(null, '', '/settings');
  render(<MomentumApp />);
};

describe('Settings: export everything (S7.5.1)', () => {
  it('offers an admin the data-only and with-files downloads', async () => {
    boot('admin');
    const section = await screen.findByRole('region', { name: 'Export everything' });
    expect(section.querySelector('a[href="/api/v1/admin/export"]')).not.toBeNull();
    expect(section.querySelector('a[href="/api/v1/admin/export?files=true"]')).not.toBeNull();
  });

  it("doesn't show it to a member", async () => {
    boot('member');
    await screen.findByRole('heading', { level: 1, name: 'Settings' });
    expect(screen.queryByRole('region', { name: 'Export everything' })).toBeNull();
  });
});
