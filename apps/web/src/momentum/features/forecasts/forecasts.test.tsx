import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import type { ReactElement } from 'react';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { addDays, toISODate } from '@/lib/dates';
import { createApiClient } from '@/lib/api/client';
import { ApiContext } from '@/providers/api';
import { ForecastCard } from './ForecastCard';
import { basis, day, verdict } from './model';
import type { Forecast } from './queries';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderWithProviders(ui: ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ApiContext.Provider value={createApiClient('')}>{ui}</ApiContext.Provider>
    </QueryClientProvider>,
  );
}

const iso = (days: number) => toISODate(addDays(new Date(), days));
const forecast = (extra: Partial<Forecast> = {}): Forecast => ({
  id: 'f1',
  project_id: 'p1',
  computed_at: new Date().toISOString(),
  as_of: iso(0),
  status: 'ok',
  p50: iso(20),
  p80: iso(26),
  p95: iso(33),
  due_on: iso(15),
  risk_score: 52,
  risk_level: 'medium',
  drivers: [
    {
      kind: 'forecast',
      text: 'Likely to finish in 20 days, 5 days after the due date',
      points: 40,
      tasks: [],
    },
    {
      kind: 'unassigned',
      text: '1 task(s) due within 3 days have no one assigned',
      points: 12,
      tasks: ['T-4 Copy'],
    },
  ],
  inputs: {
    mode: 'tasks',
    remaining: 12,
    weeks: 6,
    throughput: [3, 4, 2, 5, 4, 3],
    added: [0, 1, 0, 0, 2, 0],
    runs: 10000,
    chain_days: 3,
  },
  ...extra,
});

describe('forecast model (S6.5.3)', () => {
  it('reads the forecast against the due date', () => {
    expect(verdict(forecast())).toEqual({ text: 'Likely 5 days late', tone: 'crit' });
    expect(verdict(forecast({ due_on: iso(22) })).tone).toBe('warn');
    expect(verdict(forecast({ due_on: iso(30) }))).toEqual({
      text: 'On track, with a small risk',
      tone: 'ok',
    });
    expect(verdict(forecast({ due_on: iso(40) })).text).toBe('On track for the due date');
    expect(verdict(forecast({ due_on: null })).tone).toBe('none');
  });

  it('names the year only when it is not this year', () => {
    const year = new Date().getFullYear();
    expect(day(`${year}-03-04`)).not.toMatch(String(year));
    expect(day(`${year + 1}-03-04`)).toMatch(String(year + 1));
  });

  it('says what it is based on', () => {
    expect(basis(forecast())).toBe(
      `12 tasks left · 3.5 tasks/week over the last 6 weeks · 0.5 tasks/week added · ${(10000).toLocaleString()} simulated futures`,
    );
  });
});

describe('ForecastCard (S6.5.3)', () => {
  it('shows the likely date, the range against the due date, the risk and why', async () => {
    server.use(http.get('*/api/v1/projects/:id/forecast', () => HttpResponse.json({ forecast: forecast() })));
    renderWithProviders(<ForecastCard projectId="p1" />);
    const card = await screen.findByRole('region', { name: 'Forecast' });
    expect(await within(card).findByText(/^Likely done /)).toBeInTheDocument();
    expect(within(card).getByText('Likely 5 days late')).toHaveClass('text-crit');
    expect(within(card).getByRole('figure')).toHaveAccessibleName(/50% by .*, 80% by .*, 95% by .*; due /);
    const why = within(card).getByRole('list', { name: 'What drives the risk' });
    expect(why).toHaveTextContent('+40');
    expect(why).toHaveTextContent('T-4 Copy');
    expect(within(card).getByText('52')).toBeInTheDocument();
  });

  it('says there is no finish date while work grows faster than it gets done', async () => {
    server.use(
      http.get('*/api/v1/projects/:id/forecast', () =>
        HttpResponse.json({ forecast: forecast({ status: 'growing', p50: null, p80: null, p95: null }) }),
      ),
    );
    renderWithProviders(<ForecastCard projectId="p1" />);
    expect(await screen.findByText(/no finish date to forecast yet/)).toBeInTheDocument();
    expect(screen.queryByText(/^Likely done/)).toBeNull();
  });

  it('is honest when there is nothing to go on, and refreshes on request', async () => {
    let posted = 0;
    server.use(
      http.get('*/api/v1/projects/:id/forecast', () =>
        HttpResponse.json({ forecast: forecast({ status: 'no_history', p50: null, p80: null, p95: null }) }),
      ),
      http.post('*/api/v1/projects/:id/forecast', () => {
        posted += 1;
        return HttpResponse.json({ forecast: forecast({ status: 'done', p50: null, p80: null, p95: null }) });
      }),
    );
    renderWithProviders(<ForecastCard projectId="p1" />);
    expect(await screen.findByText(/Not enough finished work to forecast yet/)).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole('button', { name: 'Refresh the forecast' }));
    expect(await screen.findByText(/every task is done/)).toBeInTheDocument();
    expect(posted).toBe(1);
  });
});
