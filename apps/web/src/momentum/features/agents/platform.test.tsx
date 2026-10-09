import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router';
import { Toaster } from 'sonner';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { RichTextView } from '@/components/editor/RichTextView';
import { MomentumApp } from '@/MomentumApp';
import { createApiClient } from '@/lib/api/client';
import {
  agentFixture,
  agentHandlers,
  cardFixture,
  healthFixture,
  profileFixture,
  runFixture,
} from '@/mocks/agents';
import { askFixture, askHandlers, taskJobFixture } from '@/mocks/asks';
import { authHandlers } from '@/mocks/handlers';
import { projectHandlers } from '@/mocks/projects';
import { teamHandlers } from '@/mocks/teams';
import { ApiContext } from '@/providers/api';
import { AskCard } from './AskCard';
import { TaskJobs } from './JobCard';
import { docText } from './platform';
import { useReplyAsAnswer } from './ReplyAsAnswer';
import { WaitingOnYou } from './WaitingOnYou';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function boot(path: string, extra: Parameters<typeof server.use> = [], role = 'member') {
  server.use(
    ...authHandlers({ loggedIn: true, me: { role } }).handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, []),
    ...extra,
  );
  window.history.replaceState(null, '', path);
  render(<MomentumApp />);
  return userEvent.setup();
}

function renderWithProviders(ui: ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <ApiContext.Provider value={createApiClient('')}>
        <MemoryRouter>
          {ui}
          <Toaster />
        </MemoryRouter>
      </ApiContext.Provider>
    </QueryClientProvider>,
  );
  return userEvent.setup();
}

const bernie = agentFixture({ id: 'agent-2', user_id: 'agent-user-2', key: 'bernie', name: 'Bernie' });
const bernieCard = cardFixture(bernie, {
  title: 'Accounts payable clerk',
  data_class: 'financial',
  capabilities: [
    {
      key: 'process_invoices',
      title: 'Process invoices',
      description: 'Reads supplier invoices',
      examples: ['Process the attached invoices'],
      files: ['pdf'],
      typical_duration_s: 60,
    },
  ],
  health: { jobs: 12, items: 40, success_rate: 0.9 },
});

