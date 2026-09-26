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

/** Pointer drag of one element onto another (Board columns, Calendar day cells — anything using
 * `@dnd-kit`'s `useDraggable`/`useDroppable`), same mouse-event technique as `dragRow`, just not
 * tied to "before/after another row" — it drops onto `to`'s own center (plus an optional offset). */
export async function dragOnto(
  page: Page,
  from: Locator,
  to: Locator,
  offset: { x: number; y: number } = { x: 0, y: 0 },
) {
  await from.scrollIntoViewIfNeeded();
  const a = (await from.boundingBox())!;
  await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2);
  await page.mouse.down();
  await page.mouse.move(a.x + a.width / 2 + 10, a.y + a.height / 2 + 8, { steps: 4 });
  await to.scrollIntoViewIfNeeded();
  const b = (await to.boundingBox())!;
  await page.mouse.move(b.x + b.width / 2 + offset.x, b.y + b.height / 2 + offset.y, { steps: 12 });
  await page.waitForTimeout(150);
  await page.mouse.up();
}

/** Today's date as `YYYY-MM-DD` in the local timezone (not `toISOString`, which is UTC and can
 * land on the wrong calendar day near midnight). */
export function isoToday(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}
