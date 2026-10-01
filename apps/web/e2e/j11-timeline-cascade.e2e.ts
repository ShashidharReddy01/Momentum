import { expect, test, type APIRequestContext } from '@playwright/test';
import { login, settled } from './helpers';

/**
 * J11 (Phase 6): on the timeline, moving a task that another task waits on shows the cascade
 * before anything is saved, "Move all" moves both in one change, and one Undo puts both back.
 * The two tasks and their dependency are made through the API (the setup isn't what's being
 * tested); the move is a keyboard nudge on the bar (Shift+→ = one week), which goes through the
 * same preview → confirm path as a drag and is steadier than pointer drags in a headless run.
 */
const H = { 'X-Requested-With': 'momentum' };
const iso = (days: number) => {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

async function task(api: APIRequestContext, pid: string, title: string, start: number, due: number) {
  const made = await api.post(`/api/v1/projects/${pid}/tasks`, { headers: H, data: { title } });
  expect(made.ok()).toBeTruthy();
  const id = (await made.json()).data.id as string;
  const r = await api.patch(`/api/v1/tasks/${id}`, {
    headers: H,
    data: { start_on: iso(start), due_on: iso(due) },
  });
  expect(r.ok()).toBeTruthy();
  return id;
}

async function dates(api: APIRequestContext, id: string) {
  const t = await (await api.get(`/api/v1/tasks/${id}`)).json();
  return [t.start_on, t.due_on];
}

test('J11: move a task with a dependent → cascade preview → apply → undo restores both', async ({ page }) => {
  await login(page);
  const api = page.request;
  // its own project: the journeys share one database, and Website Revamp's sections are what
  // J3, J4 and J9 drag and count
  const teams = (await (await api.get('/api/v1/teams')).json()).data as { id: string; name: string }[];
  const made = await api.post('/api/v1/projects', {
    headers: H,
    data: { team_id: teams.find((t) => t.name === 'Product')!.id, name: 'J11 Timeline' },
  });
  expect(made.ok()).toBeTruthy();
  const pid = (await made.json()).data.id as string;
  const blocker = await task(api, pid, 'J11 blocker', 1, 3);
  const dependent = await task(api, pid, 'J11 dependent', 4, 6);
  const dep = await api.post(`/api/v1/tasks/${dependent}/dependencies`, {
    headers: H,
    data: { depends_on_id: blocker },
  });
  expect(dep.ok()).toBeTruthy();

  await page.goto(`/projects/${pid}/timeline`);
  const bar = page.locator(`[data-bar="${blocker}"]`);
  await expect(bar).toBeVisible();
  await bar.focus();
  await page.keyboard.press('Shift+ArrowRight');

  // the cascade is previewed before anything is saved
  const dialog = page.getByRole('dialog', { name: /and 1 task that waits on it\?/ });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText('J11 dependent');
  expect(await dates(api, dependent)).toEqual([iso(4), iso(6)]);

  await dialog.getByRole('button', { name: 'Move all 2' }).click();
  await settled(page);
  await expect.poll(() => dates(api, blocker)).toEqual([iso(8), iso(10)]);
  // pushed only as far as it must: it starts the day its blocker is now due (same-day hand-off)
  expect(await dates(api, dependent)).toEqual([iso(10), iso(12)]);

  // one undo restores both
  await page.getByRole('button', { name: 'Undo' }).click();
  await expect.poll(() => dates(api, blocker)).toEqual([iso(1), iso(3)]);
  expect(await dates(api, dependent)).toEqual([iso(4), iso(6)]);
});
