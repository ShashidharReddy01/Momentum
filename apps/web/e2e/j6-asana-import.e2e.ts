import { expect, test } from '@playwright/test';
import { login } from './helpers';

/** J6: Asana import against a recorded fixture API (`tools/e2e/asana_fixture_server.py`, the
 * exact same synthetic workspace `test_asana_import.py`'s `FakeAsanaClient` uses) → the imported
 * team/project/tasks show up with the expected counts. */
test('J6: import from Asana (recorded fixture), correct counts and a browsable project', async ({ page }) => {
  await login(page, 'Avery Admin'); // Action.TEAM_CREATE requires an admin or member; admin is seeded
  await page.goto('/settings/import/asana');
  await expect(page.getByRole('heading', { name: 'Import from Asana' })).toBeVisible();

  await page.getByLabel('Personal Access Token').fill('fixture-pat-not-real');
  await page.getByLabel('Asana workspace gid').fill('ws1');
  await page.getByLabel('Asana team gid').fill('team1');
  await page.getByLabel('Team name in Momentum').fill('J6 Imported Team');
  await page.getByRole('button', { name: 'Run import' }).click();

  await expect(page.getByText('Import finished')).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText('teams: 1')).toBeVisible();
  await expect(page.getByText('projects: 1')).toBeVisible();
  await expect(page.getByText('sections: 2')).toBeVisible();
  await expect(page.getByText('tasks: 2')).toBeVisible();
  await expect(page.getByText('subtasks: 1')).toBeVisible();
  await expect(page.getByText('tags: 1')).toBeVisible();
  await expect(page.getByText('users_matched: 1')).toBeVisible();
  await expect(page.getByText('users_unmatched: 1')).toBeVisible();

  // the imported project is real and browsable, with its tasks correctly placed
  await page
    .getByRole('navigation', { name: 'Main' })
    .getByRole('link', { name: 'J6 Imported Team' })
    .click();
  await page.getByRole('link', { name: 'Imported Project' }).click();
  await expect(page.getByRole('button', { name: /^Project name: Imported Project/ })).toBeVisible();
  await expect(page.locator('[data-task-id][aria-label="Ship the release"]')).toBeVisible();
  // "Kickoff milestone" imports completed — hidden by default, same as every other list view
  await expect(page.locator('[data-task-id][aria-label="Kickoff milestone"]')).not.toBeVisible();
});
