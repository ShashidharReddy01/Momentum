import { expect, test } from '@playwright/test';
import { login, row } from './helpers';

/**
 * J8 (Phase 3): Ask Mo "what's blocking launch?" → an answer with citations. Real API + Postgres;
 * the LLM runs in mock mode (`ai/evals/fixtures/mock_responses/chat.yaml`: a semantic search for
 * launch blockers, then an answer citing exactly what the search returned). Journey-scoped data:
 * the blocker task is created here. The citation must be a working link to that task, and the
 * conversation must come back from history with the link still working.
 */
test('J8: Ask Mo answers with citations that open the cited task', async ({ page }) => {
  await login(page);
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Website Revamp' }).click();
  await expect(page.locator('[data-task-id]').first()).toBeVisible();

  const title = `Launch blocker vendor contract unsigned J8 ${Date.now()}`;
  await page.keyboard.press('q');
  const dialog = page.getByRole('dialog', { name: 'New task' });
  await dialog.getByRole('textbox', { name: 'Task name' }).fill(title);
  await dialog.getByRole('button', { name: 'Add task' }).click();
  await expect(row(page, title)).toBeVisible();

  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Ask Mo' }).click();
  await expect(page.getByText('Ask Mo about your work')).toBeVisible();
  const chat = page.getByRole('region', { name: 'New chat' });
  await chat.getByRole('textbox', { name: 'Message Mo' }).fill("What's blocking launch?");
  await chat.getByRole('textbox', { name: 'Message Mo' }).press('Enter');

  const q = page.getByRole('region', { name: "Question: What's blocking launch?" });
  await expect(q.getByText('Searched content')).toBeVisible();
  const answer = q.getByRole('group', { name: "Mo's answer (AI)" });
  await expect(answer).toContainText('Launch is blocked by');
  const cite = answer.getByRole('link', { name: new RegExp(title) });
  await expect(cite).toBeVisible();
  await expect(page).toHaveURL(/\/ask\/[0-9a-f-]{36}$/);
  const conversationUrl = page.url();
  await q.getByRole('button', { name: 'Good answer' }).click();
  await expect(q.getByRole('button', { name: 'Good answer' })).toHaveAttribute('aria-pressed', 'true');

  await cite.click();
  await expect(page.getByRole('textbox', { name: 'Task name' })).toHaveValue(title);

  // history: the conversation reopens, rating and working citation included
  await page.goto(conversationUrl);
  const again = page.getByRole('region', { name: "Question: What's blocking launch?" });
  await expect(again.getByRole('link', { name: new RegExp(title) })).toBeVisible();
  await expect(again.getByRole('button', { name: 'Good answer' })).toHaveAttribute('aria-pressed', 'true');
  await expect(
    page
      .getByRole('navigation', { name: 'Conversations' })
      .getByRole('link', { name: "What's blocking launch?" }),
  ).toBeVisible();
});
