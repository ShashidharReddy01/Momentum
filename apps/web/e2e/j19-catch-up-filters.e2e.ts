import { expect, test, type APIRequestContext } from '@playwright/test';
import { login } from './helpers';

const H = { 'X-Requested-With': 'momentum' };
const iso = (days: number) => {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

async function task(api: APIRequestContext, pid: string, title: string, data: object = {}) {
  const made = await api.post(`/api/v1/projects/${pid}/tasks`, { headers: H, data: { title, ...data } });
  expect(made.ok()).toBeTruthy();
  return (await made.json()).data.id as string;
}

/**
 * J19 parts 1-2 (Phase 7.5, spec §11.4): Catch me up and plain-English filters. Ravi looks at Home
 * and a project, Ana finishes four of its tasks, and Ravi's Home shows "While you were away"; the
 * project's "Catch me up" says what changed. Then on the project's list, "only my overdue work"
 * becomes chips that apply only on Apply, with the amber marker, and Clear puts the list back.
 */
test('J19: catch me up after someone else’s changes, then filter the list in plain English', async ({
  page,
  browser,
}) => {
  await login(page);
  const api = page.request;
  const teams = (await (await api.get('/api/v1/teams')).json()).data as { id: string; name: string }[];
  const made = await api.post('/api/v1/projects', {
    headers: H,
    data: { team_id: teams.find((t) => t.name === 'Product')!.id, name: 'J19 Catch-up' },
  });
  expect(made.ok()).toBeTruthy();
  const pid = (await made.json()).data.id as string;
  const me = (await (await api.get('/api/v1/me')).json()).user.id as string;
  const ids = [];
  for (const n of [1, 2, 3, 4]) ids.push(await task(api, pid, `J19 step ${n}`));
  await task(api, pid, 'J19 late and mine', { assignee_id: me, due_on: iso(-2) });

  // Ravi looks at Home, then the project, then Home again (each visit is written on leaving)
  await page.goto('/');
  await expect(page.getByRole('heading', { level: 1, name: /Good/ })).toBeVisible();
  await page.goto(`/projects/${pid}/list`); // a fresh load: Home's visit comes from the beacon below
  await api.put('/api/v1/visits', { headers: H, data: { scope: 'home' } });
  await expect(page.getByRole('list', { name: /Tasks in/ }).first()).toBeVisible();
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Home' }).click();
  await expect(page.getByRole('heading', { level: 1, name: /Good/ })).toBeVisible();

  // Ana finishes four tasks
  const ctxB = await browser.newContext();
  const ana = await ctxB.newPage();
  await login(ana, 'Ana Souza');
  for (const id of ids) {
    const r = await ana.request.post(`/api/v1/tasks/${id}/complete`, { headers: H });
    expect(r.ok()).toBeTruthy();
  }
  await ctxB.close();

  // Home: "While you were away", and Mo's catch-up
  await page.reload();
  const card = page.getByRole('region', { name: 'While you were away' });
  // at least Ana's four (earlier journeys may have left more since Ravi's last Home visit)
  await expect(card).toContainText(/\d+ changes since/);
  await card.getByRole('button', { name: 'Catch me up' }).click();
  const home = page.getByRole('dialog', { name: 'While you were away' });
  await expect(home.getByRole('list', { name: 'What changed' }).getByRole('listitem').first()).toBeVisible();
  await home.getByRole('button', { name: 'Done' }).click();

  // the project's own catch-up
  await page.goto(`/projects/${pid}/list`);
  await page.getByRole('button', { name: /Catch me up/ }).click();
  const proj = page.getByRole('dialog', { name: 'Catch me up: J19 Catch-up' });
  await expect(proj).toContainText('4 changes by others');
  await expect(proj.getByRole('list', { name: 'What changed' })).toBeVisible();
  await proj.getByRole('button', { name: 'Done' }).click();

  // plain-English filters on the list: chips first, Apply, the marker, Clear
  const box = page.getByRole('textbox', { name: 'Describe what to show' });
  await box.fill('Only my overdue work');
  await box.press('Enter');
  const chips = page.getByRole('group', { name: "Mo's filters" });
  await expect(chips.getByText('Assignee: me')).toBeVisible();
  await expect(chips.getByText('Overdue')).toBeVisible();
  await chips.getByRole('button', { name: 'Apply' }).click();
  await expect(page.getByText('Filtered with Mo')).toBeVisible();
  await expect(page.locator('[data-task-id][aria-label="J19 late and mine"]')).toBeVisible();
  await expect(page.locator('[data-task-id][aria-label="J19 step 1"]')).toHaveCount(0);
  await page.getByRole('button', { name: "Clear Mo's filters" }).click();
  await expect(page.getByText('Filtered with Mo')).toBeHidden();
});
