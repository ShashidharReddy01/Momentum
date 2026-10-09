import { expect, test } from '@playwright/test';
import { login } from './helpers';

/**
 * J24 part 1 (Phase 7.6 S76-07): the agents directory → an agent's page → its settings saved and
 * undone → its health. Uses the synthetic Echo test pack (loaded only with MOMENTUM_TEST_PACKS),
 * so nothing here depends on a real model.
 */
test('J24: find an agent by what it does, change its settings, undo, see its health', async ({ page }) => {
  await login(page, 'Avery Admin');
  await page.goto('/agents');
  const install = page.getByRole('button', { name: 'Install starter agents' });
  const directory = page.getByRole('list', { name: 'Agents' });
  await expect(install.or(directory)).toBeVisible();
  if (await install.isVisible()) await install.click();
  await expect(directory).toBeVisible();

  // search reads like a question; the filler words are dropped
  await page.getByRole('searchbox', { name: 'Search agents' }).fill('who can echo the input?');
  const echo = directory.getByRole('link', { name: /^Echo/ });
  await expect(echo).toBeVisible();
  await expect(directory.getByRole('listitem')).toHaveCount(1);
  await expect(echo.getByText('Echo the input')).toBeVisible();
  await expect(echo.getByText('Internal data')).toBeVisible();
  await echo.click();

  // Overview: what it may do, in plain English
  await expect(page.getByRole('heading', { name: 'Echo', level: 1 })).toBeVisible();
  const may = page.getByRole('region', { name: 'What it may do' });
  await expect(may.getByText('comment on the task')).toBeVisible();
  await expect(may.getByText('create echo bill records')).toBeVisible();

  // Settings: save the workspace's threshold, then undo it
  await page.getByRole('tab', { name: 'Settings' }).click();
  const form = page.getByRole('form', { name: 'Settings form' });
  const threshold = form.getByRole('spinbutton', { name: 'Threshold' });
  await expect(threshold).toBeVisible();
  const before = await threshold.inputValue();
  const next = before === '7' ? '8' : '7';
  await threshold.fill(next);
  await form.getByRole('button', { name: 'Save' }).click();
  await expect(page.getByText('Settings saved')).toBeVisible();
  await expect(threshold).toHaveValue(next);
  await page.getByRole('button', { name: 'Undo' }).click();
  await expect(threshold).toHaveValue(before);

  // Health renders (an honest empty state until it has done work)
  await page.getByRole('tab', { name: 'Health' }).click();
  await expect(
    page.getByRole('list', { name: 'Health numbers' }).or(page.getByText('No jobs yet')),
  ).toBeVisible();
});
