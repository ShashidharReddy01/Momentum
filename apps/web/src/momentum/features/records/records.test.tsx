import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { MemoryRouter } from 'react-router';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { createApiClient } from '@/lib/api/client';
import { MomentumApp } from '@/MomentumApp';
import { agentFixture, agentHandlers } from '@/mocks/agents';
import { authHandlers } from '@/mocks/handlers';
import { projectHandlers } from '@/mocks/projects';
import { recordFixture, recordHandlers, skillFixture } from '@/mocks/records';
import { sectionHandlers } from '@/mocks/sections';
import { taskHandlers } from '@/mocks/tasks';
import { teamHandlers } from '@/mocks/teams';
import { ApiContext } from '@/providers/api';
import { applyOps, formSpec, pushOp, sumMoney, whereOnPage } from './model';
import { RecordPanel } from './RecordPanel';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function boot(path: string, extra: Parameters<typeof server.use> = [], role = 'member') {
  server.use(
    ...extra,
    ...authHandlers({ loggedIn: true, me: { role } }).handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, [{ name: 'Website Revamp', my_role: 'admin' }]),
    ...sectionHandlers('', { 'seed-1': ['Backlog'] }),
    ...taskHandlers('', { 'seed-1': { 'sec-1': ['First'] } }),
  );
  window.history.replaceState(null, '', path);
  render(<MomentumApp />);
  return userEvent.setup();
}

describe('Record model (S76-08)', () => {
  it('builds the form from the schema and display spec', async () => {
    const { billTypeFixture } = await import('@/mocks/records');
    const t = billTypeFixture();
    const spec = formSpec(t.schema as never, t.display as never);
    expect(spec.fields.map((f) => [f.path, f.kind])).toEqual([
      ['vendor.name', 'text'],
      ['number', 'text'],
      ['total', 'money'],
      ['currency', 'currency'],
      ['dated', 'date'],
    ]);
    expect(spec.arrays[0]!.columns.map((c) => [c.path, c.kind])).toEqual([
      ['description', 'text'],
      ['amount', 'money'],
    ]);
  });

  it('applies operations as the server will, and coalesces typing', () => {
    const data = { number: 'A', lines: [{ amount: '1' }, { amount: '2' }] };
    let ops = pushOp([], { op: 'set', path: 'number', value: 'B' });
    ops = pushOp(ops, { op: 'set', path: 'number', value: 'BC' });
    expect(ops).toHaveLength(1);
    ops = [...ops, { op: 'move_item', array: 'lines', from: 1, to: 0 }];
    ops = [...ops, { op: 'add_item', array: 'lines', item: { amount: '3' } }];
    ops = pushOp(ops, { op: 'set', path: 'lines[2].amount', value: '4' });
    expect(applyOps(data, ops)).toEqual({
      number: 'BC',
      lines: [{ amount: '2' }, { amount: '1' }, { amount: '4' }],
    });
    expect(data.number).toBe('A');
  });

  it('sums money in exact cents and says where a box is', () => {
    expect(sumMoney(['60.00', '40.1', '0.05'])).toBe('100.15');
    expect(sumMoney(['1,200.00', '-0.50'])).toBe('1199.50');
    expect(sumMoney(['twelve'])).toBeNull();
    expect(whereOnPage({ page: 1, bbox: [450, 40, 560, 60] }, { width: 612, height: 792 })).toBe(
      'page 1, top right',
    );
    expect(whereOnPage({ page: 2 })).toBe('page 2');
  });
});

