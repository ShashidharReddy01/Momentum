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
    test.setTimeout(180_000);
    await page.emulateMedia({ colorScheme: scheme, reducedMotion: 'reduce' });
    await login(page, 'Avery Admin');
    const found: string[] = [];
    for (const [name, path] of PAGES) {
      await page.goto(path);
      found.push(...(await serious(page)).map((v) => `${name}: ${v}`));
    }
    // Phase 7.5: the lifecycle portfolio's table, board and timeline, and a project's Files tab
    const folios = (await (await page.request.get('/api/v1/portfolios')).json()).data as {
      id: string;
      name: string;
    }[];
    const folio = folios.find((f) => f.name === 'Customer onboarding')!.id;
    for (const tab of ['table', 'board', 'timeline']) {
      await page.goto(`/portfolios/${folio}/${tab}`);
      await expect(
        page.getByRole('tab', { name: tab[0]!.toUpperCase() + tab.slice(1), selected: true }),
      ).toBeVisible();
      found.push(...(await serious(page)).map((v) => `Portfolio ${tab}: ${v}`));
    }
    // S75-13: the portfolio's Dashboard and Reports tabs and Mo's brief (S75-08 to S75-10)
    for (const tab of ['dashboard', 'reports']) {
      await page.goto(`/portfolios/${folio}/${tab}`);
      await expect(
        page.getByRole('tab', { name: tab[0]!.toUpperCase() + tab.slice(1), selected: true }),
      ).toBeVisible();
      found.push(...(await serious(page)).map((v) => `Portfolio ${tab}: ${v}`));
    }
    await page.getByRole('button', { name: /Brief me/ }).click();
    const brief = page.getByRole('dialog', { name: /Brief: Customer onboarding/ });
    await expect(brief.getByRole('button', { name: 'Done' })).toBeVisible();
    found.push(...(await serious(page)).map((v) => `Portfolio brief: ${v}`));
    await brief.getByRole('button', { name: 'Done' }).click();
    // S75-08: a role dashboard (the seed pins Leadership to the admin's Home)
    const pinned = (await (await page.request.get('/api/v1/dashboards/pinned')).json()).data as {
      id: string;
    }[];
    await page.goto(`/dashboards/${pinned[0]!.id}`);
    await expect(page.getByRole('region', { name: 'Lifecycle funnel' })).toBeVisible();
    found.push(...(await serious(page)).map((v) => `Role dashboard: ${v}`));

    await page.goto('/');
    await page
      .getByRole('navigation', { name: 'Main' })
      .getByRole('link', { name: 'Website Revamp' })
      .click();
    await expect(page.getByRole('list', { name: 'Tasks in Review' })).toBeVisible();
    found.push(...(await serious(page)).map((v) => `Project list: ${v}`));
    // S75-09 / S75-11: the report dialog and Catch me up
    await page.getByRole('button', { name: 'Project actions' }).click();
    const reportItem = page.getByRole('menuitem', { name: /^Create report/ });
    await reportItem.focus();
    await page.keyboard.press('Enter');
    const report = page.getByRole('dialog', { name: /Create a report: Website Revamp/ });
    await expect(
      report.getByRole('region', { name: 'Report outline' }).getByText(/About \d+ page/),
    ).toBeVisible();
    found.push(...(await serious(page)).map((v) => `Report dialog: ${v}`));
    await report.getByRole('button', { name: 'Cancel' }).click();
    await expect(report).toBeHidden();
    await page.getByRole('button', { name: /Catch me up/ }).click();
    const catchUp = page.getByRole('dialog', { name: 'Catch me up: Website Revamp' });
    await expect(catchUp.getByRole('button', { name: 'Done' })).toBeVisible();
    await expect(catchUp.getByText(/changes? by others|Nothing changed since/)).toBeVisible();
    found.push(...(await serious(page)).map((v) => `Catch me up: ${v}`));
    await catchUp.getByRole('button', { name: 'Done' }).click();
    const first = page.getByRole('list', { name: 'Tasks in Review' }).locator('[data-task-id]').first();
    const title = (await first.getAttribute('aria-label'))!;
    await row(page, title)
      .getByRole('button', { name: `Open details for ${title}` })
      .click();
    await expect(page.getByRole('complementary', { name: 'Task details' })).toBeVisible();
    found.push(...(await serious(page)).map((v) => `Task pane: ${v}`));
    const projects = (await (await page.request.get('/api/v1/projects')).json()).data as {
      id: string;
      name: string;
    }[];
    const revamp = projects.find((p) => p.name === 'Website Revamp')!.id;
    // Phase 7.6 S76-08: the review screen, the Records tab, entities and the skills admin
    const bill = await firstBill(page);
    await page.goto(`/records/${bill}`);
    await expect(page.getByRole('grid', { name: 'Lines grid' })).toBeVisible();
    found.push(...(await serious(page)).map((v) => `Record review: ${v}`));
    await page.goto(`/projects/${revamp}/records`);
    await expect(page.getByRole('table', { name: 'Echo bill records' })).toBeVisible();
    found.push(...(await serious(page)).map((v) => `Records tab: ${v}`));
    await page.goto('/entities');
    await expect(page.getByRole('list', { name: 'Entities' })).toBeVisible();
    found.push(...(await serious(page)).map((v) => `Entities: ${v}`));
    const agents = (await (await page.request.get('/api/v1/agents')).json()).data as {
      id: string;
      key: string;
    }[];
    await page.goto(`/agents/${agents.find((a) => a.key === 'echo')!.id}?tab=skills`);
    await expect(page.getByRole('region', { name: 'Skills' })).toBeVisible();
    found.push(...(await serious(page)).map((v) => `Skills admin: ${v}`));
    // last: opening Files makes the project remember that view
    await page.goto(`/projects/${revamp}/files`);
    await expect(page.getByRole('toolbar', { name: 'Files' })).toBeVisible();
    found.push(...(await serious(page)).map((v) => `Project files: ${v}`));
    // back to the list, so the next run (and journey) opens the project on its list
    await page.goto(`/projects/${revamp}/list`);
    await expect(page.getByRole('list', { name: 'Tasks in Review' })).toBeVisible();
    await page.waitForLoadState('networkidle');
    expect(found).toEqual([]);
  });
}

