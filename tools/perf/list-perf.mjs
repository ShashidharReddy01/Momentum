// List performance probe (S1.2.6). Usage:
//   momentum seed --perf && (cd apps/web && pnpm build)
//   MOMENTUM_SPA_DIR=apps/web/dist momentum serve --port 8000
//   node tools/perf/list-perf.mjs http://localhost:8000 4     # 4 = CPU slowdown factor
// Needs playwright-core and a Chromium (CHROMIUM_PATH, default /opt/pw-browsers/...).
import { chromium } from 'playwright-core';
const base = process.argv[2] ?? 'http://localhost:8000';
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH ?? '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();
const errors = [];
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
// mid-laptop approximation: 4x CPU slowdown
const cdp = await ctx.newCDPSession(page);
await cdp.send('Emulation.setCPUThrottlingRate', { rate: Number(process.argv[3] ?? 4) });
await page.goto(base + '/');
await page.click('text=Ravi Kumar');
await page.waitForSelector('text=Good');
const t0 = Date.now();
let apiMs = 0;
page.on('response', async (r) => {
  if (/\/projects\/[^/]+\/tasks\?/.test(r.url()) && r.url().includes('completed=false')) apiMs = Date.now() - t0;
});
await page.click('nav >> text=Load Test (2k)');
await page.waitForSelector('[data-task-id]');
const tFirst = Date.now() - t0;
await page.waitForFunction(() => document.querySelectorAll('[data-task-id]').length > 0 && document.querySelector('[aria-label="Tasks in Done"]'));
const tAll = Date.now() - t0;
const rows = await page.$$eval('[data-task-id]', (els) => els.length);
console.log(JSON.stringify({ apiMs, firstRowMs: tFirst, listRenderedMs: tAll, domRows: rows }));
// scroll smoothness: scroll the main scroller for 2s, record frame gaps
const scroll = await page.evaluate(async () => {
  const el = document.querySelector('[data-task-id]').closest('.overflow-auto');
  const gaps = [];
  let last = performance.now();
  let running = true;
  const tick = (t) => { gaps.push(t - last); last = t; if (running) requestAnimationFrame(tick); };
  requestAnimationFrame(tick);
  const start = performance.now();
  while (performance.now() - start < 3000) {
    el.scrollTop += 60; // ~3,600 px/s, a fast flick
    await new Promise((r) => requestAnimationFrame(r));
  }
  running = false;
  gaps.sort((a, b) => a - b);
  const p = (q) => Math.round(gaps[Math.floor(gaps.length * q)]);
  return { frames: gaps.length, p50: p(0.5), p95: p(0.95), max: Math.round(gaps.at(-1)), scrolled: el.scrollTop };
});
console.log('scroll', JSON.stringify(scroll));
// edit feedback: focus a row, press M, time until assignee cell updates
await page.evaluate(() => document.querySelector('[data-task-id]').closest('.overflow-auto').scrollTo(0, 0));
await page.waitForTimeout(300);
const lat = await page.evaluate(async () => {
  const rows = [...document.querySelectorAll('[data-task-id]')];
  const target = rows.find((r) => !r.querySelector('button[aria-label^="Assignee: Ravi"]'));
  target.focus();
  const t = performance.now();
  target.dispatchEvent(new KeyboardEvent('keydown', { key: 'm', bubbles: true }));
  return await new Promise((resolve) => {
    const check = () => {
      const el = document.querySelector(`[data-task-id="${target.dataset.taskId}"] button[aria-label^="Assignee: Ravi"]`);
      if (el) resolve(Math.round(performance.now() - t));
      else if (performance.now() - t > 5000) resolve(-1);
      else requestAnimationFrame(check);
    };
    check();
  });
});
const sel = await page.evaluate(async () => {
  const rows = [...document.querySelectorAll('[data-task-id]')];
  rows[5].focus();
  const t = performance.now();
  rows[5].dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', shiftKey: true, bubbles: true }));
  return await new Promise((resolve) => {
    const check = () => {
      if (document.querySelector(`[data-task-id="${rows[5].dataset.taskId}"]`)?.hasAttribute('data-selected')) resolve(Math.round(performance.now() - t));
      else if (performance.now() - t > 5000) resolve(-1);
      else requestAnimationFrame(check);
    };
    check();
  });
});
console.log('latency', JSON.stringify({ assignToMeMs: lat, shiftSelectMs: sel }));
console.log('errors', JSON.stringify(errors.filter((e) => !e.includes('401'))));
await browser.close();
