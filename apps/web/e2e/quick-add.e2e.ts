import { expect, test } from '@playwright/test';
import { login, row } from './helpers';

/** Quick add (Q): lands in the project on screen, assigned to me, dated, and undoable. */
test('quick add from a project page', async ({ page }) => {
  await login(page);
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Website Revamp' }).click();
  await expect(page.locator('[data-task-id]').first()).toBeVisible();
  await page.keyboard.press('q');
  const dialog = page.getByRole('dialog', { name: 'New task' });
  await expect(dialog.getByLabel('Project')).toHaveValue(/.+/);
  await expect(dialog.getByLabel('Project').locator('option:checked')).toHaveText('Website Revamp');
  await dialog.getByRole('textbox', { name: 'Task name' }).fill('Renew the domain');
  await dialog.getByRole('button', { name: 'Set due date' }).click();
  await page.getByRole('textbox', { name: 'Due date' }).fill('tomorrow');
  await page.getByRole('textbox', { name: 'Due date' }).press('Enter');
  await dialog.getByRole('button', { name: 'Add task' }).click();
  const added = row(page, 'Renew the domain');
  await expect(added).toBeVisible();
  await expect(added.getByRole('button', { name: /Assignee: Ravi Kumar/ })).toBeVisible();
  await expect(added.getByRole('button', { name: /^Due / })).toBeVisible();
  // one undo removes it
  await page
    .locator('[data-sonner-toast]')
    .filter({ hasText: 'Task added to Website Revamp' })
    .getByRole('button', { name: 'Undo' })
    .click();
  await expect(added).toHaveCount(0);
  await page.reload();
  await expect(page.locator('[data-task-id]').first()).toBeVisible();
  await expect(row(page, 'Renew the domain')).toHaveCount(0);
});
