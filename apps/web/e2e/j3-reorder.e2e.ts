import { expect, test } from '@playwright/test';
import { dragRow, login, row, settled, titlesIn } from './helpers';

/** J3: reorder tasks by drag within and across sections; the order persists after reload. */
test('J3: drag to reorder within and across sections, persisted', async ({ page }) => {
  await login(page);
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Website Revamp' }).click();
  await expect(page.getByRole('button', { name: /^Project name: Website Revamp/ })).toBeVisible();
  const backlog = await titlesIn(page, 'Backlog');
  const progress = await titlesIn(page, 'In progress');
  expect(backlog.length).toBeGreaterThanOrEqual(3);
  const [first, second, third] = backlog as [string, string, string];

  // within a section: move the first task below the third
  await dragRow(page, row(page, first), row(page, third), 'after');
  await expect.poll(() => titlesIn(page, 'Backlog')).toEqual([second, third, first, ...backlog.slice(3)]);

  // across sections: move the second task to the top of "In progress"
  await dragRow(page, row(page, second), row(page, progress[0]!), 'before');
  await expect.poll(() => titlesIn(page, 'In progress')).toEqual([second, ...progress]);
  await expect.poll(() => titlesIn(page, 'Backlog')).toEqual([third, first, ...backlog.slice(3)]);
  await expect(page.getByText('Moved to In progress')).toBeVisible();

  // keyboard path: ⌘↑ moves the focused task back up
  await row(page, first).focus();
  await page.keyboard.press('ControlOrMeta+ArrowUp');
  await expect.poll(() => titlesIn(page, 'Backlog')).toEqual([first, third, ...backlog.slice(3)]);

  await settled(page);
  await page.reload();
  await expect.poll(() => titlesIn(page, 'Backlog')).toEqual([first, third, ...backlog.slice(3)]);
  await expect.poll(() => titlesIn(page, 'In progress')).toEqual([second, ...progress]);
});
