// Initial-JS budget (performance.md): the gzip size of every script the built index.html loads
// up front (the entry plus its modulepreloads) must stay within the budget. Lazy chunks don't
// count. Run after `pnpm build`:  node tools/perf/bundle-budget.mjs [apps/web/dist] [--budget 300]
import { readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { gzipSync } from 'node:zlib';

const args = process.argv.slice(2);
const dist = resolve(args.find((a) => !a.startsWith('--')) ?? 'apps/web/dist');
const i = args.indexOf('--budget');
const budgetKb = i >= 0 ? Number(args[i + 1]) : 300;

const html = readFileSync(join(dist, 'index.html'), 'utf8');
const files = [...new Set([...html.matchAll(/(?:src|href)="[^"]*?(assets\/[^"]+\.js)"/g)].map((m) => m[1]))];
const sizes = files
  .map((f) => [f, gzipSync(readFileSync(join(dist, f))).length])
  .sort((a, b) => b[1] - a[1]);
const total = sizes.reduce((a, [, n]) => a + n, 0) / 1024;
for (const [f, n] of sizes.slice(0, 8)) console.log(`${(n / 1024).toFixed(1).padStart(7)} KB  ${f}`);
console.log(`initial JS: ${total.toFixed(1)} KB gzip in ${files.length} files (budget ${budgetKb} KB)`);
if (total > budgetKb) {
  console.error(`over budget by ${(total - budgetKb).toFixed(1)} KB`);
  process.exit(1);
}
