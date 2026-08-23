import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.dirname(fileURLToPath(import.meta.url));
const read = (name) => fs.existsSync(path.join(root, name)) ? fs.readFileSync(path.join(root, name), 'utf8') : '';
const html = read('index.html');
const css = read('styles.css');
const js = read('app.js');

const checks = [];
const expect = (condition, message) => checks.push({ condition: Boolean(condition), message });

expect(html.includes('id="app-sidebar"'), 'Missing prototype shell: app-sidebar');
expect(html.includes('id="workspace"'), 'Missing prototype shell: workspace');
expect(html.includes('id="evidence-panel"'), 'Missing prototype shell: evidence-panel');
expect(html.includes('id="run-drawer"'), 'Missing prototype shell: run-drawer');
expect((html.match(/data-view=/g) || []).length >= 9, 'Missing prototype shell: nine navigation entries');
expect(html.includes('id="runtime-mode"'), 'Missing prototype shell: runtime-mode');

for (const view of ['dashboard','projects','literature','verify','formalize','writing','review','education','runs']) {
  expect(html.includes(`id="view-${view}"`), `Missing view: ${view}`);
}

for (const token of ['FULL','LOCAL_ENGINE','BROWSER_LOCAL','UNAVAILABLE']) {
  expect(js.includes(token), `Missing runtime mode: ${token}`);
}

for (const behavior of ['navigate','setRuntimeMode','toggleRunDrawer','openModal','startLeanBuild','cancelLeanBuild','runEducationPreflight']) {
  expect(js.includes(`function ${behavior}`) || js.includes(`const ${behavior}`), `Missing behavior: ${behavior}`);
}

for (const content of ['不是论文排名','Lean 4','Mathlib','k≥20','formal_pending','证据账本','capabilities_used','missing_capabilities']) {
  expect((html + js).includes(content), `Missing required content: ${content}`);
}

expect(css.includes(':focus-visible'), 'Missing accessible focus state');
expect(css.includes('@media'), 'Missing responsive styles');
expect(css.includes('--status-pass'), 'Missing semantic status tokens');

const failed = checks.filter((check) => !check.condition);
if (failed.length) {
  console.error(`FAIL ${failed.length}/${checks.length}`);
  for (const failure of failed) console.error(`- ${failure.message}`);
  process.exit(1);
}

console.log(`PASS ${checks.length}/${checks.length} prototype assertions`);
