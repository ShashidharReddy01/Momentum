import { expect, test } from '@playwright/test';
import { login } from './helpers';

/**
 * J17 (Phase 7.5, spec §11.4): a role dashboard. On the seeded lifecycle portfolio's Dashboard tab,
 * create "Implementation lead" from its template, check the filter bar's "owner = me" (saved by the
 * template) and change it for this view only, add a lifecycle funnel, and drill a stage into the
 * projects behind it. (The PDF export step joins in S75-09.)
 */
test('J17: role dashboard from a template, filters and a stage drill', async ({ page }) => {
  await login(page);
  const folios = (await (await page.request.get('/api/v1/portfolios')).json()).data as {
    id: string;
    name: string;
  }[];
  const folio = folios.find((f) => f.name === 'Customer onboarding')!.id;
  await page.goto(`/portfolios/${folio}/dashboard`);
  await expect(page.getByRole('tab', { name: 'Dashboard', selected: true })).toBeVisible();

  // journeys share the database: make the tab's dashboard unless an earlier run did
  const start = page.getByRole('button', { name: 'Start from a template' });
  const slipping = page.getByRole('region', { name: 'Slipping' });
  await expect(start.or(slipping)).toBeVisible();
  if (await start.isVisible()) {
    await start.click();
    const dialog = page.getByRole('dialog', { name: 'New dashboard from a template' });
    await dialog.getByRole('button', { name: /Implementation lead/ }).click();
    await expect(dialog.getByRole('region', { name: 'What it will hold' })).toContainText('Control tower');
    await dialog.getByRole('button', { name: 'Create dashboard' }).click();
    await expect(dialog).toBeHidden();
  }
  await expect(slipping).toBeVisible();
  await expect(page.getByRole('region', { name: 'Control tower' }).getByRole('table')).toBeVisible();

  // the template saved "owner = me": turning it off changes this view only
  const bar = page.getByRole('region', { name: 'Dashboard filters' });
  const mine = bar.getByRole('button', { name: 'Projects I own' });
  await expect(mine).toHaveAttribute('aria-pressed', 'true');
  await mine.click();
  await expect(mine).toHaveAttribute('aria-pressed', 'false');
  await expect(bar.getByText('Only you see this view')).toBeVisible();
  await expect(page).toHaveURL(/filters=/);
  await bar.getByRole('button', { name: 'Back to the saved filters' }).click();
  await expect(mine).toHaveAttribute('aria-pressed', 'true');

  // a lifecycle funnel, added from the editor
  const funnel = page.getByRole('region', { name: 'Lifecycle funnel' });
  if (!(await funnel.isVisible())) {
    await page.getByRole('button', { name: 'Add chart' }).click();
    const editor = page.getByRole('dialog', { name: 'Add a chart' });
    await editor.getByRole('radio', { name: 'Lifecycle' }).click();
    await editor.getByLabel('Portfolio').selectOption({ label: 'Customer onboarding' });
    await expect(editor.getByText('Preview, with your numbers')).toBeVisible();
    await editor.getByRole('button', { name: 'Add chart' }).click();
    await expect(editor).toBeHidden();
  }
  await expect(funnel).toBeVisible();

  // drill a stage: the projects behind it
  await funnel.getByRole('button', { name: /^Pre-sales/ }).click();
  const panel = page.getByRole('complementary', { name: 'Projects behind this number' });
  await expect(panel.getByRole('heading', { name: /Pre-sales/ })).toBeVisible();
  await expect(panel.getByRole('link').first()).toBeVisible();
});
