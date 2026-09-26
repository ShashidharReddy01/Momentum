import { expect, test } from '@playwright/test';
import { dragOnto, isoToday, login, settled } from './helpers';

/** J4: Board — drag a card between columns. Calendar — drag an undated task onto a day to
 * schedule it. Both against the seeded "Website Revamp" project (same one J2/J3 use — reading
 * a disjoint task/column from theirs, so the three journeys don't step on each other). */
test('J4: board card drag between columns, calendar drag to reschedule', async ({ page }) => {
  await login(page);
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Website Revamp' }).click();

  // Board: drag the first card in Backlog into In progress
  await page.getByRole('navigation', { name: 'Project views' }).getByRole('link', { name: 'Board' }).click();
  const backlog = page.getByRole('list', { name: 'Cards in Backlog' });
  const inProgress = page.getByRole('list', { name: 'Cards in In progress' });
  const card = backlog.getByRole('listitem').first();
  const title = (await card.getAttribute('aria-label'))!;
  // drop onto an existing card in the target column (a stable dnd-kit drop target — the column's
  // otherwise-empty list area isn't itself droppable, only cards and its "column-end" zone are)
  await dragOnto(page, card, inProgress.getByRole('listitem').first());
  await settled(page);
  await expect(inProgress.getByRole('listitem', { name: title })).toBeVisible();
  await expect(backlog.getByRole('listitem', { name: title })).not.toBeVisible();

  // it persists after reload
  await page.reload();
  await expect(
    page.getByRole('list', { name: 'Cards in In progress' }).getByRole('listitem', { name: title }),
  ).toBeVisible();

  // Calendar: quick-add an undated task (via a day cell's "+", then clear its date to land it in
  // the tray), then drag it from the "No date" tray onto today — the AC's "drag to reschedule".
  await page
    .getByRole('navigation', { name: 'Project views' })
    .getByRole('link', { name: 'Calendar' })
    .click();
  const todayIso = isoToday();
  const todayCell = page.locator(`[role="gridcell"][data-date="${todayIso}"]`);
  const taskTitle = 'J4 calendar reschedule check';
  await todayCell.getByRole('button', { name: 'Add task' }).click();
  await page.keyboard.type(taskTitle);
  await page.keyboard.press('Enter');
  await settled(page);
  const trayDrop = page.getByRole('complementary', { name: 'No date' }); // the tray's own droppable ref
  const trayList = page.getByRole('list', { name: 'Tasks with no date' });
  const onToday = page.getByRole('list', { name: `Tasks on ${todayIso}` });

  // drag it into the tray (clears the date), then back onto today (sets it again)
  await dragOnto(page, onToday.getByRole('listitem', { name: taskTitle }), trayDrop);
  await settled(page);
  await expect(trayList.getByRole('listitem', { name: taskTitle })).toBeVisible();

  await dragOnto(page, trayList.getByRole('listitem', { name: taskTitle }), todayCell);
  await settled(page);
  await expect(onToday.getByRole('listitem', { name: taskTitle })).toBeVisible();
  await expect(trayList.getByRole('listitem', { name: taskTitle })).not.toBeVisible();
});
