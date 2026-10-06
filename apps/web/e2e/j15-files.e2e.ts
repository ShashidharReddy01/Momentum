import { expect, test, type APIRequestContext } from '@playwright/test';
import { login } from './helpers';

/**
 * J15 (Phase 7.5, spec §11.4). Part 1 (S75-01): a project's Files tab shows a task's attachment
 * and accepts uploads straight to the project; uploading a file with the same name offers a new
 * version; the versions drawer lists both; delete, then Undo brings it back.
 * Part 2 (S75-03) asks Mo about the workbook.
 */
const H = { 'X-Requested-With': 'momentum' };

async function json(r: Awaited<ReturnType<APIRequestContext['get']>>) {
  expect(r.ok(), await r.text()).toBeTruthy();
  return r.json();
}

test('J15: project files, versions, delete and undo', async ({ page }) => {
  await login(page);
  const api = page.request;
  const teams = (await json(await api.get('/api/v1/teams'))).data as { id: string; name: string }[];
  const team = teams.find((t) => t.name === 'Product')!.id;
  const pid = (
    await json(await api.post('/api/v1/projects', { headers: H, data: { team_id: team, name: 'J15 Files' } }))
  ).data.id as string;
  const task = (
    await json(
      await api.post(`/api/v1/projects/${pid}/tasks`, { headers: H, data: { title: 'Send the quote' } }),
    )
  ).data as { id: string; key: string };
  await json(
    await api.post(`/api/v1/tasks/${task.id}/attachments`, {
      headers: H,
      multipart: {
        file: { name: 'Quote.csv', mimeType: 'text/csv', buffer: Buffer.from('item,amount\nA,10\n') },
      },
    }),
  );

  await page.goto(`/projects/${pid}/files`);
  const grid = page.getByRole('grid', { name: 'Project files' });
  await expect(grid.getByText('Quote.csv')).toBeVisible();
  await expect(grid.getByText('Send the quote')).toBeVisible();

  // upload to the project
  await page.getByTestId('files-upload-input').setInputFiles({
    name: 'Statement of work.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('Scope: onboarding'),
  });
  await expect(grid.getByText('Statement of work.txt')).toBeVisible();

  // same name again: offered as a new version
  await page.getByTestId('files-upload-input').setInputFiles({
    name: 'Statement of work.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('Scope: onboarding, v2'),
  });
  const ask = page.getByRole('dialog', { name: /new version of Statement of work.txt/ });
  await ask.getByRole('button', { name: 'New version' }).click();
  await expect(grid.getByText('v2')).toBeVisible();
  await expect(grid.getByRole('row')).toHaveCount(3); // header + 2 files, the old version isn't listed

  await page.getByRole('button', { name: 'Actions for Statement of work.txt' }).click();
  await page.getByRole('menuitem', { name: /Versions/ }).click();
  const versions = page.getByRole('complementary', { name: 'Versions' });
  await expect(versions.getByText('v2')).toBeVisible();
  await expect(versions.getByText('v1')).toBeVisible();
  await versions.getByRole('button', { name: 'Close' }).click();

  // delete the task's file from the Files tab, then undo
  await page.getByRole('button', { name: 'Actions for Quote.csv' }).click();
  await page.getByRole('menuitem', { name: 'Delete' }).click();
  await expect(grid.getByText('Quote.csv')).toBeHidden();
  await page.getByRole('button', { name: 'Undo' }).last().click();
  await expect(grid.getByText('Quote.csv')).toBeVisible();
});

test('J15 part 2: ask Mo about a workbook from the Files tab', async ({ page }) => {
  await login(page);
  const api = page.request;
  const teams = (await json(await api.get('/api/v1/teams'))).data as { id: string; name: string }[];
  const team = teams.find((t) => t.name === 'Product')!.id;
  const pid = (
    await json(await api.post('/api/v1/projects', { headers: H, data: { team_id: team, name: 'J15 Mo' } }))
  ).data.id as string;
  await json(
    await api.post(`/api/v1/projects/${pid}/files`, {
      headers: H,
      multipart: {
        file: {
          name: 'J15 invoices.csv',
          mimeType: 'text/csv',
          buffer: Buffer.from('item,amount\nA,10\nB,32.5\n'),
        },
      },
    }),
  );
  await page.goto(`/projects/${pid}/files`);
  await page.getByRole('button', { name: 'Actions for J15 invoices.csv' }).click();
  await page.getByRole('menuitem', { name: /Ask Mo about this file/ }).click();
  const mo = page.getByRole('complementary', { name: 'Ask Mo' });
  await expect(mo.getByLabel('Chat is about J15 invoices.csv')).toBeVisible();
  await mo.getByRole('textbox', { name: 'Message Mo' }).fill("What's the total amount in this workbook?");
  await mo.getByRole('textbox', { name: 'Message Mo' }).press('Enter');
  // the mock answer cites the sheet; the number comes from the server's query (10 + 32.5)
  const chip = mo.getByRole('link', { name: 'File J15 invoices.csv · s:J15 invoices' });
  await expect(chip).toBeVisible();
  await expect(mo.getByText(/42\.5/)).toBeVisible();
  await expect(mo.getByText(/Queried a table/)).toBeVisible();
});
