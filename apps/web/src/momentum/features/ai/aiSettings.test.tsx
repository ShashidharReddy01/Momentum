import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { aiAdminHandlers, aiMemoryHandlers } from '@/mocks/ai';
import { authHandlers } from '@/mocks/handlers';
import { projectHandlers } from '@/mocks/projects';
import { teamHandlers } from '@/mocks/teams';
import type { components } from '@/lib/api/schema';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const prefsHandler = http.get('*/api/v1/ai/prefs', () => HttpResponse.json({ auto_apply_low_risk: false }));

async function boot(
  role: 'admin' | 'member',
  bullets: string[],
  admin?: {
    config?: components['schemas']['AiConfig'];
    usage?: Partial<components['schemas']['UsageReport']>;
  },
) {
  const mem = aiMemoryHandlers(bullets, { canEdit: role === 'admin' });
  const adminApi = aiAdminHandlers(admin?.config, admin?.usage, { canEdit: role === 'admin' });
  server.use(
    ...authHandlers({ loggedIn: true, me: { role } }).handlers,
    ...teamHandlers(),
    ...projectHandlers(),
    ...mem.handlers,
    ...adminApi.handlers,
    prefsHandler,
  );
  window.history.replaceState(null, '', '/settings/ai');
  render(<MomentumApp />);
  await screen.findByRole('heading', { name: 'AI settings' });
  return { user: userEvent.setup(), mem, adminApi };
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

describe('AI settings: admin section (S3.5.2)', () => {
  it('a member sees no admin section at all', async () => {
    await boot('member', []);
    expect(screen.queryByRole('heading', { name: 'Admin' })).toBeNull();
    expect(screen.queryByRole('heading', { name: /Usage/ })).toBeNull();
  });

  it('an admin sees the effective settings, model aliases and usage', async () => {
    await boot('admin', [], {
      config: { monthly_budget_usd: 10 },
      usage: {
        month_spend_usd: '1.23',
        by_feature: [
          { feature: 'chat', calls: 3, tokens_in: 100, tokens_out: 50, cost_usd: '1.23', errors: 1 },
        ],
      },
    });
    expect(await screen.findByRole('heading', { name: 'Admin' })).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: /Mo is turned on/ })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: /apply low-risk changes/ })).toBeChecked();
    expect(screen.getByText('provider/chat-default')).toBeInTheDocument();
    expect(await screen.findByText('$1.23 spent this month of a $10.00 budget.')).toBeInTheDocument();
    const table = screen.getByText('By feature').closest('table')!;
    expect(within(table).getByText('chat')).toBeInTheDocument();
    expect(within(table).getByText('3')).toBeInTheDocument();
  });

  it('unchecking "Mo is turned on" saves an explicit override', async () => {
    const { user, adminApi } = await boot('admin', []);
    await user.click(await screen.findByRole('checkbox', { name: /Mo is turned on/ }));
    await waitFor(() => expect(adminApi.config().enabled).toBe(false));
  });

  it("turning off auto-apply policy sends an explicit false, not the checkbox's displayed default", async () => {
    const { user, adminApi } = await boot('admin', []);
    await user.click(await screen.findByRole('checkbox', { name: /apply low-risk changes/ }));
    await waitFor(() => expect(adminApi.config().allow_auto_apply).toBe(false));
  });

  it('a blank budget field saves null (defer to the deployment default)', async () => {
    const { user, adminApi } = await boot('admin', [], { config: { monthly_budget_usd: 50 } });
    const input = await screen.findByLabelText('Monthly budget (USD)');
    await user.clear(input);
    await waitFor(() => expect(adminApi.config().monthly_budget_usd).toBeNull());
  });
});
