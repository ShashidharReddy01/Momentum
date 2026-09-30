import { expect, test } from '@playwright/test';
import { login, settled } from './helpers';

/**
 * J12 (Phase 6): ask for a chart in words on a project's Dashboard tab → Mo's preview (mock
 * fixtures: `ai/evals/fixtures/mock_responses/chart.yaml`) → add it → it's still there after a
 * reload, marked as drafted by Mo, and its number is the server's count.
 */
test('J12: ask for a chart → preview → add to a project dashboard → it shows on reload', async ({ page }) => {
  await login(page);
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Website Revamp' }).click();
  await page
    .getByRole('navigation', { name: 'Project views' })
    .getByRole('link', { name: 'Dashboard' })
    .click();
  await expect(page.getByText(/The starter dashboard, with live numbers/)).toBeVisible();

  await page.getByRole('button', { name: 'Ask for a chart' }).click();
  const dialog = page.getByRole('dialog', { name: 'Ask for a chart' });
  await dialog.getByLabel('What do you want to see?').fill('How many tasks are blocked?');
  await dialog.getByRole('button', { name: /Ask$/ }).click();
  await expect(dialog.getByRole('region', { name: 'Mo made this chart (AI)' })).toBeVisible();
  const preview = dialog.getByRole('region', { name: 'Blocked' });
  await expect(preview).toBeVisible();
  const number = preview.locator('button[title]');
  await expect(number).toHaveText(/\d/);
  const counted = /\d+/.exec(await number.innerText())![0];

  await dialog.getByRole('button', { name: 'Add to dashboard' }).click();
  await settled(page);
  const card = page.getByRole('region', { name: 'Blocked' });
  await expect(card).toBeVisible();
  // the starter dashboard was saved as this project's own (starter charts + the new one)
  await expect(page.getByText(/The starter dashboard, with live numbers/)).toHaveCount(0);

  await page.reload();
  await expect(card).toBeVisible();
  await expect(
    card.getByRole('img', { name: 'Drafted by Mo from: How many tasks are blocked?' }),
  ).toBeVisible();
  await expect(card.locator('button[title]')).toContainText(counted);
});
