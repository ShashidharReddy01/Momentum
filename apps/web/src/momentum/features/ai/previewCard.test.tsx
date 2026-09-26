import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { aiActionFixture, aiHandlers } from '@/mocks/ai';
import { authHandlers } from '@/mocks/handlers';
import { teamHandlers } from '@/mocks/teams';
import { projectHandlers } from '@/mocks/projects';
import type { AiAction } from './queries';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

async function boot(action: AiAction, opts: { staleOnce?: boolean } = {}) {
  const ai = aiHandlers([action], opts);
  server.use(
    ...authHandlers({ loggedIn: true }).handlers,
    ...teamHandlers(),
    ...projectHandlers(),
    ...ai.handlers,
  );
  window.history.replaceState(null, '', `/ai/actions/${action.id}`);
  render(<MomentumApp />);
  const card = await screen.findByRole('region', { name: 'Mo suggests (AI)' });
  return { user: userEvent.setup(), card, calls: ai.calls };
}

describe('PreviewCard (S3.1.3)', () => {
  it('shows the changes grouped by task with the risk, applies, and offers undo', async () => {
    const { user, card, calls } = await boot(aiActionFixture());
    expect(within(card).getByText('Low risk')).toBeInTheDocument();
    const changes = within(card).getByRole('list', { name: 'Proposed changes' });
    expect(within(changes).getByText('T-12 Draft pricing copy')).toBeInTheDocument();
    expect(within(changes).getByText('Assignee: — → Ana Souza')).toBeInTheDocument();
    expect(within(changes).getByText('Due: — → 2026-10-09')).toBeInTheDocument();

    await user.click(within(card).getByRole('button', { name: 'Apply' }));
    expect(await within(card).findByText('Applied')).toBeInTheDocument();
    expect(calls).toEqual([{ path: 'apply', body: { confirm_high_risk: false } }]);
    expect(within(card).queryByRole('button', { name: 'Apply' })).toBeNull();

    await user.click(await screen.findByRole('button', { name: 'Undo' }));
    expect(await within(card).findByText('Undone')).toBeInTheDocument();
    expect(calls.map((c) => c.path)).toEqual(['apply', 'undo']);
  });

  it('asks for explicit confirmation before applying a high-risk change', async () => {
    const { user, card, calls } = await boot(
      aiActionFixture({ risk: 'high', summary: 'Would update 30 task(s)' }),
    );
    expect(within(card).getByText('High risk')).toBeInTheDocument();
    await user.click(within(card).getByRole('button', { name: 'Apply' }));
    const dialog = await screen.findByRole('dialog', { name: 'Apply 1 change?' });
    expect(calls).toEqual([]); // nothing sent before confirming
    await user.click(within(dialog).getByRole('button', { name: 'Go back' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());

    await user.click(within(card).getByRole('button', { name: 'Apply' }));
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Yes, apply' }));
    expect(await within(card).findByText('Applied')).toBeInTheDocument();
    expect(calls).toEqual([{ path: 'apply', body: { confirm_high_risk: true } }]);
  });

  it('shows the updated preview instead of applying when something changed', async () => {
    const { user, card, calls } = await boot(aiActionFixture(), { staleOnce: true });
    await user.click(within(card).getByRole('button', { name: 'Apply' }));
    expect(await within(card).findByText(/Something changed since this preview/)).toBeInTheDocument();
    expect(within(card).getByText('T-12 Pricing copy (final)')).toBeInTheDocument();
    expect(within(card).getByRole('button', { name: 'Apply' })).toBeInTheDocument(); // still pending
    await user.click(within(card).getByRole('button', { name: 'Apply' }));
    expect(await within(card).findByText('Applied')).toBeInTheDocument();
    expect(calls.map((c) => c.path)).toEqual(['apply', 'apply']);
  });

  it('cancel dismisses; finished suggestions show their state without buttons', async () => {
    const { user, card, calls } = await boot(aiActionFixture());
    await user.click(within(card).getByRole('button', { name: 'Cancel' }));
    expect(await within(card).findByText('Dismissed')).toBeInTheDocument();
    expect(calls.map((c) => c.path)).toEqual(['reject']);
    expect(within(card).queryByRole('button')).toBeNull();
  });

  it('an expired suggestion says so', async () => {
    const { card } = await boot(aiActionFixture({ state: 'expired' }));
    expect(within(card).getByText(/expired/)).toBeInTheDocument();
    expect(within(card).queryByRole('button', { name: 'Apply' })).toBeNull();
  });
});
