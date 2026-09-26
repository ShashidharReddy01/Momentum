import { expect, test } from '@playwright/test';
import { login, row, settled } from './helpers';

/** J1: dev login → create team → create project → add 3 tasks → assign → set due → complete one → undo. */
test('J1: from an empty team to done tasks, with undo', async ({ page }) => {
  await login(page);

  // create a team
  await page.getByRole('button', { name: 'Create' }).click();
  await page.getByRole('menuitem', { name: 'Team' }).click();
  await page.getByLabel('Name').fill('E2E Journeys');
  await page.getByRole('button', { name: 'Create team' }).click();
  await expect(page.getByRole('navigation', { name: 'Main' }).getByText('E2E Journeys')).toBeVisible();

  // create a project in it
  await page.getByRole('button', { name: 'Create' }).click();
  await page.getByRole('menuitem', { name: 'Project' }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Name').fill('Launch Checklist');
  await dialog.getByLabel('Team').selectOption({ label: 'E2E Journeys' });
  await dialog.getByRole('button', { name: 'Create project' }).click();
  await expect(page.getByRole('button', { name: /^Project name: Launch Checklist/ })).toBeVisible();

  // add three tasks, one after another from the keyboard
  await page
    .getByRole('button', { name: /Add task/ })
    .first()
    .click();
  for (const title of ['Draft the announcement', 'Book the venue', 'Order the swag']) {
    await page.keyboard.type(title);
    await page.keyboard.press('Enter');
  }
  await page.keyboard.press('Escape');
  for (const title of ['Draft the announcement', 'Book the venue', 'Order the swag'])
    await expect(row(page, title)).toBeVisible();

  // assign one to Ana, and give it a due date
  const venue = row(page, 'Book the venue');
  await venue.getByRole('button', { name: 'Assign' }).click();
  await page.getByPlaceholder('Assign to…').fill('Ana');
  await page.getByRole('option', { name: /Ana Souza/ }).click();
  await expect(venue.getByRole('button', { name: /Assignee: Ana Souza/ })).toBeVisible();
  await venue.getByRole('button', { name: 'Set due date' }).click();
  await page.getByRole('textbox', { name: 'Due date' }).fill('tomorrow');
  await page.getByRole('textbox', { name: 'Due date' }).press('Enter');
  await expect(venue.getByRole('button', { name: /^Due / })).toBeVisible();

  // complete one, then undo from the toast
  await row(page, 'Draft the announcement').getByRole('checkbox').click();
  await expect(page.getByText('Task completed')).toBeVisible();
  await settled(page);
  await page
    .locator('[data-sonner-toast]')
    .filter({ hasText: 'Task completed' })
    .getByRole('button', { name: 'Undo' })
    .click();
  await expect(row(page, 'Draft the announcement').getByRole('checkbox')).not.toBeChecked();

  // it all persisted
  await page.reload();
  await expect(row(page, 'Draft the announcement').getByRole('checkbox')).not.toBeChecked();
  await expect(
    row(page, 'Book the venue').getByRole('button', { name: /Assignee: Ana Souza/ }),
  ).toBeVisible();
  await expect(row(page, 'Book the venue').getByRole('button', { name: /^Due / })).toBeVisible();

  // and Ana sees it in her My Tasks
  await page.context().clearCookies();
  await login(page, 'Ana Souza');
  // the sidebar link (Home's "My priorities" widget also links to My Tasks, and its label depends
  // on how many open tasks the user has)
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'My Tasks' }).click();
  await expect(
    page.getByRole('list', { name: 'Tasks in Recently assigned' }).locator('[aria-label="Book the venue"]'),
  ).toBeVisible();
});
