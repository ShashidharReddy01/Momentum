import { expect, test } from '@playwright/test';
import { dragOnto, login, settled } from './helpers';

/**
 * J9 (Phase 4): a rule "when a task moves to Done, notify someone" actually fires against the
 * real rules executor (the embedded worker's `run_rules` cron, `* * * * *` — up to a minute of
 * real wall-clock, not simulated), not just the mock-mode unit coverage in `test_rules.py`. Two
 * browsers: Ravi builds the rule and moves the card; Ana (the notified person, not the rule's
 * mover) checks her own inbox for it.
 */
test('J9: a rule fires and delivers a notification', async ({ browser }) => {
  test.setTimeout(120_000);
  const ctxA = await browser.newContext();
  const ctxB = await browser.newContext();
  const ravi = await ctxA.newPage();
  const ana = await ctxB.newPage();

  await login(ravi, 'Ravi Kumar');
  await ravi.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Website Revamp' }).click();

  // build the rule: when a task moves to Done, notify Ana
  await ravi.getByRole('button', { name: 'Project actions' }).click();
  await ravi.getByRole('menuitem', { name: 'Rules' }).click();
  const dialog = ravi.getByRole('dialog', { name: 'Rules' });
  await dialog.getByRole('button', { name: 'New rule' }).click();
  await dialog.getByRole('textbox', { name: 'Rule name' }).fill('J9 notify on done');
  await dialog.getByRole('combobox', { name: 'Trigger' }).selectOption('task.moved');
  await dialog.getByRole('combobox', { name: 'Section' }).selectOption({ label: 'Done' });
  await dialog.getByRole('combobox', { name: 'Action' }).selectOption('notify_user');
  await dialog.getByRole('combobox', { name: 'Person' }).selectOption({ label: 'Ana Souza' });
  await dialog.getByRole('textbox', { name: 'Text' }).fill('J9: a task reached Done');
  await dialog.getByRole('button', { name: 'Create rule' }).click();
  await expect(dialog.getByText('J9 notify on done')).toBeVisible();
  // guards against a mis-selected combobox option silently saving the wrong trigger/action
  await expect(dialog.getByText(/moves to Done/)).toBeVisible();
  await expect(dialog.getByText(/notify Ana Souza/)).toBeVisible();
  await ravi.keyboard.press('Escape');

  // drag the first Backlog card into Done (a freshly quick-added card isn't reliably draggable
  // the same tick it's created, so — like J4 — this moves an existing seeded card)
  await ravi
    .getByRole('navigation', { name: 'Project views' })
    .getByRole('link', { name: 'Board', exact: true })
    .click();
  const backlog = ravi.getByRole('list', { name: 'Cards in Backlog' });
  const done = ravi.getByRole('list', { name: 'Cards in Done' });
  const card = backlog.getByRole('listitem').first();
  const title = (await card.getAttribute('aria-label'))!;
  await dragOnto(ravi, card, done.getByRole('listitem').first());
  await settled(ravi);
  await expect(done.getByRole('listitem', { name: title })).toBeVisible();

  // Ana's inbox, opened once and never reloaded: the rules executor ticks once a minute (real
  // wall-clock), and since S5.0.1 the inbox is live, so the notification appears on the page
  // she is already looking at.
  await login(ana, 'Ana Souza');
  await ana.goto('/inbox');
  await expect(ana.getByRole('button', { name: 'J9: a task reached Done' })).toBeVisible({
    timeout: 90_000,
  });

  await ctxA.close();
  await ctxB.close();
});
