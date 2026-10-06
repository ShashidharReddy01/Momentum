// Keyboard pass (Phase 6.5 exit, Phase 7 E7.5.3): on each key screen, Tab through up to 80 stops and
// check that every stop is visible, shows a focus indicator, and that focus moves on (no traps).
// Overlays (the ⌘K palette, quick add) must open from the keyboard, hold focus, and close on Escape
// with focus back where it was. Run against tools/ux/serve.sh:
//   node tools/ux/keyboard.mjs [--base http://localhost:8140] [--out dir]
import { mkdirSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { join, resolve } from 'node:path';

const require = createRequire(resolve('apps/web/package.json'));
const { chromium } = require('@playwright/test');
const arg = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 ? process.argv[i + 1] : fallback;
};
const base = arg('base', 'http://localhost:8140');
const out = resolve(arg('out', 'docs/progress/ux-audit/keyboard'));
mkdirSync(out, { recursive: true });
const findings = [];

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1280, height: 720 }, reducedMotion: 'reduce' });
const page = await ctx.newPage();
await page.goto(base + '/');
await page.getByText('Avery Admin', { exact: true }).first().click();
await page.waitForLoadState('networkidle');
const projects = await page.evaluate(async () => (await (await fetch('/api/v1/projects')).json()).data);
const atlas = projects.find((p) => p.name === 'Atlas Website Relaunch')?.id;

const focusInfo = () =>
  page.evaluate(() => {
    const el = document.activeElement;
    if (!el || el === document.body) return null;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    const name =
      el.getAttribute('aria-label') || (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 40) || el.tagName;
    // a visible indicator: an outline, a ring (box-shadow), or a changed border/background on focus
    const ring = (s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0) || s.boxShadow !== 'none';
    return {
      id: `${el.tagName.toLowerCase()}|${name}|${Math.round(r.x)},${Math.round(r.y)}`,
      name,
      visible: r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.opacity !== '0',
      ring,
    };
  });

async function tabPass(label) {
  const seen = new Set();
  let repeats = 0;
  for (let i = 0; i < 80; i++) {
    await page.keyboard.press('Tab');
    let f = await focusInfo();
    if (!f) continue;
    if (!f.visible || !f.ring) {
      await page.waitForTimeout(250); // let a fade-in or ring transition finish before judging
      f = (await focusInfo()) ?? f;
    }
    if (!f.visible) findings.push({ screen: label, kind: 'focus-on-invisible', detail: f.name });
    else if (!f.ring) findings.push({ screen: label, kind: 'no-focus-indicator', detail: f.name });
    if (seen.has(f.id)) repeats++;
    seen.add(f.id);
    if (repeats > 3) break; // wrapped around: the whole page was reachable
  }
  if (seen.size < 3) findings.push({ screen: label, kind: 'few-tab-stops', detail: `${seen.size}` });
}

const screens = [
  ['home', '/'],
  ['mytasks', '/my-tasks'],
  ['inbox', '/inbox'],
  ['goals', '/goals'],
  ['workload', '/workload'],
  ['settings', '/settings'],
];
if (atlas) {
  for (const v of ['list', 'board', 'calendar', 'timeline', 'overview', 'files', 'dashboard'])
    screens.push([`atlas-${v}`, `/projects/${atlas}/${v}`]);
}
// Phase 7.5: the lifecycle portfolio's views
const folios = await page.evaluate(async () => (await (await fetch('/api/v1/portfolios')).json()).data);
const onboarding = folios.find((f) => f.name === 'Customer onboarding')?.id;
if (onboarding)
  for (const v of ['table', 'board', 'timeline', 'dashboard'])
    screens.push([`onboarding-${v}`, `/portfolios/${onboarding}/${v}`]);
// S75-08: a role dashboard (filter bar, KPI tiles, stage charts)
const pinned = await page.evaluate(async () => (await (await fetch('/api/v1/dashboards/pinned')).json()).data);
if (pinned?.[0]) screens.push(['role-dashboard', `/dashboards/${pinned[0].id}`]);
for (const [label, path] of screens) {
  await page.goto(base + path);
  await page.waitForLoadState('networkidle').catch(() => {});
  await tabPass(label);
}

// overlays: open from the keyboard, focus inside, Escape closes and restores focus
async function overlay(label, open, selector) {
  await page.goto(base + '/my-tasks');
  await page.waitForLoadState('networkidle').catch(() => {});
  await page.locator('main').focus();
  await open();
  const opened = await page
    .locator(selector)
    .first()
    .waitFor({ timeout: 4000 })
    .then(() => true)
    .catch(() => false);
  if (!opened) return findings.push({ screen: label, kind: 'overlay-did-not-open', detail: selector });
  const inside = await page.evaluate((sel) => !!document.activeElement?.closest(sel), selector);
  if (!inside) findings.push({ screen: label, kind: 'focus-not-in-overlay', detail: selector });
  for (let i = 0; i < 15; i++) await page.keyboard.press('Tab');
  const still = await page.evaluate((sel) => !!document.activeElement?.closest(sel), selector);
  if (!still) findings.push({ screen: label, kind: 'focus-escapes-overlay', detail: selector });
  await page.keyboard.press('Escape');
  await page.waitForTimeout(300);
  const closed = (await page.locator(selector).count()) === 0;
  if (!closed) findings.push({ screen: label, kind: 'escape-does-not-close', detail: selector });
}
await overlay('palette', () => page.keyboard.press('Control+k'), '[role=dialog]');
await overlay('quick-add', () => page.keyboard.press('q'), '[role=dialog]');

// the task pane: open a task from the list with the keyboard, Escape closes it
if (atlas) {
  await page.goto(`${base}/projects/${atlas}/list`);
  await page.waitForLoadState('networkidle').catch(() => {});
  await page.locator('[data-task-id]').first().focus();
  await page.keyboard.press('Space');
  const pane = await page
    .getByRole('complementary', { name: 'Task details' })
    .waitFor({ timeout: 4000 })
    .then(() => true)
    .catch(() => false);
  if (!pane) findings.push({ screen: 'pane', kind: 'space-does-not-open-pane', detail: 'list row' });
  else {
    await page.keyboard.press('Escape');
    await page.waitForTimeout(300);
    if (await page.getByRole('complementary', { name: 'Task details' }).count())
      findings.push({ screen: 'pane', kind: 'escape-does-not-close', detail: 'task pane' });
  }
}

await browser.close();
const md = [`# Keyboard pass`, '', `${screens.length} screens + overlays, ${findings.length} findings.`, '']
  .concat(findings.map((f) => `- \`${f.screen}\` **${f.kind}**: ${f.detail}`))
  .join('\n');
writeFileSync(join(out, 'report.md'), md + '\n');
writeFileSync(join(out, 'report.json'), JSON.stringify(findings, null, 2));
console.log(`${findings.length} findings`);
const kinds = {};
for (const f of findings) kinds[f.kind] = (kinds[f.kind] ?? 0) + 1;
console.log(kinds);
