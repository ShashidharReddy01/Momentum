import { expect, test } from '@playwright/test';
import { login, row } from './helpers';

/**
 * J7 (Phase 3): ⌘K "assign all overdue tasks in Website Revamp to Ana" → Mo previews the change →
 * apply → the tasks are Ana's → undo puts them back. Real API + Postgres; the LLM runs in mock
 * mode (multi-step fixture in `ai/evals/fixtures/mock_responses/command.yaml`: search, then a
 * bulk update of exactly what the search returned). Journey-scoped data: the overdue task this
 * journey checks is created here (via smart quick add), not taken from the seed.
 */
test('J7: natural-language command with preview, apply and undo', async ({ page }) => {
  await login(page);
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Website Revamp' }).click();
  await expect(page.locator('[data-task-id]').first()).toBeVisible();

  // an overdue task of our own, unassigned (smart quick add reads "yesterday")
  await page.keyboard.press('q');
  const dialog = page.getByRole('dialog', { name: 'New task' });
  await dialog.getByRole('textbox', { name: 'Task name' }).fill('J7 overdue check yesterday');
  await expect(dialog.getByRole('status', { name: 'Understood from the name' })).toContainText(
    'J7 overdue check',
  );
  await dialog.getByRole('button', { name: 'Assignee: Me' }).click();
  await page.getByRole('option', { name: /Unassign/ }).click();
  await dialog.getByRole('button', { name: 'Add task' }).click();
  const mine = row(page, 'J7 overdue check');
  await expect(mine).toBeVisible();
  await expect(mine.getByRole('button', { name: /Assignee: Ana Souza/ })).toHaveCount(0);

  // ⌘K → Ask Mo to do this
  await page.keyboard.press('Control+k');
  const palette = page.getByRole('dialog', { name: 'Command palette' });
  await palette.getByRole('combobox').fill('assign all overdue tasks in Website Revamp to Ana');
  await palette.getByRole('option', { name: /Ask Mo to do this/ }).click();

  const panel = page.getByRole('complementary', { name: 'Ask Mo' });
  await expect(panel.getByText('Searched tasks · Previewed bulk update tasks')).toBeVisible();
  const card = panel.getByRole('region', { name: 'Mo suggests (AI)' });
  await expect(card).toBeVisible();
  await expect(card.getByRole('list', { name: 'Proposed changes' })).toContainText('J7 overdue check');
  await expect(card).toContainText('Assignee: — → Ana Souza');

  // nothing changed before applying
  await expect(mine.getByRole('button', { name: /Assignee: Ana Souza/ })).toHaveCount(0);
  await card.getByRole('button', { name: 'Apply' }).click();
  const confirm = page.getByRole('dialog', { name: /^Apply \d+ changes?\?$/ });
  if (await confirm.isVisible().catch(() => false)) {
    await confirm.getByRole('button', { name: 'Yes, apply' }).click(); // >25 targets: high risk
  }
  await expect(card.getByText('Applied')).toBeVisible();
  await expect(mine.getByRole('button', { name: /Assignee: Ana Souza/ })).toBeVisible();

  // one undo reverses the whole action
  await page
    .locator('[data-sonner-toast]')
    .filter({ hasText: /^Applied:/ })
    .getByRole('button', { name: 'Undo' })
    .click();
  await expect(card.getByText('Undone')).toBeVisible();
  await expect(mine.getByRole('button', { name: /Assignee: Ana Souza/ })).toHaveCount(0);
  await page.reload();
  await expect(row(page, 'J7 overdue check')).toBeVisible();
  await expect(
    row(page, 'J7 overdue check').getByRole('button', { name: /Assignee: Ana Souza/ }),
  ).toHaveCount(0);
});
