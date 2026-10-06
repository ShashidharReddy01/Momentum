import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { login, row } from './helpers';

/**
 * J14 (S7.5.3): accessibility as a standing gate. axe (WCAG 2.2 A/AA) finds no serious or
 * critical violation on the key pages, in light and dark, including the admin and Asana pages
 * built after the Phase 6.5 audit; and the core list → pane → back loop works from the keyboard
 * alone, with focus returning to the task's row when the pane closes.
 */
const PAGES: [string, string][] = [
  ['Home', '/'],
  ['My tasks', '/my-tasks'],
  ['Inbox', '/inbox'],
  ['Search', '/search?q=design'],
  ['Goals', '/goals'],
  ['Workload', '/workload'],
  ['Dashboards', '/dashboards'],
  ['Agents', '/agents'],
  ['Members', '/settings/members'],
  ['Background jobs', '/settings/jobs'],
  ['Audit trail', '/settings/audit'],
  ['Asana import', '/settings/import/asana'],
  ['Coming from Asana', '/welcome/asana'],
];

async function serious(page: Page) {
  await page.waitForLoadState('networkidle');
  const { violations } = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
    .analyze();
  return violations
    .filter((v) => v.impact === 'serious' || v.impact === 'critical')
    .map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`);
}

for (const scheme of ['light', 'dark'] as const) {
  test(`J14: no serious axe violations (${scheme})`, async ({ page }) => {
    test.setTimeout(120_000);
    await page.emulateMedia({ colorScheme: scheme, reducedMotion: 'reduce' });
    await login(page, 'Avery Admin');
    const found: string[] = [];
    for (const [name, path] of PAGES) {
      await page.goto(path);
      found.push(...(await serious(page)).map((v) => `${name}: ${v}`));
    }
    await page.goto('/');
    await page
      .getByRole('navigation', { name: 'Main' })
      .getByRole('link', { name: 'Website Revamp' })
      .click();
    await expect(page.getByRole('list', { name: 'Tasks in Review' })).toBeVisible();
    found.push(...(await serious(page)).map((v) => `Project list: ${v}`));
    const first = page.getByRole('list', { name: 'Tasks in Review' }).locator('[data-task-id]').first();
    const title = (await first.getAttribute('aria-label'))!;
    await row(page, title)
      .getByRole('button', { name: `Open details for ${title}` })
      .click();
    await expect(page.getByRole('complementary', { name: 'Task details' })).toBeVisible();
    found.push(...(await serious(page)).map((v) => `Task pane: ${v}`));
    expect(found).toEqual([]);
  });
}

test('J14: list → pane → back to the row, from the keyboard', async ({ page }) => {
  await login(page);
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Website Revamp' }).click();
  const first = page.getByRole('list', { name: 'Tasks in Review' }).locator('[data-task-id]').first();
  const title = (await first.getAttribute('aria-label'))!;
  const taskRow = row(page, title);

  await taskRow.focus();
  await page.keyboard.press(' '); // Space opens the task, focus stays on the list
  const pane = page.getByRole('complementary', { name: 'Task details' });
  await expect(pane.getByRole('textbox', { name: 'Task name' })).toHaveValue(title);
  await expect(taskRow).toBeFocused();

  // into the pane, out of the field, then the pane closes and focus is back on the row
  await pane.getByRole('textbox', { name: 'Task name' }).focus();
  await page.keyboard.press('Escape');
  // the first Escape leaves the field; wait for it, or under load the second lands in the field
  await expect(pane.getByRole('textbox', { name: 'Task name' })).not.toBeFocused();
  await page.keyboard.press('Escape');
  await expect(pane).toBeHidden();
  await expect(taskRow).toBeFocused();
});