describe('Review screen (S76-08, spec §12.4)', () => {
  it('links highlights and fields both ways, and saves corrections as operations with undo', async () => {
    const recs = recordHandlers();
    let undone: unknown = null;
    const user = boot('/records/rec-1', [
      ...recs.handlers,
      http.post('*/api/v1/undo', async ({ request }) => {
        undone = await request.json();
        return HttpResponse.json({ undone: 1 });
      }),
    ]);
    expect(await screen.findByRole('heading', { name: 'Acme Ltd INV-0041' })).toBeInTheDocument();
    expect(screen.getByText('Needs review')).toBeInTheDocument();
    expect(await screen.findByText(/page 1 of 2/)).toBeInTheDocument();
    // every highlight has a text equivalent
    const box = screen.getByRole('button', { name: 'Number: page 1, top right' });
    await user.click(box);
    const number = screen.getByRole('textbox', { name: /Number/ });
    await waitFor(() => expect(number).toHaveFocus());
    expect(box).toHaveAttribute('aria-pressed', 'true');

    // lines: grid with a per-currency totals row
    const grid = screen.getByRole('grid', { name: 'Lines grid' });
    expect(within(grid).getByText('100.00 USD')).toBeInTheDocument();
    await user.click(within(grid).getByRole('textbox', { name: 'Amount, row 1' }));
    await user.keyboard('{ArrowDown}');
    await waitFor(() => expect(within(grid).getByRole('textbox', { name: 'Amount, row 2' })).toHaveFocus());
    await user.click(within(grid).getByRole('button', { name: 'Remove row 2' }));
    expect(within(grid).getByText('60.00 USD')).toBeInTheDocument();

    await user.clear(number);
    await user.type(number, 'INV-9');
    await user.click(screen.getByRole('button', { name: /Save \(2 changes\)/ }));
    await waitFor(() => expect(recs.patches).toHaveLength(1));
    expect(recs.patches[0]).toEqual({
      ops: [
        { op: 'remove_item', array: 'lines', index: 1 },
        { op: 'set', path: 'number', value: 'INV-9' },
      ],
      expected_version: 2,
    });
    await user.click(await screen.findByRole('button', { name: 'Undo' }));
    await waitFor(() => expect(undone).toEqual({ activity_id: 'act-rec' }));
  });

  it('shows failing checks first with links to their fields, and the agent’s suggestion', async () => {
    const user = boot('/records/rec-1', recordHandlers().handlers);
    const checks = await screen.findByRole('region', { name: 'Checks' });
    expect(within(checks).getByText('(1 need attention)')).toBeInTheDocument();
    expect(within(checks).getAllByRole('listitem')[0]).toHaveTextContent('No purchase order found');
    await user.click(within(checks).getByRole('button', { name: 'Number' }));
    await waitFor(() => expect(screen.getByRole('textbox', { name: /Number/ })).toHaveFocus());
    expect(screen.getByRole('region', { name: 'Decision' })).toHaveTextContent('No purchase order matched');
    const entity = screen.getByRole('region', { name: 'Linked entity' });
    expect(await within(entity).findByRole('link', { name: 'Acme Ltd' })).toHaveAttribute(
      'href',
      '/entities/ent-1',
    );
    expect(within(entity).getByText('Bank account •••• 4821')).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'History' })).toHaveTextContent('Dated → 2026-09-15');
  });

  it('offers reload-and-reapply on a conflict and keeps the edits', async () => {
    const recs = recordHandlers({ conflictOnce: true });
    const user = boot('/records/rec-1', recs.handlers);
    const number = await screen.findByRole('textbox', { name: /Number/ });
    await user.clear(number);
    await user.type(number, 'INV-7');
    await user.click(screen.getByRole('button', { name: /^Save \(/ }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Someone else changed this record');
    await user.click(within(alert).getByRole('button', { name: 'Reload and reapply my changes' }));
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
    expect(screen.getByRole('textbox', { name: /Number/ })).toHaveValue('INV-7');
    await user.click(screen.getByRole('button', { name: /^Save \(/ }));
    await waitFor(() => expect(recs.patches).toHaveLength(2));
    expect(recs.patches[1]).toMatchObject({ expected_version: 3 });
  });

  it('approves, asks why on reject, and refuses while a blocking check fails', async () => {
    const recs = recordHandlers();
    const user = boot('/records/rec-1', recs.handlers);
    const decision = await screen.findByRole('region', { name: 'Decision' });
    await user.click(within(decision).getByRole('button', { name: 'Reject…' }));
    expect(within(decision).getByRole('button', { name: 'Reject' })).toBeDisabled();
    await user.type(within(decision).getByLabelText('Why reject it?'), 'Not ours');
    await user.click(within(decision).getByRole('button', { name: 'Reject' }));
    await waitFor(() =>
      expect(recs.patches[0]).toMatchObject({
        ops: [{ op: 'set_status', status: 'rejected', reason: 'Not ours' }],
      }),
    );
  });

  it('blocks approval while a blocking check fails, and is read-only without edit rights', async () => {
    const record = recordFixture({
      checks: [
        { id: 'x', severity: 'block', passed: false, title: 'Lines add up to the total', fields: ['total'] },
      ],
      can_edit: false,
      can_decide: true,
    });
    boot('/records/rec-1', recordHandlers({ record }).handlers);
    const decision = await screen.findByRole('region', { name: 'Decision' });
    expect(within(decision).getByRole('button', { name: 'Approve' })).toBeDisabled();
    expect(within(decision).getByText('Fix the blocking checks first.')).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: /Number/ })).toBeDisabled();
    expect(screen.queryByRole('button', { name: /Save/ })).toBeNull();
    expect(screen.getByText('You can look at this record but not change it.')).toBeInTheDocument();
  });
});

