import { expect, test } from '@playwright/test';
import { login } from './helpers';

/**
 * J18 (Phase 7.5, spec §11.4): reports. From a project's menu, "Create report" → a customer status
 * update (Word) with Mo's summary: the outline previews it, the job makes it, the file appears in
 * the project's Files with the AI-drafted badge, and undo deletes it.
 */
test('J18: a customer report from the project menu, in Files, then undone', async ({ page }) => {
  await login(page);
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Website Revamp' }).click();
  await expect(page.getByRole('list', { name: 'Tasks in Review' })).toBeVisible();

  await page.getByRole('button', { name: 'Project actions' }).click();
  await page.getByRole('menuitem', { name: /Create report/ }).click();
  const dialog = page.getByRole('dialog', { name: /Create a report: Website Revamp/ });
  await dialog.getByRole('button', { name: /Customer update/ }).click();
  const outline = dialog.getByRole('region', { name: 'Report outline' });
  await expect(outline.getByText('Website Revamp: progress update')).toBeVisible();
  await expect(outline.getByText(/AI-drafted summary/)).toBeVisible();
  await expect(dialog.getByRole('radio', { name: 'Word' })).toHaveAttribute('aria-checked', 'true');
  await dialog.getByRole('button', { name: 'Create report' }).click();

  // the job runs on the server's worker; the dialog then says it's ready
  const ready = dialog.getByRole('status');
  await expect(ready).toContainText('Report ready', { timeout: 30_000 });
  const filename = (await ready.locator('span.font-medium').textContent())!.trim();
  expect(filename).toMatch(/^Website Revamp - Customer update .+\.docx$/);
  await dialog.getByRole('button', { name: 'Done' }).click();

  // in Files, marked as a report written partly by Mo
  await page.getByRole('navigation', { name: 'Project views' }).getByRole('link', { name: 'Files' }).click();
  const row = page.getByRole('row', { name: new RegExp(filename.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) });
  await expect(row).toBeVisible();
  await expect(row.getByText('Report', { exact: true })).toBeVisible();
  await expect(row.getByText('AI-drafted')).toBeVisible();

  // undo (⌘Z / Ctrl+Z outside a text field) deletes it
  await page.locator('body').click({ position: { x: 5, y: 5 } });
  await page.keyboard.press('ControlOrMeta+z');
  await expect(row).toBeHidden();

  // back to the list, so later journeys open the project on its list
  await page.getByRole('navigation', { name: 'Project views' }).getByRole('link', { name: 'List' }).click();
  await expect(page.getByRole('list', { name: 'Tasks in Review' })).toBeVisible();
});
