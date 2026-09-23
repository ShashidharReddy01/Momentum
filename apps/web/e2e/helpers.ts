import { expect, type Locator, type Page } from '@playwright/test';

/** Dev login as a seeded (synthetic) user and wait for Home. */
export async function login(page: Page, name = 'Ravi Kumar') {
  await page.goto('/');
  await page.getByRole('button', { name: new RegExp(name) }).click();
  await expect(
    page.getByRole('heading', { level: 1, name: /Good (morning|afternoon|evening)/ }),
  ).toBeVisible();
}

export const row = (page: Page, title: string): Locator =>
  page.locator(`[data-task-id][aria-label="${title}"]`);

/** Task titles in a section of the project list, top to bottom. */
export async function titlesIn(page: Page, section: string): Promise<string[]> {
  const list = page.getByRole('list', { name: `Tasks in ${section}` });
  return list
    .locator('[data-task-id]')
    .evaluateAll((els) => els.map((e) => e.getAttribute('aria-label') ?? ''));
}

/** Pointer drag of a row onto the top or bottom half of another row. */
export async function dragRow(page: Page, from: Locator, to: Locator, where: 'before' | 'after') {
  await from.scrollIntoViewIfNeeded();
  const a = (await from.boundingBox())!;
  await page.mouse.move(a.x + 60, a.y + a.height / 2);
  await page.mouse.down();
  await page.mouse.move(a.x + 70, a.y + a.height / 2 + 8, { steps: 4 });
  await to.scrollIntoViewIfNeeded();
  const b = (await to.boundingBox())!;
  await page.mouse.move(b.x + 80, where === 'before' ? b.y + 6 : b.y + b.height - 6, { steps: 12 });
  await page.waitForTimeout(150);
  await page.mouse.up();
}

/** Resolve after every in-flight request settles (optimistic UI → server). */
export async function settled(page: Page) {
  await page.waitForLoadState('networkidle');
}
