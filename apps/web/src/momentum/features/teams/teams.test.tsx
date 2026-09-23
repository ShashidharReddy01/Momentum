import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { authHandlers } from '@/mocks/handlers';
import { projectHandlers } from '@/mocks/projects';
import { teamHandlers } from '@/mocks/teams';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  server.resetHandlers();
  window.localStorage.clear();
});
afterAll(() => server.close());

describe('Teams', () => {
  it('creates a team from the sidebar, opens its page, renames it and adds a member', async () => {
    server.use(...authHandlers({ loggedIn: true }).handlers, ...teamHandlers(), ...projectHandlers());
    window.history.replaceState(null, '', '/');
    render(<MomentumApp />);
    const user = userEvent.setup();
    await screen.findByRole('heading', { name: /Ravi$/ });

    const nav = screen.getByRole('navigation', { name: 'Main' });
    expect(await within(nav).findByText('No teams yet.')).toBeInTheDocument();
    await user.click(within(nav).getByRole('button', { name: 'New team' }));
    await user.type(await screen.findByLabelText('Name'), 'Design');
    await user.click(screen.getByRole('button', { name: 'Create team' }));

    // Lands on the team page; sidebar lists the team
    expect(await screen.findByRole('button', { name: /Team name: Design/ })).toBeInTheDocument();
    expect(window.location.pathname).toBe('/teams/team-1');
    expect(await within(nav).findByRole('link', { name: 'Design' })).toHaveAttribute('href', '/teams/team-1');

    // Rename inline
    await user.click(screen.getByRole('button', { name: /Team name: Design/ }));
    const input = screen.getByRole('textbox', { name: 'Team name' });
    await user.clear(input);
    await user.type(input, 'Design Systems{Enter}');
    expect(await screen.findByRole('button', { name: /Team name: Design Systems/ })).toBeInTheDocument();

    // Add a member through the people picker
    await user.click(screen.getByRole('button', { name: /Add member/ }));
    await user.click(await screen.findByRole('option', { name: /Ana Souza/ }));
    expect(await screen.findByText('ana@acme-demo.test')).toBeInTheDocument();
  });
});
