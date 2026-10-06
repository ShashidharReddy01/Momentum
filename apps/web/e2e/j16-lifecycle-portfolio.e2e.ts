import { expect, test, type Locator, type Page } from '@playwright/test';
import { login } from './helpers';

/**
 * J16 (Phase 7.5, spec §11.4): a lifecycle portfolio. Create a rule portfolio from the Customer
 * onboarding template (seeded by `seed --onboarding --small`), set the stage field and a gate,
 * drag a card from Discovery to Contracts (the gate's checklist, then Move anyway), edit a
 * Contract value in the table, save a personal view, and see the timeline.
 */

async function dragTo(page: Page, from: Locator, to: Locator) {
  await from.scrollIntoViewIfNeeded();
  const a = (await from.boundingBox())!;
  const b = (await to.boundingBox())!;
  // grab the card below its title link (pressing the link would follow it)
  const x = a.x + a.width - 24;
  const y = a.y + a.height - 8;
  await page.mouse.move(x, y);
  await page.mouse.down();
  // past the 6 px activation distance, then over the target column in a few steps
  await page.mouse.move(x + 10, y + 4, { steps: 3 });
  await page.mouse.move(b.x + b.width / 2, b.y + 60, { steps: 12 });
  await page.mouse.up();
}

test('J16: lifecycle portfolio from the onboarding template', async ({ page }) => {
  await login(page);
  await page.goto('/portfolios');
  await page.getByRole('button', { name: 'New portfolio' }).click();
  await page.getByRole('textbox', { name: 'Portfolio name' }).fill('J16 Onboarding');
  await page.getByRole('main').getByRole('button', { name: 'Create', exact: true }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'J16 Onboarding' })).toBeVisible();

  // a rule: every project made from the template
  await page.getByRole('button', { name: 'Settings' }).click();
  const dialog = page.getByRole('dialog', { name: 'Portfolio settings' });
  await dialog.getByRole('radio', { name: 'By a rule' }).click();
  const rule = dialog.getByRole('form', { name: 'Rule' });
  await rule.getByRole('checkbox', { name: 'Customer onboarding' }).check();
  await rule.getByRole('button', { name: 'Save rule' }).click();
  await expect(page.getByText('Portfolio settings saved')).toBeVisible();

  // the stage field, and a gate on Contracts (a signed NDA)
  await dialog.getByRole('tab', { name: 'Stages and gates' }).click();
  await dialog.getByRole('combobox', { name: 'Stage field' }).selectOption({ label: 'Stage' });
  const files = dialog.getByRole('textbox', { name: 'Files Contracts needs' });
  await files.fill('*nda*');
  await files.blur();
  await dialog.getByRole('button', { name: 'Save stages' }).click();
  await expect(page.getByText('Portfolio settings saved').first()).toBeVisible();
  await page.keyboard.press('Escape');

  // the board: drag a Discovery customer to Contracts; the gate shows its checklist
  await page.getByRole('tab', { name: 'Board', exact: true }).click();
  const discovery = page.getByRole('listitem', { name: /^Discovery: \d+ projects?/ }); // journeys share the data
  await expect(discovery).toBeVisible();
  const card = discovery.getByRole('list').getByRole('listitem').first();
  const name = (await card.getByRole('link').first().textContent())!.trim();
  await dragTo(page, card, page.getByRole('listitem', { name: /^Contracts:/ }));
  const gate = page.getByRole('dialog', { name: new RegExp(`isn’t ready for Contracts`) });
  await expect(gate.getByRole('list', { name: 'Gate checklist' })).toContainText('*nda*');
  await gate.getByRole('button', { name: 'Move anyway' }).click();
  await expect(gate).toBeHidden();
  await expect(page.getByRole('listitem', { name: /^Contracts:/ }).getByRole('link', { name })).toBeVisible();

  // the table: edit a Contract value in place
  await page.getByRole('tab', { name: 'Table' }).click();
  const table = page.getByRole('table', { name: 'Projects in J16 Onboarding' });
  const row = table.getByRole('row', { name: new RegExp(name) });
  const value = row.getByRole('spinbutton', { name: 'Contract value' });
  await value.fill('123456');
  await value.press('Enter');
  await expect(page.getByText('Contract value updated')).toBeVisible();

  // a personal view
  await page.getByRole('combobox', { name: 'Group by' }).selectOption({ label: 'Group: Stage' });
  await expect(table.getByRole('rowheader', { name: /^Contracts/ })).toBeVisible();
  await page.getByRole('button', { name: 'Save view' }).click();
  await page.getByRole('textbox', { name: 'View name' }).fill('J16 by stage');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByRole('combobox', { name: 'View' })).toHaveValue(/.+/);
  await expect(page.getByRole('combobox', { name: 'View' }).locator('option:checked')).toHaveText(
    'J16 by stage',
  );

  // the timeline renders a bar per customer
  await page.getByRole('tab', { name: 'Timeline' }).click();
  const timeline = page.getByRole('region', { name: 'Timeline of J16 Onboarding' });
  await expect(timeline.getByRole('listitem').first()).toBeVisible();
  expect(await timeline.getByRole('listitem').count()).toBeGreaterThanOrEqual(12);
});
