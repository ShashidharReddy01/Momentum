import { expect, test } from '@playwright/test';
import { login, row, settled } from './helpers';

/**
 * J2 (full, Phase 2): open the task pane → edit the description → add a subtask → comment with
 * an @mention → the mention arrives in the other user's inbox. The Phase 1 version of this test
 * stopped at "becomes a follower and sees the comment" (S2.5's notifications/inbox didn't exist
 * yet); this now also checks the inbox delivery the roadmap's J2 actually calls for.
 */
test('J2: pane description, subtask and @mention comment', async ({ page }) => {
  await login(page);
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Website Revamp' }).click();
  const title = (await page
    .getByRole('list', { name: 'Tasks in Review' })
    .locator('[data-task-id]')
    .first()
    .getAttribute('aria-label'))!;
  await row(page, title)
    .getByRole('button', { name: `Open details for ${title}` })
    .click();
  const pane = page.getByRole('complementary', { name: 'Task details' });
  await expect(pane.getByRole('textbox', { name: 'Task name' })).toHaveValue(title);
  await expect(page).toHaveURL(/task=/);
  const taskId = new URL(page.url()).searchParams.get('task')!;

  // description autosaves
  const description = pane.getByRole('textbox', { name: 'Task description' });
  const saved = page.waitForResponse(
    (r) => r.request().method() === 'PATCH' && r.url().includes(`/api/v1/tasks/${taskId}`) && r.ok(),
  );
  await description.click();
  await page.keyboard.type('Checklist for the staging rollout.');
  await saved;

  // subtask
  await pane.getByRole('button', { name: 'Add subtask' }).click();
  await page.keyboard.type('Smoke-test the checkout');
  await page.keyboard.press('Enter');
  await page.keyboard.press('Escape');
  await expect(
    pane.getByRole('list', { name: 'Subtasks' }).getByText('Smoke-test the checkout'),
  ).toBeVisible();

  // comment with an @mention
  const comment = pane.locator('[aria-label="New comment"]');
  await comment.click();
  await page.keyboard.type('Can you check this, @Mei');
  await page.getByRole('option', { name: /Mei Chen/ }).click();
  await page.keyboard.press('ControlOrMeta+Enter');
  await expect(pane.getByRole('list', { name: 'Feed' }).getByText('@Mei Chen')).toBeVisible();
  await settled(page);

  // all of it survives a reload
  await page.reload();
  const again = page.getByRole('complementary', { name: 'Task details' });
  await expect(again.getByRole('textbox', { name: 'Task description' })).toContainText(
    'Checklist for the staging rollout.',
  );
  await expect(
    again.getByRole('list', { name: 'Subtasks' }).getByText('Smoke-test the checkout'),
  ).toBeVisible();
  await expect(again.getByRole('list', { name: 'Feed' }).getByText('@Mei Chen')).toBeVisible();

  // Mei now follows the task and sees the comment
  await page.context().clearCookies();
  await login(page, 'Mei Chen');
  await page.goto(`/task/${taskId}`);
  const full = page.getByRole('complementary', { name: 'Task details' });
  await expect(full.getByRole('list', { name: 'Feed' }).getByText('Can you check this')).toBeVisible();
  await expect(full.getByRole('button', { name: 'Stop following' })).toBeVisible();

  // and the mention shows up in Mei's Inbox
  await page.goto('/inbox');
  await expect(
    page.getByRole('list', { name: 'Notifications' }).getByLabel(`You were mentioned in "${title}"`),
  ).toBeVisible();
});