describe('Agents directory (S76-07, spec §12.1)', () => {
  it('searches by what agents can do and shows capabilities, data class and health', async () => {
    const teammate = agentFixture();
    const agents = agentHandlers({
      list: [teammate, bernie],
      cards: [cardFixture(teammate), bernieCard],
    });
    const user = boot('/agents', agents.handlers);
    const list = await screen.findByRole('list', { name: 'Agents' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(2);
    const card = within(list).getByRole('link', { name: /Bernie/ });
    expect(within(card).getByText('Process invoices')).toBeInTheDocument();
    expect(within(card).getByText('Financial data')).toBeInTheDocument();
    expect(within(card).getByText(/12 jobs, 40 items, 90% succeeded/)).toBeInTheDocument();

    await user.type(screen.getByRole('searchbox', { name: 'Search agents' }), 'who can read invoices?');
    await waitFor(() =>
      expect(within(screen.getByRole('list', { name: 'Agents' })).getAllByRole('listitem')).toHaveLength(1),
    );
    expect(agents.directoryQueries.at(-1)?.get('q')).toBe('who can read invoices?');

    await user.selectOptions(screen.getByLabelText('Data'), 'personal');
    expect(await screen.findByText('No agent matches')).toBeInTheDocument();
    expect(agents.directoryQueries.at(-1)?.get('data_class')).toBe('personal');
  });
});

describe('Agent page tabs (S76-07, spec §12.2)', () => {
  it('Overview says what the agent may do in plain English and how to hand it work', async () => {
    const agents = agentHandlers({
      agent: agentFixture({ triggers: [{ type: 'assigned' }, { type: 'manual' }] }),
      profile: profileFixture({
        is_pack: true,
        title: 'Test pack',
        data_class: 'internal',
        charter: 'I repeat what I am given.',
        capabilities: [
          {
            key: 'echo',
            title: 'Echo the input',
            description: 'Returns the input text unchanged.',
            examples: ['Echo hello'],
            files: [],
            typical_duration_s: 1,
          },
        ],
        effects: ['comment on the task', 'create echo bill records'],
        can_run: true,
      }),
    });
    boot('/agents/agent-1', agents.handlers);
    const may = await screen.findByRole('region', { name: 'What it may do' });
    expect(within(may).getByText('create echo bill records')).toBeInTheDocument();
    expect(screen.getByText('“Echo hello”')).toBeInTheDocument();
    expect(screen.getByText('Internal data')).toBeInTheDocument();
    const hand = screen.getByRole('region', { name: 'Hand work' });
    expect(within(hand).getByText('Assign a task to Teammate.')).toBeInTheDocument();
    expect(within(hand).getByText(/Run now/)).toBeInTheDocument();
  });

  it('Health shows the numbers, and an empty state before any job', async () => {
    const agents = agentHandlers({
      health: healthFixture({
        jobs: 5,
        items: 4,
        success_rate: 0.75,
        median_active_seconds: 25,
        human_touch_rate: 0.25,
        cost_per_item_usd: 0.125,
        time_saved_minutes: 21,
        detail: true,
        top_corrected_fields: [['number', 1]],
        top_failure_reasons: [['Boom happened', 1]],
        calibration: { reviewed: 3, bands: [], note: 'Not enough reviewed items yet' },
      }),
    });
    const user = boot('/agents/agent-1?tab=health', agents.handlers);
    const numbers = await screen.findByRole('list', { name: 'Health numbers' });
    expect(within(numbers).getByText('75%')).toBeInTheDocument();
    expect(within(numbers).getByText('25s')).toBeInTheDocument();
    expect(within(numbers).getByText('$0.13')).toBeInTheDocument();
    expect(screen.getByText('Boom happened')).toBeInTheDocument();
    expect(screen.getByText(/Not enough reviewed items yet \(3 reviewed\)/)).toBeInTheDocument();
    await user.click(screen.getByRole('radio', { name: 'Last 90 days' }));
    expect(await screen.findByRole('list', { name: 'Health numbers' })).toBeInTheDocument();
  });

  it('Settings renders the pack form by its hints, saves this level, and offers undo', async () => {
    let undone: unknown = null;
    const agents = agentHandlers({ profile: profileFixture({ is_pack: true, has_settings: true }) });
    const user = boot(
      '/agents/agent-1?tab=settings',
      [
        ...agents.handlers,
        http.post('*/api/v1/undo', async ({ request }) => {
          undone = await request.json();
          return HttpResponse.json({ undone: 1 });
        }),
      ],
      'admin',
    );
    const form = await screen.findByRole('form', { name: 'Settings form' });
    expect(within(form).getByRole('checkbox')).not.toBeChecked();
    expect(within(form).getByLabelText('Confidence floor (percent)')).toHaveValue(85);
    expect(within(form).getByLabelText('Materiality in USD')).toHaveValue('5000');
    expect(within(form).getByRole('combobox', { name: 'Tone' })).toHaveValue('plain');
    expect(within(form).getByText('Nobody yet')).toBeInTheDocument();

    const threshold = within(form).getByRole('spinbutton', { name: 'Threshold' });
    await user.clear(threshold);
    await user.type(threshold, '7');
    await user.clear(within(form).getByLabelText('Confidence floor (percent)'));
    await user.type(within(form).getByLabelText('Confidence floor (percent)'), '90');
    await user.type(within(form).getByLabelText('Currency to add to Materiality'), 'gbp');
    await user.click(within(form).getByRole('button', { name: 'Add currency' }));
    await user.type(within(form).getByLabelText('Add to Watched sections'), 'Invoices in{Enter}');
    await user.click(within(form).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(agents.settingsPuts).toHaveLength(1));
    expect(agents.settingsPuts[0]).toEqual({
      projectId: null,
      values: {
        threshold: 7,
        confidence_floor: 0.9,
        materiality: { USD: '5000', GBP: '0' },
        sections: ['Invoices in'],
      },
    });
    await user.click(await screen.findByRole('button', { name: 'Undo' }));
    await waitFor(() => expect(undone).toEqual({ activity_id: 'act-settings' }));
  });

  it('switches to a project’s own settings', async () => {
    const agents = agentHandlers({ profile: profileFixture({ is_pack: true, has_settings: true }) });
    const user = boot('/agents/agent-1?tab=settings', agents.handlers, 'admin');
    await screen.findByRole('form', { name: 'Settings form' });
    await user.click(screen.getByRole('radio', { name: 'Website Revamp' }));
    expect(await screen.findAllByText('Inherited (the workspace value)')).not.toHaveLength(0);
  });
});

describe('Run page timeline (S76-07, spec §4.6)', () => {
  it('shows a job’s steps and nested sub-jobs, and its controls', async () => {
    const run = runFixture({
      mode: 'job',
      status: 'waiting',
      waiting_on: 'children',
      progress: { done: 1, total: 2, label: 'invoices' },
      trace: [],
      job_steps: [
        {
          seq: 1,
          key: 'ingest',
          kind: 'step',
          status: 'done',
          started_at: '2026-10-08T10:00:00Z',
          finished_at: '2026-10-08T10:00:01Z',
          duration_ms: 1200,
          tokens_in: 0,
          tokens_out: 0,
          cost_usd: '0',
          error: null,
          output: { files: 2 },
        },
        {
          seq: 2,
          key: 'extract',
          kind: 'llm',
          status: 'failed',
          started_at: '2026-10-08T10:00:01Z',
          finished_at: '2026-10-08T10:00:03Z',
          duration_ms: 2000,
          tokens_in: 900,
          tokens_out: 100,
          cost_usd: '0.01',
          error: 'Model timed out',
          output: null,
        },
      ],
      children: [
        { ...runFixture({ id: 'run-c1', status: 'succeeded', capability: 'process_invoice' }) },
        { ...runFixture({ id: 'run-c2', status: 'running', capability: 'process_invoice' }) },
      ],
    });
    const asks = askHandlers({ asks: [] });
    const user = boot('/agents/runs/run-1', [...agentHandlers({ run }).handlers, ...asks.handlers]);
    const timeline = await screen.findByRole('region', { name: 'Timeline' });
    expect(within(timeline).getByText('ingest')).toBeInTheDocument();
    expect(within(timeline).getByText('Model timed out')).toBeInTheDocument();
    expect(within(timeline).getByText(/1,000 tokens/)).toBeInTheDocument();
    expect(within(timeline).getByText(/Sub-jobs \(1 of 2 done\)/)).toBeInTheDocument();
    expect(within(timeline).getAllByRole('link')[0]).toHaveAttribute('href', '/agents/runs/run-c1');
    expect(screen.getByText('Its sub-jobs')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Pause' }));
    await waitFor(() => expect(asks.controls).toEqual(['pause']));
    await user.click(screen.getByRole('button', { name: 'Undo everything Teammate did' }));
    await user.click(screen.getByRole('button', { name: 'Undo all of it' }));
    expect(
      await screen.findByText('Undid 3 changes; 1 was changed by someone since and left as it is'),
    ).toBeInTheDocument();
  });
});

describe('On a task (S76-07, spec §12.3, §5.2-5.3)', () => {
  it('the job card shows progress, what it waits for, and updates after an answer', async () => {
    const asks = askHandlers({ jobs: [taskJobFixture({ task: { id: 't-1', key: 'T-12', title: 'x' } })] });
    server.use(...asks.handlers);
    const user = renderWithProviders(
      <>
        <TaskJobs taskId="t-1" />
        <AskCard askId="ask-1" />
      </>,
    );
    const card = await screen.findByRole('region', { name: 'Echo job' });
    expect(within(card).getByRole('progressbar', { name: 'Progress' })).toHaveAttribute('aria-valuenow', '2');
    expect(within(card).getByText('2 of 5 invoices')).toBeInTheDocument();
    expect(within(card).getByText('Waiting for an answer: “Which vendor is this?”')).toBeInTheDocument();
    expect(within(card).getByText(/Waiting on you: 1 question/)).toBeInTheDocument();

    const ask = await screen.findByRole('region', { name: 'Echo asks: Which vendor is this?' });
    expect(within(ask).getByText('Page 1: “Globex Ltd”')).toBeInTheDocument();
    await user.click(within(ask).getByRole('button', { name: 'Globex' }));
    await waitFor(() => expect(asks.answers).toEqual([{ id: 'ask-1', value: 'globex', via: 'card' }]));
    expect(await within(ask).findByText('Globex')).toBeInTheDocument();
    expect(within(ask).getByText(/Answered by Ravi Kumar/)).toBeInTheDocument();
    expect(within(ask).getByRole('button', { name: 'Change' })).toBeInTheDocument();
    await waitFor(() => expect(within(card).queryByText(/Waiting on you/)).toBeNull());
  });

  it('answers forms and confirms, and only shows controls to the people asked', async () => {
    const asks = askHandlers({
      asks: [
        askFixture({
          id: 'ask-f',
          kind: 'form',
          options: null,
          form: [
            { name: 'amount', label: 'Amount', type: 'money', required: true },
            { name: 'due', label: 'Due', type: 'date', required: false },
          ],
        }),
        askFixture({ id: 'ask-c', kind: 'confirm', options: null, title: 'Approve it?' }),
        askFixture({ id: 'ask-x', title: 'Not yours', can_answer: false }),
      ],
    });
    server.use(...asks.handlers);
    const user = renderWithProviders(
      <>
        <AskCard askId="ask-f" />
        <AskCard askId="ask-c" />
        <AskCard askId="ask-x" />
      </>,
    );
    await user.type(await screen.findByLabelText('Amount'), '1250.00');
    await user.click(screen.getAllByRole('button', { name: 'Send' })[0]!);
    await waitFor(() =>
      expect(asks.answers[0]).toEqual({ id: 'ask-f', value: { amount: '1250.00', due: '' }, via: 'card' }),
    );
    const confirm = screen.getByRole('region', { name: 'Echo asks: Approve it?' });
    await user.click(within(confirm).getByRole('button', { name: 'No' }));
    await waitFor(() => expect(asks.answers[1]).toEqual({ id: 'ask-c', value: false, via: 'card' }));
    const theirs = screen.getByRole('region', { name: 'Echo asks: Not yours' });
    expect(within(theirs).queryByRole('button')).toBeNull();
    expect(within(theirs).getByText('Waiting for Ravi Kumar.')).toBeInTheDocument();
  });

  it('renders an askCard node in a comment through the slot', async () => {
    server.use(...askHandlers().handlers);
    renderWithProviders(
      <RichTextView
        doc={{ type: 'doc', content: [{ type: 'askCard', attrs: { askId: 'ask-1' } }] }}
        askCard={(id) => <AskCard askId={id} />}
      />,
    );
    expect(
      await screen.findByRole('region', { name: 'Echo asks: Which vendor is this?' }),
    ).toBeInTheDocument();
  });

  it('reads a thread reply as the answer: applied when certain, confirmed when not', async () => {
    function Composer({ taskId }: { taskId: string }) {
      const reply = useReplyAsAnswer(taskId);
      return (
        <>
          <button
            type="button"
            onClick={() =>
              reply.afterSend({
                type: 'doc',
                content: [{ type: 'paragraph', content: [{ type: 'text', text: 'It is Globex' }] }],
              })
            }
          >
            Send comment
          </button>
          {reply.ui}
        </>
      );
    }
    const certain = askHandlers();
    server.use(...certain.handlers);
    const user = renderWithProviders(<Composer taskId="t-1" />);
    expect(
      await screen.findByLabelText(/Use this as the answer to Echo’s question “Which vendor is this\?”/),
    ).toBeChecked();
    await user.click(screen.getByRole('button', { name: 'Send comment' }));
    await waitFor(() => expect(certain.interpreted).toEqual([{ id: 'ask-1', text: 'It is Globex' }]));
    expect(await screen.findByText('Understood: Globex')).toBeInTheDocument();
  });

  it('asks to confirm an uncertain reading, never applying it silently', async () => {
    function Composer() {
      const reply = useReplyAsAnswer('t-1');
      return (
        <>
          <button
            type="button"
            onClick={() =>
              reply.afterSend({
                type: 'doc',
                content: [{ type: 'paragraph', content: [{ type: 'text', text: 'the first one' }] }],
              })
            }
          >
            Send comment
          </button>
          {reply.ui}
        </>
      );
    }
    const unsure = askHandlers({ interpret: 'unsure' });
    server.use(...unsure.handlers);
    const user = renderWithProviders(<Composer />);
    await screen.findByLabelText(/Use this as the answer/);
    await user.click(screen.getByRole('button', { name: 'Send comment' }));
    const box = await screen.findByRole('region', { name: 'Confirm the answer' });
    expect(unsure.answers).toEqual([]);
    await user.click(within(box).getByRole('button', { name: 'Yes, use it' }));
    await waitFor(() => expect(unsure.answers).toEqual([{ id: 'ask-1', value: 'globex', via: 'thread' }]));
  });

  it('Home’s “Waiting on you” lists my open questions, answerable in place', async () => {
    const asks = askHandlers();
    server.use(...asks.handlers);
    const user = renderWithProviders(<WaitingOnYou />);
    const card = await screen.findByRole('region', { name: 'Waiting on you' });
    expect(within(card).getByRole('link', { name: 'Open the task' })).toHaveAttribute('href', '/task/t-1');
    await user.click(within(card).getByRole('button', { name: 'Initech' }));
    await waitFor(() => expect(asks.answers).toEqual([{ id: 'ask-1', value: 'initech', via: 'card' }]));
  });

  it('docText flattens a comment to plain text', () => {
    expect(
      docText({
        type: 'doc',
        content: [
          {
            type: 'paragraph',
            content: [
              { type: 'text', text: 'Use ' },
              { type: 'mention', attrs: { label: 'Bernie' } },
            ],
          },
          { type: 'paragraph', content: [{ type: 'text', text: '1,250.00' }] },
        ],
      }),
    ).toBe('Use @Bernie\n1,250.00');
  });
});
