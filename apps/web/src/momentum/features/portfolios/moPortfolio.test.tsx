import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { authHandlers } from '@/mocks/handlers';
import { lifecycleState, portfolioV2Handlers } from '@/mocks/portfolios';
import { projectHandlers } from '@/mocks/projects';
import { teamHandlers } from '@/mocks/teams';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'bypass' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const meta = { activity_id: '01a0ccaf-0000-7000-8000-00000000f010', version: 1 };
const statusUpdate = {
  status: 'at_risk',
  title: 'Portfolio brief, 07 Oct 2026',
  summary: 'Two customers are slipping.',
  sections: { completed: [], slipped: [{ text: 'Northwind Health slips 12 days.' }], blockers: [], next: [] },
  generated_by_ai: true,
};

function boot(path: string) {
  const posted: { path: string; body: unknown }[] = [];
  const rowUrls: string[] = [];
  const state = lifecycleState();
  server.use(
    ...authHandlers({ loggedIn: true }).handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, [{ name: 'Website Revamp' }]),
  );
  server.use(...portfolioV2Handlers(state));
  server.use(
    http.get('*/api/v1/portfolios/:id/rows', ({ request }) => {
      rowUrls.push(request.url); // falls through to the portfolio mock
    }),
    http.post('*/api/v1/ai/portfolios/:id/brief', () =>
      HttpResponse.json({
        portfolio_id: 'pf-life',
        portfolio: 'Customer onboarding',
        headline: 'Two customers are slipping; Discovery is the bottleneck.',
        items: [
          {
            kind: 'slipping',
            text: 'Northwind Health slips 12 days.',
            cites: ['Northwind Health'],
            project_ids: ['p-north'],
          },
          {
            kind: 'bottleneck',
            text: 'Discovery runs 30 days against 21.',
            cites: ['Discovery'],
            project_ids: [],
          },
        ],
        hidden: 1,
        ai: true,
        status_update: statusUpdate,
      }),
    ),
    http.post('*/api/v1/portfolios/:id/status-updates', async ({ request }) => {
      posted.push({ path: new URL(request.url).pathname, body: await request.json() });
      return HttpResponse.json({ data: { id: 'su-1', ...statusUpdate }, meta }, { status: 201 });
    }),
    http.post('*/api/v1/ai/filters', async ({ request }) => {
      const body = (await request.json()) as { text: string };
      if (body.text.includes('Pilot'))
        return HttpResponse.json({
          surface: 'portfolio',
          filters: {},
          chips: [],
          question: 'There’s no stage "Pilot". Which stage did you mean?',
          options: ['Discovery', 'Contracts'],
        });
      return HttpResponse.json({
        surface: 'portfolio',
        filters: { status: ['at_risk'], stage: ['s-impl'] },
        chips: [
          { key: 'status', label: 'Health: At risk' },
          { key: 'stage', label: 'Stage: Implementation' },
        ],
        question: null,
        options: [],
      });
    }),
    http.post('*/api/v1/ai/portfolios/:pf/projects/:pid/readiness', async ({ request }) => {
      const body = (await request.json()) as { read_files: boolean };
      return HttpResponse.json({
        project: 'Northwind Health',
        readiness: {
          stage: 's-impl',
          stage_label: 'Implementation',
          met: false,
          items: [
            { kind: 'milestone', label: 'Contract signed', met: false, ref: null },
            { kind: 'file', label: '*signed*', met: true, ref: { type: 'file', id: 'att-1' } },
          ],
        },
        notes: body.read_files
          ? [
              {
                item: '*signed*',
                text: 'The contract has no signature date.',
                concern: true,
                cites: ['contract.pdf'],
              },
            ]
          : [],
        files_read: body.read_files ? ['contract.pdf'] : [],
        unreadable: [],
        ai: body.read_files,
      });
    }),
    http.post('*/api/v1/ai/projects/:pid/handoff', () =>
      HttpResponse.json({
        project_id: 'p-north',
        project: 'Northwind Health',
        to_stage: 'Contracts',
        sections: {
          sold: [{ text: 'Core and Analytics, 120,000 EUR.', cites: ['Products'] }],
          risks: [{ text: 'The SOW review is overdue [T-4].', cites: ['T-4'] }],
        },
        files_read: [],
        status_update: { ...statusUpdate, title: 'Handoff to Contracts: Northwind Health' },
      }),
    ),
    http.post('*/api/v1/projects/:pid/status-updates', async ({ request }) => {
      posted.push({ path: new URL(request.url).pathname, body: await request.json() });
      return HttpResponse.json({ data: { id: 'su-2', ...statusUpdate }, meta }, { status: 201 });
    }),
  );
  window.history.replaceState(null, '', path);
  render(<MomentumApp />);
  return { posted, rowUrls, state, user: userEvent.setup() };
}

