import { expect, test } from '@playwright/test';
import { login, row, settled } from './helpers';

/** J5: two real browser tabs (separate contexts, so separate WS connections) — an edit in one
 * shows up live in the other, no reload. Uses a task created just for this journey (not one of
 * J2/J3/J4's) so there's no ordering dependency on what those left behind. */
test('J5: two browsers, live update with no reload', async ({ browser }) => {
  const ctxA = await browser.newContext();
  const ctxB = await browser.newContext();
  const a = await ctxA.newPage();
  const b = await ctxB.newPage();

  // J2/J3/J4 may have left Ravi's *remembered view* for this project on Board/Calendar (S2.2.3:
  // per-user, persisted server-side, not reset between journeys in the same run) — force List
  // explicitly rather than trusting the bare project link to land there.
  const openWebsiteRevampInList = async (page: typeof a) => {
    await page
      .getByRole('navigation', { name: 'Main' })
      .getByRole('link', { name: 'Website Revamp' })
      .click();
    await page.getByRole('navigation', { name: 'Project views' }).getByRole('link', { name: 'List' }).click();
  };

  await login(a, 'Ravi Kumar');
  await openWebsiteRevampInList(a);
  await a
    .getByRole('button', { name: /Add task/ })
    .first()
    .click();
  await a.keyboard.type('J5 realtime sync check');
  await a.keyboard.press('Enter');
  await a.keyboard.press('Escape');
  await expect(row(a, 'J5 realtime sync check')).toBeVisible();

  // Ana is on the Product team too (per seed.py), so she can see this project
  await login(b, 'Ana Souza');
  await openWebsiteRevampInList(b);
  await expect(row(b, 'J5 realtime sync check')).toBeVisible();

  // A renames the task — B sees the new title with no reload
  await row(a, 'J5 realtime sync check')
    .getByRole('button', { name: `Open details for J5 realtime sync check` })
    .click();
  const pane = a.getByRole('complementary', { name: 'Task details' });
  const nameField = pane.getByRole('textbox', { name: 'Task name' });
  await nameField.click();
  await nameField.fill('J5 realtime sync renamed');
  await nameField.press('Enter');
  await expect(row(b, 'J5 realtime sync renamed')).toBeVisible({ timeout: 5000 });

  // A completes it — B sees it drop out of the incomplete list with no reload
  await row(a, 'J5 realtime sync renamed').getByRole('checkbox').click();
  await settled(a);
  await expect(row(b, 'J5 realtime sync renamed')).not.toBeVisible({ timeout: 5000 });

  await ctxA.close();
  await ctxB.close();
});
