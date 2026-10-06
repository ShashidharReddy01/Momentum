// UI audit (Phase 6.5 exit, Phase 7 E7.0): every screen of the showcase workspace at the target
// viewports in both themes. For each screen it saves a screenshot and checks, automatically:
// - the page never scrolls sideways;
// - every visible control (button, link, field, tab, menu item) is inside the window (or inside a
//   container that scrolls to it), not covered by something else at its centre, and has a name;
// - axe (WCAG 2.2 A/AA): serious and critical violations.
// Run against tools/ux/serve.sh:  node tools/ux/audit.mjs [--base http://localhost:8140]
//   [--out dir] [--full] [--users admin,ravi]
// Without --full, the four secondary viewports cover the key screens only (the primary 1280x620
// covers all of them). Writes <out>/report.json and <out>/report.md.
import { mkdirSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { join, resolve } from 'node:path';

const require = createRequire(resolve('apps/web/package.json'));
const { chromium } = require('@playwright/test');
const { AxeBuilder } = require('@axe-core/playwright');

const arg = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 ? process.argv[i + 1] : fallback;
};
const base = arg('base', 'http://localhost:8140');
const out = resolve(arg('out', 'docs/progress/ux-audit/latest'));
const full = process.argv.includes('--full');
const users = arg('users', 'admin,ravi').split(',');
const NAMES = { admin: 'Avery Admin', ravi: 'Ravi Kumar', mei: 'Mei Chen', tom: 'Tom Becker' };
const VIEWPORTS = {
  '1280x620': { width: 1280, height: 620 }, // primary: 150% scaling on a laptop
  '1366x768': { width: 1366, height: 768 },
  '1920x1080': { width: 1920, height: 1080 },
  '1024x768': { width: 1024, height: 768 },
  '390x844': { width: 390, height: 844 },
};
const KEY = new Set([
  'home',
  'mytasks',
  'inbox',
  'atlas-list',
  'atlas-board',
  'atlas-pane',
  'atlas-timeline',
  // Phase 7.5: the new screens, at every viewport
  'atlas-files',
  'portfolios',
  'onboarding-table',
  'onboarding-board',
  'onboarding-timeline',
  'onboarding-workload',
]);
mkdirSync(out, { recursive: true });

const findings = [];
const add = (f) => findings.push(f);

async function login(browser, user, viewport, scheme) {
  const ctx = await browser.newContext({ viewport, colorScheme: scheme, reducedMotion: 'reduce' });
  const page = await ctx.newPage();
  await page.goto(base + '/');
  await page.getByText(NAMES[user] ?? user, { exact: true }).first().click();
  await page.waitForLoadState('networkidle');
  return { ctx, page };
}

async function screens(page) {
  const projects = await page.evaluate(async () => (await (await fetch('/api/v1/projects')).json()).data);
  const atlas = projects.find((p) => p.name === 'Atlas Website Relaunch')?.id;
  const list = [
    ['home', '/'],
    ['mytasks', '/my-tasks'],
    ['inbox', '/inbox'],
    ['search', '/search?q=design'],
    ['portfolios', '/portfolios'],
    ['goals', '/goals'],
    ['workload', '/workload'],
    ['dashboards', '/dashboards'],
    ['agents', '/agents'],
    ['settings-profile', '/settings'],
    ['settings-members', '/settings/members'],
    ['settings-ai', '/settings/ai'],
  ];
  if (atlas) {
    for (const v of ['list', 'board', 'calendar', 'timeline', 'overview', 'files', 'dashboard'])
      list.push([`atlas-${v}`, `/projects/${atlas}/${v}`]);
    const tasks = await page.evaluate(
      async (id) => (await (await fetch(`/api/v1/projects/${id}/tasks?completed=false`)).json()).data,
      atlas,
    );
    const rich = tasks.find((t) => (t.subtask_count ?? 0) > 0) ?? tasks[0];
    if (rich) list.push(['atlas-pane', `/projects/${atlas}/list?task=${rich.id}`]);
  }
  const folios = await page.evaluate(async () => (await (await fetch('/api/v1/portfolios')).json()).data);
  const onboarding = folios.find((f) => f.name === 'Customer onboarding')?.id;
  if (onboarding)
    for (const v of ['table', 'board', 'timeline', 'workload', 'overview', 'dashboard'])
      list.push([`onboarding-${v}`, `/portfolios/${onboarding}/${v}`]);
  // S75-08: the role dashboards the seed pins to each persona's Home
  const pinned = await page.evaluate(async () => (await (await fetch('/api/v1/dashboards/pinned')).json()).data);
  if (pinned?.[0]) list.push(['role-dashboard', `/dashboards/${pinned[0].id}`]);
  return list;
}

