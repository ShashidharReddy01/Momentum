import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { authHandlers } from '@/mocks/handlers';
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

describe('Projects', () => {
  it('creates a project in a team, stars it, and archives it', async () => {
    server.use(
      ...authHandlers({ loggedIn: true }).handlers,
      ...teamHandlers(),
      ...projectHandlers('', () => 'Design'),
      ...sectionHandlers('', { 'project-1': ['To do'] }),
      ...taskHandlers(),
    );
    window.history.replaceState(null, '', '/');
    render(<MomentumApp />);
    const user = userEvent.setup();
    await screen.findByRole('heading', { name: /Ravi$/ });
    const nav = screen.getByRole('navigation', { name: 'Main' });

    // a team first
    await user.click(within(nav).getByRole('button', { name: 'New team' }));
    await user.type(await screen.findByLabelText('Name'), 'Design');
    await user.click(screen.getByRole('button', { name: 'Create team' }));
    await screen.findByRole('button', { name: /Team name: Design/ });

    // new project from the team page
    await user.click(screen.getByRole('button', { name: /New project/ }));
    await user.type(await screen.findByLabelText('Name'), 'Pricing Page');
    await user.click(screen.getByRole('radio', { name: 'Only invited members' }));
    await user.click(screen.getByRole('button', { name: 'Create project' }));

    expect(await screen.findByRole('button', { name: /Project name: Pricing Page/ })).toBeInTheDocument();
    expect(window.location.pathname).toBe('/projects/project-1');
    expect(await screen.findByRole('region', { name: 'Section To do' })).toBeInTheDocument();
    expect(screen.getByLabelText('Private project')).toBeInTheDocument();
    // breadcrumb shows team › project
    const crumbs = screen.getByRole('navigation', { name: 'Breadcrumb' });
    expect(within(crumbs).getByText('Pricing Page')).toBeInTheDocument();

    // star → appears in Favorites
    await user.click(screen.getByRole('button', { name: 'Add to favorites' }));
    expect(await within(nav).findAllByRole('link', { name: /Pricing Page/ })).toHaveLength(2);

    // archive → banner
    await user.click(screen.getByRole('button', { name: 'Project actions' }));
    await user.click(await screen.findByRole('menuitem', { name: /Archive project/ }));
    expect(await screen.findByText(/This project is archived/)).toBeInTheDocument();
  });
});
