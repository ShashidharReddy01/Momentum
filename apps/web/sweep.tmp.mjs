// usage: node sweep.tmp.mjs <outdir> <who> <scheme> <WxH>[,WxH...] [screens,...]
import { chromium } from '@playwright/test';
import { mkdirSync } from 'node:fs';
const [out, who = 'Avery Admin', scheme = 'light', sizes = '1280x620', only] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const base = 'http://localhost:5181';
const browser = await chromium.launch();
const errors = [];
const slug = who.split(' ')[0].toLowerCase();
for (const size of sizes.split(',')) {
  const [width, height] = size.split('x').map(Number);
  const ctx = await browser.newContext({ viewport: { width, height }, colorScheme: scheme });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(base + '/');
  await page.click('text=' + who);
  await page.waitForSelector('text=/Good (morning|afternoon|evening)/');
  const projects = await page.evaluate(async () => (await (await fetch('/api/v1/projects')).json()).data);
  const atlas = projects.find((p) => p.name.startsWith('Atlas'))?.id;
  const screens = {
    home: '/', mytasks: '/my-tasks', inbox: '/inbox', portfolios: '/portfolios', goals: '/goals',
    workload: '/workload', dashboards: '/dashboards', agents: '/agents', members: '/settings/members',
    ask: '/ask', 'atlas-list': `/projects/${atlas}/list`, 'atlas-board': `/projects/${atlas}/board`,
    'atlas-calendar': `/projects/${atlas}/calendar`, 'atlas-timeline': `/projects/${atlas}/timeline`,
    'atlas-overview': `/projects/${atlas}/overview`, 'atlas-dashboard': `/projects/${atlas}/dashboard`,
    'atlas-pane': `/projects/${atlas}/list`,
  };
  for (const [name, path] of Object.entries(screens)) {
    if (only && !only.split(',').includes(name)) continue;
    await page.goto(base + path);
    await page.waitForLoadState('networkidle');
    if (name === 'atlas-pane') {
      await page.locator('[aria-label^="Open details for"]').nth(1).click();
      await page.waitForTimeout(500);
    }
    await page.waitForTimeout(600);
    await page.screenshot({ path: `${out}/${slug}-${size}-${scheme}-${name}.png` });
  }
  await ctx.close();
}
console.log('errors', JSON.stringify(errors));
await browser.close();