async function checkControls(page) {
  return page.evaluate(() => {
    const W = window.innerWidth;
    const H = window.innerHeight;
    const issues = [];
    if (document.documentElement.scrollWidth > W + 1)
      issues.push({ kind: 'page-scrolls-sideways', detail: `${document.documentElement.scrollWidth} > ${W}` });
    const sel =
      'button, a[href], input:not([type=hidden]), select, textarea, [role=button], [role=tab], [role=menuitem], [role=checkbox], [role=switch]';
    const scrollsX = (el) => {
      for (let p = el.parentElement; p; p = p.parentElement) {
        const s = getComputedStyle(p);
        if (/(auto|scroll|hidden)/.test(s.overflowX) && p.scrollWidth > p.clientWidth + 1) return p;
      }
      return null;
    };
    const clipper = (el) => {
      for (let p = el.parentElement; p; p = p.parentElement) {
        const s = getComputedStyle(p);
        if (/(auto|scroll|hidden)/.test(s.overflow + s.overflowX + s.overflowY)) return p;
      }
      return null;
    };
    const describe = (el) => {
      const name =
        el.getAttribute('aria-label') ||
        el.getAttribute('title') ||
        (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 50) ||
        el.getAttribute('placeholder') ||
        '';
      return `${el.tagName.toLowerCase()}${el.getAttribute('role') ? `[${el.getAttribute('role')}]` : ''} "${name}"`;
    };
    const named = (el) => {
      if (el.getAttribute('aria-label') || el.getAttribute('aria-labelledby') || el.getAttribute('title'))
        return true;
      if ((el.textContent || '').trim()) return true;
      if (el.querySelector('img[alt]:not([alt=""]), svg[aria-label], [aria-label]')) return true;
      if (el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`)) return true;
      if (el.closest('label')) return true;
      if (el.getAttribute('placeholder')) return true;
      return false;
    };
    for (const el of document.querySelectorAll(sel)) {
      const r = el.getBoundingClientRect();
      const st = getComputedStyle(el);
      if (r.width < 1 || r.height < 1 || st.visibility === 'hidden' || st.display === 'none') continue;
      if (el.closest('[aria-hidden="true"], [inert]')) continue;
      if (!named(el)) issues.push({ kind: 'unnamed-control', detail: describe(el) });
      const box = clipper(el)?.getBoundingClientRect();
      const visibleTop = Math.max(0, box?.top ?? 0);
      const visibleBottom = Math.min(H, box?.bottom ?? H);
      // horizontally out of the window, with no scrolling container to bring it in
      if ((r.right > W + 1 || r.left < -1) && !scrollsX(el))
        issues.push({ kind: 'clipped-control', detail: `${describe(el)} at x=${Math.round(r.left)}..${Math.round(r.right)}` });
      // covered: only for controls whose centre is actually on screen
      const cx = r.left + r.width / 2;
      const cy = r.top + r.height / 2;
      if (cx < 0 || cx > W || cy < visibleTop || cy > visibleBottom || cy > H) continue;
      if (box && (cx < box.left || cx > box.right)) continue;
      const hit = document.elementFromPoint(cx, cy);
      if (hit && hit !== el && !el.contains(hit) && !hit.contains(el)) {
        // a dialog or popover covering the page is normal, and so is the task pane, which opens
        // full-screen over the list below the md breakpoint (768 px) by design
        const cover = hit.closest('[role=dialog], [data-radix-popper-content-wrapper], [data-state=open]');
        const pane = hit.closest('aside[aria-label="Task details"]');
        if (pane && !pane.contains(el) && W < 768) continue;
        // a control scrolled under a sticky column or header is reachable by scrolling back
        const sticky = (n) => {
          for (let p = n; p && p !== document.body; p = p.parentElement)
            if (getComputedStyle(p).position === 'sticky') return p;
          return null;
        };
        const s = sticky(hit);
        if (s && !s.contains(el) && scrollsX(el)) continue;
        if (!cover || !cover.contains(el))
          issues.push({ kind: 'covered-control', detail: `${describe(el)} under ${describe(hit)}` });
      }
    }
    return issues;
  });
}

const browser = await chromium.launch();
const summary = { base, startedAt: new Date().toISOString(), screens: 0, findings };
try {
  for (const user of users) {
    for (const [vname, viewport] of Object.entries(VIEWPORTS)) {
      for (const scheme of ['light', 'dark']) {
        const { ctx, page } = await login(browser, user, viewport, scheme);
        const consoleErrors = [];
        page.on('console', (m) => m.type() === 'error' && consoleErrors.push(m.text()));
        page.on('pageerror', (e) => consoleErrors.push(String(e)));
        for (const [name, path] of await screens(page)) {
          if (vname !== '1280x620' && !full && !KEY.has(name)) continue;
          consoleErrors.length = 0;
          await page.goto(base + path);
          await page.waitForLoadState('networkidle').catch(() => {});
          await page.waitForTimeout(400);
          const tag = `${user}-${vname}-${scheme}-${name}`;
          await page.screenshot({ path: join(out, `${tag}.jpg`), type: 'jpeg', quality: 55 });
          summary.screens++;
          for (const i of await checkControls(page)) add({ screen: tag, ...i });
          if (scheme === 'light' || vname === '1280x620') {
            const axe = await new AxeBuilder({ page })
              .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
              .analyze()
              .catch((e) => ({ violations: [{ id: 'axe-failed', impact: 'serious', help: String(e), nodes: [] }] }));
            for (const v of axe.violations.filter((v) => ['serious', 'critical'].includes(v.impact)))
              add({
                screen: tag,
                kind: `axe:${v.id}`,
                detail: `${v.help} (${v.nodes.length}): ${v.nodes
                  .slice(0, 3)
                  .map((n) => n.target.join(' '))
                  .join(' | ')}`,
              });
          }
          for (const e of consoleErrors) add({ screen: tag, kind: 'console-error', detail: e.slice(0, 300) });
        }
        await ctx.close();
      }
    }
  }
} finally {
  await browser.close();
}
summary.finishedAt = new Date().toISOString();
writeFileSync(join(out, 'report.json'), JSON.stringify(summary, null, 2));
const byKind = {};
for (const f of findings) byKind[f.kind] = (byKind[f.kind] ?? 0) + 1;
const md = [
  `# UI audit`,
  ``,
  `${summary.screens} screens, ${findings.length} findings (${summary.startedAt}).`,
  ``,
  ...Object.entries(byKind).map(([k, n]) => `- ${k}: ${n}`),
  ``,
  ...findings.map((f) => `- \`${f.screen}\` **${f.kind}**: ${f.detail}`),
];
writeFileSync(join(out, 'report.md'), md.join('\n') + '\n');
console.log(`${summary.screens} screens, ${findings.length} findings`, byKind);