describe('Mo on a portfolio (S75-10)', () => {
  it('briefs, then posts the brief as a status update only after the preview', async () => {
    const { posted, user } = boot('/portfolios/pf-life');
    await user.click(await screen.findByRole('button', { name: /Brief me/ }));
    const dialog = await screen.findByRole('dialog', { name: 'Brief: Customer onboarding' });
    expect(await within(dialog).findByText(/Discovery is the bottleneck/)).toHaveClass('text-amber-ink');
    const list = within(dialog).getByRole('list', { name: 'Brief' });
    expect(within(list).getByText('Slipping')).toBeInTheDocument();
    expect(
      within(dialog).getByText(/1 project in this portfolio you can’t see isn’t included/),
    ).toBeInTheDocument();
    expect(posted).toHaveLength(0);
    await user.click(within(dialog).getByRole('button', { name: 'Post as status update…' }));
    expect(within(dialog).getByRole('region', { name: 'Status update preview' })).toHaveTextContent(
      'Northwind Health slips 12 days.',
    );
    await user.click(within(dialog).getByRole('button', { name: 'Post status update' }));
    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0]).toMatchObject({
      path: '/api/v1/portfolios/pf-life/status-updates',
      body: { generated_by_ai: true },
    });
  });

  it('turns a sentence into filter chips that apply only on Apply', async () => {
    const { rowUrls, user } = boot('/portfolios/pf-life/table');
    await screen.findByRole('table', { name: 'Projects in Customer onboarding' });
    await user.type(
      screen.getByRole('textbox', { name: 'Ask the portfolio' }),
      'Anything in the Pilot stage',
    );
    await user.click(screen.getByRole('button', { name: /^Ask$/ }));
    expect(await screen.findByText(/no stage "Pilot"/)).toBeInTheDocument();
    expect(screen.getByText('Options: Discovery, Contracts')).toBeInTheDocument();

    await user.clear(screen.getByRole('textbox', { name: 'Ask the portfolio' }));
    await user.type(screen.getByRole('textbox', { name: 'Ask the portfolio' }), 'At risk implementations');
    await user.click(screen.getByRole('button', { name: /^Ask$/ }));
    const chips = await screen.findByLabelText("Mo's filters");
    expect(within(chips).getByText('Stage: Implementation')).toBeInTheDocument();
    expect(rowUrls.some((u) => u.includes('filters='))).toBe(false); // not applied yet
    await user.click(within(chips).getByRole('button', { name: 'Apply' }));
    expect(await screen.findByText('Filtered with Mo')).toBeInTheDocument();
    await waitFor(() =>
      expect(rowUrls.some((u) => decodeURIComponent(u).includes('"stage":["s-impl"]'))).toBe(true),
    );
    await user.click(screen.getByRole('button', { name: "Clear Mo's filters" }));
    await waitFor(() => expect(screen.queryByText('Filtered with Mo')).toBeNull());
  });

  it('checks readiness from a card, reading files only when ticked; offers a handoff after a move', async () => {
    const { posted, user } = boot('/portfolios/pf-life/board');
    const discovery = await screen.findByRole('listitem', { name: 'Discovery: 2 projects' });
    await user.click(within(discovery).getByRole('button', { name: 'Move Northwind Health to stage…' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Implementation readiness' }));
    const dialog = await screen.findByRole('dialog', {
      name: /Readiness of Northwind Health for Implementation/,
    });
    expect(await within(dialog).findByText('Not ready yet.')).toBeInTheDocument();
    const check = within(dialog).getByRole('button', { name: /Check the files/ });
    expect(check).toBeDisabled();
    await user.click(within(dialog).getByRole('checkbox', { name: 'Also let Mo read the files' }));
    await user.click(check);
    expect(await within(dialog).findByText('The contract has no signature date.')).toHaveClass(
      'text-amber-ink',
    );
    await user.click(within(dialog).getByRole('button', { name: 'Done' }));

    // a move offers the handoff; nothing is written until it's posted
    await user.click(within(discovery).getByRole('button', { name: 'Move Northwind Health to stage…' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Contracts' }));
    await user.click(await screen.findByRole('button', { name: /Draft handoff to Contracts/ }));
    const h = await screen.findByRole('dialog', { name: /Draft handoff to Contracts: Northwind Health/ });
    await user.click(within(h).getByRole('button', { name: /Draft handoff/ }));
    const note = await within(h).findByLabelText('Handoff note');
    expect(within(note).getByText('What was sold')).toBeInTheDocument();
    expect(posted).toHaveLength(0);
    await user.click(within(h).getByRole('button', { name: 'Post as status update' }));
    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0]).toMatchObject({
      path: '/api/v1/projects/p-north/status-updates',
      body: { title: 'Handoff to Contracts: Northwind Health', generated_by_ai: true },
    });
  });
});
