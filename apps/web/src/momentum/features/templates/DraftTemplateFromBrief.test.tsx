import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { authHandlers } from '@/mocks/handlers';
import { onboardingHandlers } from '@/mocks/onboarding';
import { projectHandlers } from '@/mocks/projects';
import { sectionHandlers } from '@/mocks/sections';
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

describe('Template from description (S4.3.3)', () => {
  it('drafts a template with Mo, saves it, and can pick it right away', async () => {
    server.use(
      ...authHandlers({ loggedIn: true, config: { ai_enabled: true } }).handlers,
      ...teamHandlers(),
      ...projectHandlers('', () => 'Design'),
      ...sectionHandlers('', { 'project-1': ['To do'] }),
      ...taskHandlers(),
      ...onboardingHandlers(),
      ...templateHandlers(),
    );
    window.history.replaceState(null, '', '/');
    render(<MomentumApp />);
    const user = userEvent.setup();
    await screen.findByRole('heading', { name: /Ravi$/ });
    const nav = screen.getByRole('navigation', { name: 'Main' });

    await user.click(within(nav).getByRole('button', { name: 'New team' }));
    await user.type(await screen.findByLabelText('Name'), 'Design');
    await user.click(screen.getByRole('button', { name: 'Create team' }));
    await screen.findByRole('button', { name: /Team name: Design/ });

    await user.click(screen.getByRole('button', { name: /New project/ }));
    await user.click(await screen.findByRole('radio', { name: 'From template' }));

    await user.type(screen.getByRole('textbox', { name: 'Describe the process' }), 'onboard a new hire');
    await user.click(screen.getByRole('button', { name: /Draft it/ }));
    await screen.findByText('Step one');

    await user.click(screen.getByRole('button', { name: 'Save template' }));
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Template' })).toBeInTheDocument());
  });
});
