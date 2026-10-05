import { expect, test } from '@playwright/test';
import { login } from './helpers';

/** J6 (S7.4.2 acceptance): import from Asana through the wizard, against the recorded synthetic
 * workspace (`tools/e2e/asana_fixture_server.py`, the same data `test_asana_import.py` imports):
 * a dry run reports what would come over and changes nothing, the import brings it all in (in
 * steps, the token sent with each), and the imported project is browsable with its comments,
 * files and custom fields. */
test('J6: Asana import wizard → dry run → import → a browsable project with comments and fields', async ({
  page,
}) => {
  await login(page, 'Avery Admin');
  await page.goto('/settings/import/asana');
  await expect(page.getByRole('heading', { name: 'Import from Asana' })).toBeVisible();

  await page.getByLabel('Personal Access Token').fill('fixture-pat-not-real');
  await page.getByRole('button', { name: 'Connect' }).click();
  await page.getByLabel('Asana team').selectOption({ label: 'Product' });
  await expect(page.getByRole('group', { name: /Projects \(3 of 3\)/ })).toBeVisible();
  await page.getByLabel('Team name in Momentum').fill('J6 Imported Team');

  await page.getByRole('button', { name: 'Dry run' }).click();
  await expect(page.getByText('Dry run finished: nothing was changed')).toBeVisible({ timeout: 30_000 });
  const would = page.getByLabel('Would import');
  await expect(would.getByText('Tasks', { exact: true }).locator('xpath=following-sibling::dd')).toHaveText(
    '5',
  );
  await expect(page.getByText('1 × formula fields imported as a text snapshot')).toBeVisible();

  await page.getByRole('button', { name: 'Import', exact: true }).click();
  await expect(page.getByText('Import finished')).toBeVisible({ timeout: 60_000 });
  const done = page.getByLabel('Imported');
  for (const [label, n] of [
    ['Projects', '3'],
    ['Tasks', '5'],
    ['Subtasks', '2'],
    ['Comments', '2'],
    ['Files', '1'],
    ['Status updates', '2'],
  ] as const) {
    await expect(done.getByText(label, { exact: true }).locator('xpath=following-sibling::dd')).toHaveText(n);
  }

  // the imported project is real: tasks placed, a comment kept with its author, a file, a field
  await page
    .getByRole('navigation', { name: 'Main' })
    .getByRole('link', { name: 'J6 Imported Team' })
    .click();
  await page.getByRole('link', { name: 'Imported Project' }).first().click();
  await expect(page.getByRole('button', { name: /^Project name: Imported Project/ })).toBeVisible();
  await page
    .getByRole('navigation', { name: 'Project views' })
    .getByRole('link', { name: 'List', exact: true })
    .click();
  const release = page.locator('[data-task-id][aria-label="Ship the release"]');
  await expect(release).toBeVisible();
  await expect(release).toContainText('Ship'); // its Stage field
  await release.getByRole('button', { name: 'Open details for Ship the release' }).click();
  const pane = page.getByRole('complementary', { name: 'Task details' });
  await expect(pane.getByText('Looks good to me')).toBeVisible();
  await expect(pane.getByText('spec.txt')).toBeVisible();
  await expect(pane.getByText(/From Asana, by Ex Colleague/)).toBeVisible();
});
