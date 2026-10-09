import { expect, test } from '@playwright/test';
import { login, titlesIn } from './helpers';

/**
 * J10 (Phase 5): assign a task to the Teammate agent → its answer arrives as a comment → the task
 * comes back for review. End to end against the real embedded worker (the `agent_triggers` and
 * `run_agent_runs` jobs tick once a minute of real wall-clock) with the mock model:
 * an admin installs the starters and switches Teammate on; Ravi (admin of Website Revamp) gives
 * it access to his project from the agent's page, assigns it a task from the pane, and waits on
 * the open pane for the reply, which @mentions him, and for the task to move to Review.
 */
test('J10: assign a task to Teammate and get the work back for review', async ({ browser }) => {
  test.setTimeout(240_000);
  const adminCtx = await browser.newContext();
  const raviCtx = await browser.newContext();
  const admin = await adminCtx.newPage();
  const ravi = await raviCtx.newPage();

  // the admin installs the starter agents (all switched off) and switches Teammate on
  await login(admin, 'Avery Admin');
  await admin.goto('/agents');
  const install = admin.getByRole('button', { name: 'Install starter agents' });
  const gallery = admin.getByRole('list', { name: 'Agents' });
  await expect(install.or(gallery)).toBeVisible();
  if (await install.isVisible()) await install.click();
  await admin
    .getByRole('list', { name: 'Agents' })
    .getByRole('link', { name: /^Teammate/ })
    .click();
  await admin.getByRole('tab', { name: 'Settings' }).click(); // Phase 7.6: the agent page has tabs
  const settings = admin.getByRole('region', { name: 'Agent settings' });
  const on = settings.getByRole('checkbox', { name: /Teammate is on/ });
  if (!(await on.isChecked())) await on.click();
  await expect(on).toBeChecked();

  // Ravi gives Teammate access to his project (explicit membership, kickoff Q1)
  await login(ravi, 'Ravi Kumar');
  await ravi.goto('/agents');
  await ravi
    .getByRole('list', { name: 'Agents' })
    .getByRole('link', { name: /^Teammate/ })
    .click();
  const works = ravi.getByRole('region', { name: 'Works in' });
  if (
    !(await works
      .getByText('Website Revamp')
      .isVisible()
      .catch(() => false))
  ) {
    await works.getByRole('combobox', { name: 'Add to project' }).selectOption({ label: 'Website Revamp' });
    await works.getByRole('button', { name: 'Add' }).click();
  }
  await expect(works.getByText('Website Revamp')).toBeVisible();

  // …and assigns it a task from the pane
  await ravi.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Website Revamp' }).click();
  const title = `J10 research ${Date.now()}`;
  await ravi.getByRole('button', { name: 'Add task' }).first().click();
  await ravi.keyboard.type(title);
  await ravi.keyboard.press('Enter');
  await ravi.keyboard.press('Escape');
  await ravi.getByRole('button', { name: `Open details for ${title}` }).click();
  const pane = ravi.getByRole('complementary', { name: 'Task details' });
  await pane.getByRole('button', { name: 'Assign' }).click();
  await ravi.getByRole('option', { name: /Teammate/ }).click();
  await expect(ravi.getByText(/Assigned to Teammate\. It will reply in the comments/)).toBeVisible();

  // within a couple of worker ticks: Teammate's answer on the pane he never left, @mentioning
  // him, and the task handed back for review: Website Revamp has a "Review" section, so the task
  // moves there (with no such section it would be reassigned to its creator)
  await expect(pane.getByText(/\(mock\) Draft ready for review/)).toBeVisible({ timeout: 180_000 });
  await expect(pane.getByText('@Ravi Kumar')).toBeVisible();
  await expect.poll(() => titlesIn(ravi, 'Review'), { timeout: 30_000 }).toContain(title);

  await adminCtx.close();
  await raviCtx.close();
});
