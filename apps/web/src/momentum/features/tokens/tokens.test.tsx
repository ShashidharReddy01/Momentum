import { http, HttpResponse } from 'msw';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { authHandlers } from '@/mocks/handlers';
import { projectHandlers } from '@/mocks/projects';
import { teamHandlers } from '@/mocks/teams';
import type { ApiToken } from './queries';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function tokenHandlers() {
  const rows: ApiToken[] = [];
  const created: unknown[] = [];
  return {
    created,
    handlers: [
      http.get('*/api/v1/me/tokens', () => HttpResponse.json({ data: rows, meta: { next_cursor: null } })),
      http.post('*/api/v1/me/tokens', async ({ request }) => {
        const body = (await request.json()) as { name: string; scopes: string[] };
        created.push(body);
        const row: ApiToken = {
          id: `tok-${rows.length + 1}`,
          name: body.name,
          prefix: 'mtm_AbCdEf',
          scopes: body.scopes,
          created_at: '2026-09-29T10:00:00Z',
          last_used_at: null,
          expires_at: '2026-12-28T10:00:00Z',
          revoked_at: null,
        };
        rows.unshift(row);
        return HttpResponse.json({ data: row, secret: 'mtm_AbCdEfSECRETvalue123' }, { status: 201 });
      }),
      http.delete('*/api/v1/me/tokens/:id', ({ params }) => {
        const row = rows.find((r) => r.id === params.id)!;
        row.revoked_at = '2026-09-29T11:00:00Z';
        return HttpResponse.json({ data: { ok: true }, meta: { activity_id: 'a-1' } });
      }),
    ],
  };
}

describe('API tokens (S5.1.6)', () => {
  it('creates a scoped token, shows its secret once, and revokes it', async () => {
    const tokens = tokenHandlers();
    server.use(
      ...authHandlers({ loggedIn: true }).handlers,
      ...teamHandlers(),
      ...projectHandlers(),
      ...tokens.handlers,
    );
    window.history.replaceState(null, '', '/settings/tokens');
    render(<MomentumApp />);
    const user = userEvent.setup();
    expect(await screen.findByText('No tokens yet')).toBeInTheDocument();

    const form = screen.getByRole('form', { name: 'Create a token' });
    await user.type(within(form).getByLabelText('Name'), 'Nightly ERP sync');
    await user.click(within(form).getByLabelText('Create and change tasks, projects and comments'));
    await user.click(within(form).getByRole('button', { name: 'Create token' }));

    const shown = await screen.findByRole('status', { name: 'New token' });
    expect(within(shown).getByText('mtm_AbCdEfSECRETvalue123')).toBeInTheDocument();
    expect(tokens.created).toEqual([
      { name: 'Nightly ERP sync', scopes: ['read', 'tasks:write'], expires_in_days: 90 },
    ]);
    const list = await screen.findByRole('region', { name: 'My tokens' });
    expect(await within(list).findByText('Nightly ERP sync')).toBeInTheDocument();
    expect(within(list).queryByText('mtm_AbCdEfSECRETvalue123')).toBeNull(); // only the prefix is listed

    await user.click(within(shown).getByRole('button', { name: 'Done' }));
    expect(screen.queryByText('mtm_AbCdEfSECRETvalue123')).toBeNull(); // gone for good
    await user.click(within(list).getByRole('button', { name: 'Revoke' }));
    await waitFor(() => expect(within(list).getByText(/Revoked/)).toBeInTheDocument());
  });
});
