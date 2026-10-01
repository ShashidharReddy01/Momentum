import { chromium } from '@playwright/test';
const out = 'C:/Users/SHASHI~1/AppData/Local/Temp/claude/C--Users-ShashidharVReddy-Documents-Projects-Momentum/4b8ff23c-3b0f-4dd2-9b62-bf6aeb36e941/scratchpad/audit2';
const base = 'http://localhost:5181';
const browser = await chromium.launch();
async function as(user, vp, scheme) {
  const ctx = await browser.newContext({ viewport: vp, colorScheme: scheme });
  const page = await ctx.newPage();
  await page.goto(base + '/'); await page.click('text=' + user); await page.waitForSelector('text=Good');
  return { ctx, page };
}
async function shot(page, name, scheme) {
  if (scheme === 'dark') await page.evaluate(() => document.querySelector('.momentum-root')?.setAttribute('data-theme', 'dark'));
  await page.waitForTimeout(1100);
  await page.screenshot({ path: out + '/' + name + '.png' });
}
const vps = { '1280x620': { width: 1280, height: 620 }, '1920x1080': { width: 1920, height: 1080 } };
for (const [user, tag] of [['Avery Admin', 'admin'], ['Ravi Kumar', 'ravi']]) {
  for (const [vn, vp] of Object.entries(vps)) {
    for (const scheme of vn === '1280x620' ? ['light', 'dark'] : ['light']) {
      const { ctx, page } = await as(user, vp, scheme);
      const projects = await page.evaluate(async () => (await (await fetch('/api/v1/projects')).json()).data);
      const atlas = projects.find((p) => p.name === 'Atlas Website Relaunch')?.id;
      const pre = tag + '-' + vn + '-' + scheme + '-';
      for (const [n, path] of [['home', '/'], ['mytasks', '/my-tasks'], ['inbox', '/inbox'], ['portfolios', '/portfolios'], ['goals', '/goals'], ['workload', '/workload'], ['dashboards', '/dashboards'], ['agents', '/agents'], ['members', '/settings/members']]) {
        await page.goto(base + path); await shot(page, pre + n, scheme);
      }
      if (atlas) for (const v of ['list', 'board', 'calendar', 'timeline', 'overview', 'dashboard']) {
        await page.goto(base + '/projects/' + atlas + '/' + v); await shot(page, pre + 'atlas-' + v, scheme);
      }
      if (atlas) {
        const tid = await page.evaluate(async (id) => (await (await fetch('/api/v1/projects/' + id + '/tasks?completed=false')).json()).data.find((t) => t.title.startsWith('Visual design'))?.id, atlas);
        await page.goto(base + '/projects/' + atlas + '/list?task=' + tid); await shot(page, pre + 'atlas-pane', scheme);
      }
      await ctx.close();
    }
  }
}
console.log('ok');
await browser.close();
