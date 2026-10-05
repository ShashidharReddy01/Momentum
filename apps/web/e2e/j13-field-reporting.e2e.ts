import { expect, test, type APIRequestContext } from '@playwright/test';
import { login, settled } from './helpers';

/**
 * J13 (Phase 7, S7.4.1 acceptance): one custom field shared by two projects. Filter a project's
 * list by it (the board follows the same filter), find tasks by it across both projects in search,
 * and chart it on a workspace dashboard: the total of a number field over the tasks in one option,
 * counted across both projects. Projects, fields and values are made through the API (setup);
 * the filtering and charting are done in the UI.
 */
const H = { 'X-Requested-With': 'momentum' };

async function json(r: Awaited<ReturnType<APIRequestContext['get']>>) {
  expect(r.ok(), await r.text()).toBeTruthy();
  return r.json();
}

test('J13: filter, search and chart by a custom field across two projects', async ({ page }) => {
  await login(page);
  const api = page.request;
  const teams = (await json(await api.get('/api/v1/teams'))).data as { id: string; name: string }[];
  const team = teams.find((t) => t.name === 'Product')!.id;
  const project = async (name: string) =>
    (await json(await api.post('/api/v1/projects', { headers: H, data: { team_id: team, name } }))).data
      .id as string;
  const alpha = await project('J13 Alpha');
  const beta = await project('J13 Beta');
  const stage = (
    await json(
      await api.post(`/api/v1/projects/${alpha}/fields`, {
        headers: H,
        data: { name: 'J13 Stage', type: 'single_select', options: [{ label: 'Plan' }, { label: 'Ship' }] },
      }),
    )
  ).data;
  const points = (
    await json(
      await api.post(`/api/v1/projects/${alpha}/fields`, {
        headers: H,
        data: { name: 'J13 Points', type: 'number' },
      }),
    )
  ).data;
  for (const f of [stage, points])
    await json(
      await api.post(`/api/v1/projects/${beta}/fields/attach`, { headers: H, data: { field_id: f.id } }),
    );
  const [plan, ship] = stage.options.map((o: { id: string }) => o.id);
  const task = async (pid: string, title: string, option: string, pts: number) => {
    const id = (await json(await api.post(`/api/v1/projects/${pid}/tasks`, { headers: H, data: { title } })))
      .data.id as string;
    await json(
      await api.put(`/api/v1/tasks/${id}/fields/${stage.id}`, { headers: H, data: { value: option } }),
    );
    await json(
      await api.put(`/api/v1/tasks/${id}/fields/${points.id}`, { headers: H, data: { value: pts } }),
    );
  };
  await task(alpha, 'J13 ship A', ship, 3);
  await task(alpha, 'J13 plan A', plan, 5);
  await task(beta, 'J13 ship B', ship, 8);

  // 1. the list, filtered by the field; a chip says so and removes it
  await page.goto(`/projects/${alpha}/list`);
  await expect(page.getByRole('listitem', { name: 'J13 plan A' })).toBeVisible();
  await page.getByRole('button', { name: /^Filter/ }).click();
  await page.locator('summary', { hasText: 'J13 Stage' }).click();
  await page
    .getByRole('group', { name: 'Filter by J13 Stage' })
    .getByRole('button', { name: 'Ship' })
    .click();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('listitem', { name: 'J13 plan A' })).toHaveCount(0);
  await expect(page.getByRole('listitem', { name: 'J13 ship A' })).toBeVisible();
  await expect(page.getByRole('list', { name: 'Custom field filters' })).toContainText('J13 Stage: Ship');

  // 2. the board follows the same filter
  await page
    .getByRole('navigation', { name: 'Project views' })
    .getByRole('link', { name: 'Board', exact: true })
    .click();
  await expect(page.getByText('J13 ship A')).toBeVisible();
  await expect(page.getByText('J13 plan A')).toHaveCount(0);

  // 3. search finds the field's tasks across both projects, without any words
  await page.goto(`/search?field=${stage.id}:any:${ship}`);
  await expect(page.getByRole('button', { name: /J13 ship A/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /J13 ship B/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /J13 plan A/ })).toHaveCount(0);

  // 4. a workspace chart: total points of the Ship tasks, across both projects
  const board = (
    await json(
      await api.post('/api/v1/dashboards', { headers: H, data: { name: 'J13 report', starter: false } }),
    )
  ).data;
  await page.goto(`/dashboards/${board.id}`);
  await page.getByRole('button', { name: 'Add chart' }).click();
  const editor = page.getByRole('dialog', { name: 'Add a chart' });
  await editor.getByRole('button', { name: /^Number/ }).click();
  await editor.getByRole('radio', { name: 'Total of a field' }).click();
  await editor.getByLabel('Number field').selectOption({ label: 'J13 Points' });
  await editor.locator('summary', { hasText: 'J13 Stage' }).click();
  await editor
    .getByRole('group', { name: 'Filter by J13 Stage' })
    .getByRole('button', { name: 'Ship' })
    .click();
  await editor.getByLabel('Title').fill('J13 shipping points');
  await editor.getByRole('button', { name: 'Add chart' }).click();
  await settled(page);
  const card = page.getByRole('region', { name: 'J13 shipping points' });
  await expect(card).toBeVisible();
  await expect(card.locator('button[title]')).toHaveText(/^11\s*total J13 Points$/);
  // what it counts, in words, on hover: across projects, where the field is Ship
  await expect(card.locator('button[title]')).toHaveAttribute('title', /where J13 Stage: Ship/);
});
