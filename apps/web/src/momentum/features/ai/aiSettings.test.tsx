import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { aiMemoryHandlers } from '@/mocks/ai';
import { authHandlers } from '@/mocks/handlers';
import { projectHandlers } from '@/mocks/projects';
import { teamHandlers } from '@/mocks/teams';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

async function boot(role: 'admin' | 'member', bullets: string[]) {
  const mem = aiMemoryHandlers(bullets, { canEdit: role === 'admin' });
  server.use(
    ...authHandlers({ loggedIn: true, me: { role } }).handlers,
    ...teamHandlers(),
    ...projectHandlers(),
    ...mem.handlers,
  );
  window.history.replaceState(null, '', '/settings/ai');
  render(<MomentumApp />);
  await screen.findByRole('heading', { name: 'AI settings' });
  return { user: userEvent.setup(), mem };
}

describe('AI settings: workspace memory (S3.1.5)', () => {
  it('an admin adds, edits and removes memory bullets', async () => {
    const { user, mem } = await boot('admin', ['Sprints start on Mondays']);
    const list = await screen.findByRole('list', { name: 'Memory' });
    expect(within(list).getByText('Sprints start on Mondays')).toBeInTheDocument();

    await user.type(screen.getByRole('textbox', { name: 'New memory bullet' }), 'Legal reviews pricing copy');
    await user.click(screen.getByRole('button', { name: 'Add' }));
    expect(await within(list).findByText('Legal reviews pricing copy')).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'New memory bullet' })).toHaveValue('');

    await user.click(within(list).getByText('Sprints start on Mondays'));
    const edit = within(list).getByRole('textbox', { name: 'Memory bullet' });
    await user.clear(edit);
    await user.type(edit, 'Sprints start on Tuesdays{Enter}');
    await waitFor(() => expect(mem.bullets[0]!.text).toBe('Sprints start on Tuesdays'));

    await user.click(within(list).getByRole('button', { name: 'Remove "Legal reviews pricing copy"' }));
    await waitFor(() => expect(within(list).queryByText('Legal reviews pricing copy')).toBeNull());
    expect(await screen.findByText('Memory removed')).toBeInTheDocument(); // with Undo
  });

  it('a member reads memory but gets no editing controls', async () => {
    await boot('member', ['Sprints start on Mondays']);
    const list = await screen.findByRole('list', { name: 'Memory' });
    expect(within(list).getByText('Sprints start on Mondays')).toBeInTheDocument();
    expect(screen.getByText(/Only workspace admins can change them/)).toBeInTheDocument();
    expect(screen.queryByRole('textbox', { name: 'New memory bullet' })).toBeNull();
    expect(within(list).queryByRole('button')).toBeNull();
  });

  it('shows an empty state', async () => {
    await boot('admin', []);
    expect(await screen.findByText('No workspace memory yet')).toBeInTheDocument();
  });
});