async function firstBill(page: Page): Promise<string> {
  const rows = (await (await page.request.get('/api/v1/records?type=echo_bill&q=INV-0041')).json()).data as {
    id: string;
  }[];
  return rows[0]!.id;
}

test('J14: the review screen from the keyboard: highlight → field, edit, save, undo', async ({ page }) => {
  await login(page, 'Avery Admin');
  await page.goto(`/records/${await firstBill(page)}`);
  // every highlight has a text equivalent and is a keyboard stop
  const box = page.getByRole('button', { name: /^Number: page 1, top right$/ });
  await box.focus();
  await page.keyboard.press('Enter');
  const number = page.getByRole('textbox', { name: /^Number/ });
  await expect(number).toBeFocused();
  await page.keyboard.press('ControlOrMeta+a');
  await page.keyboard.type('INV-0041A');
  // the lines grid: ↓ moves to the same column in the next row
  const grid = page.getByRole('grid', { name: 'Lines grid' });
  await grid.getByRole('textbox', { name: 'Amount, row 1' }).focus();
  await page.keyboard.press('ArrowDown');
  await expect(grid.getByRole('textbox', { name: 'Amount, row 2' })).toBeFocused();
  const save = page.getByRole('button', { name: /^Save \(1 change\)/ });
  await save.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByText('Saved')).toBeVisible();
  await expect(number).toHaveValue('INV-0041A');
  await page.getByRole('button', { name: 'Undo' }).click();
  await expect(number).toHaveValue('INV-0041');
});

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

test('J14: a portfolio board card moves to another stage from the keyboard', async ({ page }) => {
  await login(page);
  const folios = (await (await page.request.get('/api/v1/portfolios')).json()).data as {
    id: string;
    name: string;
  }[];
  await page.goto(`/portfolios/${folios.find((f) => f.name === 'Customer onboarding')!.id}/board`);
  const presales = page.getByRole('listitem', { name: /^Pre-sales:/ });
  const card = presales.getByRole('list').getByRole('listitem').first();
  const name = (await card.getByRole('link').first().textContent())!.trim();
  const menu = presales.getByRole('button', { name: `Move ${name} to stage…` });
  await menu.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('menu')).toBeVisible();
  // the first enabled stage has focus (Pre-sales, where the card is, is disabled)
  await expect(page.getByRole('menuitem', { name: 'Discovery' })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('listitem', { name: /^Discovery:/ }).getByRole('link', { name })).toBeVisible();
});

test('J14: the report dialog from the keyboard, focus back on the menu button', async ({ page }) => {
  await login(page);
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Website Revamp' }).click();
  await expect(page.getByRole('list', { name: 'Tasks in Review' })).toBeVisible();
  const actions = page.getByRole('button', { name: 'Project actions' });
  await actions.focus();
  await page.keyboard.press('Enter');
  const item = page.getByRole('menuitem', { name: /^Create report/ });
  await expect(item).toBeVisible();
  await item.focus();
  await page.keyboard.press('Enter');
  const dialog = page.getByRole('dialog', { name: /Create a report: Website Revamp/ });
  await expect(dialog).toBeVisible();
  // pick another kind from the keyboard: Tab to it, Enter
  const customer = dialog.getByRole('button', { name: /Customer update/ });
  for (let i = 0; i < 6 && !(await customer.evaluate((el) => el === document.activeElement)); i++)
    await page.keyboard.press('Tab');
  await expect(customer).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(customer).toHaveAttribute('aria-pressed', 'true');
  await expect(dialog.getByRole('region', { name: 'Report outline' })).toContainText('progress update');
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  await expect(actions).toBeFocused();
});

// H67: every dialog on the project ⋯ menu closes with one Escape (the Close button's tooltip must
// not open by itself and take the first Escape) and gives focus back to the menu button
for (const [item, title] of [
  [/^Create report/, /Create a report: Website Revamp/],
  [/^Rules/, 'Rules'],
  [/^Forms/, 'Forms'],
  [/^Save as template/, 'Save as template'],
  [/^Task templates/, 'Task templates'],
  [/^Import from CSV/, 'Import from CSV'],
] as const) {
  test(`J14: ${String(item).slice(2, -1)} from the keyboard, one Escape, focus back on the menu button`, async ({
    page,
  }) => {
    await login(page);
    await page
      .getByRole('navigation', { name: 'Main' })
      .getByRole('link', { name: 'Website Revamp' })
      .click();
    await expect(page.getByRole('list', { name: 'Tasks in Review' })).toBeVisible();
    const actions = page.getByRole('button', { name: 'Project actions' });
    await actions.focus();
    await page.keyboard.press('Enter');
    const entry = page.getByRole('menuitem', { name: item });
    await expect(entry).toBeVisible();
    await entry.focus();
    await page.keyboard.press('Enter');
    const dialog = page.getByRole('dialog', { name: title });
    await expect(dialog).toBeVisible();
    await expect(page.getByRole('tooltip')).toHaveCount(0);
    await page.keyboard.press('Escape');
    await expect(dialog).toBeHidden();
    await expect(actions).toBeFocused();
  });
}