describe('Records tab (S76-08, spec §12.5)', () => {
  it('lists records from the type’s columns, totals per currency, and voids as one undo', async () => {
    const recs = recordHandlers();
    const user = boot('/projects/seed-1/records', recs.handlers);
    const table = await screen.findByRole('table', { name: 'Echo bill records' });
    expect(within(table).getByRole('columnheader', { name: 'Name' })).toBeInTheDocument();
    expect(await within(table).findByRole('link', { name: 'Acme Ltd' })).toHaveAttribute(
      'href',
      '/records/rec-1',
    );
    const totals = await screen.findByLabelText('Totals');
    expect(totals).toHaveTextContent('550.50 USD · 2 records');
    expect(totals).toHaveTextContent('800.00 EUR · 1 record');
    expect(totals).toHaveTextContent('never added across currencies');
    await user.selectOptions(screen.getByLabelText('Status'), 'ready');
    await waitFor(() => expect(recs.listQueries.at(-1)?.getAll('status')).toEqual(['ready']));
    await user.selectOptions(screen.getByLabelText('Status'), '');
    await user.click(await screen.findByRole('checkbox', { name: 'Select all' }));
    await user.click(screen.getByRole('button', { name: 'Void' }));
    await waitFor(() => expect(recs.bulk).toEqual([{ ids: ['rec-1', 'rec-2'], status: 'void' }]));
    expect(await screen.findByText('Voided 2 records')).toBeInTheDocument();
  });

  it('shows the record panel on a task', async () => {
    server.use(...recordHandlers().handlers);
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <ApiContext.Provider value={createApiClient('')}>
          <MemoryRouter>
            <RecordPanel taskId="t-1" />
          </MemoryRouter>
        </ApiContext.Provider>
      </QueryClientProvider>,
    );
    const panel = await screen.findByRole('region', { name: 'Records' });
    const card = within(panel).getAllByRole('article')[0]!;
    expect(within(card).getByText('Needs review')).toBeInTheDocument();
    expect(within(card).getByRole('link', { name: 'Open review' })).toHaveAttribute('href', '/records/rec-1');
    expect(await within(card).findByText('Acme Ltd')).toBeInTheDocument(); // a key field from the columns
    expect(within(card).getByText('✦ No purchase order matched')).toBeInTheDocument();
  });
});

describe('Entities (S76-08, spec §12.5)', () => {
  it('shows an entity’s names, bank display, records, skills and history', async () => {
    const recs = recordHandlers({ skills: [skillFixture({ status: 'active' })] });
    boot('/entities/ent-1', recs.handlers);
    expect(await screen.findByRole('heading', { name: 'Acme Ltd' })).toBeInTheDocument();
    expect(screen.getByText('ACME Limited')).toBeInTheDocument();
    expect(screen.getByText('Bank account •••• 4821')).toBeInTheDocument();
    expect(await screen.findByRole('link', { name: 'Acme Ltd INV-0041' })).toBeInTheDocument();
    const skills = screen.getByRole('region', { name: 'Skills for it' });
    expect(await within(skills).findByText(/Acme puts the invoice number top right/)).toBeInTheDocument();
    const history = screen.getByRole('region', { name: 'Activity' });
    expect(await within(history).findByText('Created')).toBeInTheDocument();
  });

  it('lists and searches entities', async () => {
    const user = boot('/entities', recordHandlers().handlers);
    const list = await screen.findByRole('list', { name: 'Entities' });
    expect(within(list).getByRole('link', { name: /Acme Ltd/ })).toHaveAttribute('href', '/entities/ent-1');
    await user.type(screen.getByRole('searchbox', { name: 'Search entities' }), 'glob');
    expect(within(list).getByRole('link', { name: /Globex/ })).toBeInTheDocument();
  });
});

describe('Skills admin (S76-08, spec §12.6)', () => {
  it('approves a proposed skill as is or edited, and flags a hurting one', async () => {
    const recs = recordHandlers();
    const agent = agentFixture({ kind: 'pack', pack_key: 'echo' });
    const user = boot(
      '/agents/agent-1?tab=skills',
      [...recs.handlers, ...agentHandlers({ agent }).handlers],
      'admin',
    );
    const card = (await screen.findByText(/Acme puts the invoice number/)).closest('li')!;
    expect(within(card).getByLabelText('Tryout')).toHaveTextContent('wrong 3 → 0');
    expect(within(card).getByLabelText('Tryout')).toHaveTextContent('nothing got worse');
    await user.click(within(card).getByRole('button', { name: 'Edit and approve' }));
    const text = within(card).getByRole('textbox', { name: 'Skill text' });
    await user.clear(text);
    await user.type(text, 'Number is after Ref.');
    await user.click(within(card).getByRole('button', { name: 'Approve edited' }));
    await waitFor(() =>
      expect(recs.decisions).toEqual([
        { id: 'sk-1', decision: 'approve', body: { note: null, content: { text: 'Number is after Ref.' } } },
      ]),
    );
    await user.click(screen.getByRole('radio', { name: 'Active' }));
    expect(await screen.findByText('May be hurting')).toBeInTheDocument();
    await act(async () => {
      await user.click(screen.getByRole('button', { name: 'Retire' }));
    });
    await waitFor(() => expect(recs.decisions.at(-1)).toMatchObject({ id: 'sk-2', decision: 'retire' }));
  });
});
