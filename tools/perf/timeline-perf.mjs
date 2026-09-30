// Timeline performance probe (S6.1.1a). Usage:
//   momentum seed --perf && (cd apps/web && pnpm build)
//   MOMENTUM_SPA_DIR=apps/web/dist momentum serve --port 8000
//   node tools/perf/timeline-perf.mjs http://localhost:8000 4 [screenshot-dir]   # 4 = CPU slowdown
// Needs playwright-core and a Chromium (CHROMIUM_PATH, default /opt/pw-browsers/...).
import { chromium } from 'playwright-core';
const base = process.argv[2] ?? 'http://localhost:8000';
const slowdown = Number(process.argv[3] ?? 4);
const shots = process.argv[4];
const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH ?? '/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
});
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();
const errors = [];
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
const cdp = await ctx.newCDPSession(page);
await cdp.send('Emulation.setCPUThrottlingRate', { rate: slowdown });
await page.goto(base + '/');
await page.click('text=Ravi Kumar');
await page.waitForSelector('text=Good');
await page.click('nav >> text=Load Test Timeline (500)');
await page.waitForURL(/\/projects\/[^/]+/);
const t0 = Date.now();
await page.click('nav[aria-label="Project views"] >> text=Timeline');
await page.waitForSelector('[data-bar]');
const firstBarMs = Date.now() - t0;
const dom = await page.evaluate(() => ({
  rows: document.querySelectorAll('[data-task-row]').length,
  arrows: document.querySelectorAll('path[data-edge]').length,
  summary: document.querySelector('[role="toolbar"]')?.textContent,
}));
console.log(JSON.stringify({ firstBarMs, ...dom }));

async function frames(axis) {
  return page.evaluate(async (axis) => {
    const el = document.querySelector('[aria-label="Timeline chart"]');
    const gaps = [];
    let last = performance.now();
    let running = true;
    const tick = (t) => {
      gaps.push(t - last);
      last = t;
      if (running) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
    const start = performance.now();
    while (performance.now() - start < 3000) {
      if (axis === 'y') el.scrollTop += 60;
      else el.scrollLeft += 60;
      await new Promise((r) => requestAnimationFrame(r));
    }
    running = false;
    gaps.sort((a, b) => a - b);
    const p = (q) => Math.round(gaps[Math.floor(gaps.length * q)]);
    return { frames: gaps.length, p50: p(0.5), p95: p(0.95), max: Math.round(gaps.at(-1)) };
  }, axis);
}
console.log('scroll-y', JSON.stringify(await frames('y')));
console.log('scroll-x', JSON.stringify(await frames('x')));

if (shots) {
  await cdp.send('Emulation.setCPUThrottlingRate', { rate: 1 });
  await page.click('text=Today');
  await page.evaluate(() => document.querySelector('[aria-label="Timeline chart"]').scrollTo({ top: 0 }));
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${shots}/timeline-light.png` });
  const bar = page.locator('[data-bar]').nth(3);
  await bar.hover();
  await page.waitForTimeout(200);
  await page.screenshot({ path: `${shots}/timeline-hover.png` });
  await page.emulateMedia({ colorScheme: 'dark' });
  await page.evaluate(() => document.documentElement.setAttribute('data-theme', 'dark'));
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${shots}/timeline-dark.png` });
}
if (errors.length) console.log('console errors', errors);
await browser.close();
