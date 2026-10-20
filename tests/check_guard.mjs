// Checks the code guard in the "Decide route" node against every test lead and mock page,
// by EXECUTING the workflow's own Code nodes ("Validate lead", "Website summary", "Decide route")
// with a perfect AI answer (score 95, sure, no manipulation flag): the worst case for the guard.
//   - every prompt_injection case must be stopped (route review), whatever the AI says;
//   - no other AI-routed case may be stopped (a stopped good lead would lose high_fit).
// Code-path cases are listed for information only. No server, no n8n, no network.
//
// Run from the repo root:
//   node tests/check_guard.mjs [lead files...] [--extra <holdout_sites.json>]
// Default lead files: the visible set and the trigger set. Exit 0 = OK, 1 = guard wrong.
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

const REPO = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')), '..');
const args = process.argv.slice(2);
const extraAt = args.indexOf('--extra');
const extra = extraAt >= 0 ? args.splice(extraAt, 2)[1] : null;
const files = args.length ? args : ['tests/leads.json', 'tests/leads-set2.json', 'tests/leads-injection.json',
  'tests/leads-code.json', 'tests/leads-trigger.json'];

const wf = JSON.parse(fs.readFileSync(path.join(REPO, 'workflows', 'lead-qualifier.json'), 'utf8'));
const node = (name) => wf.nodes.find((n) => n.name === name);
const settings = {};
for (const a of node('Settings').parameters.assignments.assignments) settings[a.name] = a.value;
function runCode(name, nodes, input) {
  const $ = (n) => ({ first: () => ({ json: nodes[n] }) });
  const $input = { first: () => ({ json: input }) };
  return new Function('$', '$input', node(name).parameters.jsCode)($, $input)[0].json;
}

// Pages exactly as tests/mock_sites/server.py serves them.
const dumpArgs = [path.join(REPO, 'tests', 'mock_sites', 'server.py'), ...(extra ? ['--extra', extra] : []), '--dump'];
const sites = JSON.parse(execFileSync('python', dumpArgs, { encoding: 'utf8' }));
const page = (title, body) => `<!doctype html><html><head><title>${title}</title>`
  + `<meta name='description' content='${title}'></head><body><h1>${title}</h1><p>${body}</p></body></html>`;

const CODE_PATH = new Set(['broken_input', 'duplicate', 'simulated_bad_ai_output', 'simulated_api_error']);
const perfectAi = { ai_valid: true, ai_error: '', model_used: 'test',
  ai: { fit_score: 95, confidence: 0.95, reason: 'test', industry: 'test', company_size: '50-249',
        signals: [], red_flags: [], manipulation_attempt: false } };
const wrong = [];
let stopped = 0, passed = 0;
for (const f of files) {
  for (const c of JSON.parse(fs.readFileSync(path.join(REPO, f), 'utf8')).leads) {
    const body = { ...c.lead, source: 'test-run' };
    if (typeof body.message === 'object') body.message = body.message.repeat.repeat(body.message.times);
    const v = runCode('Validate lead', { 'New lead': { body }, Settings: settings });
    if (!v.valid) continue;
    const host = (v.fetch_url.split('/').pop() || '').toLowerCase();
    const site = sites[host];
    const w = runCode('Website summary', { 'Validate lead': v }, site ? { html: page(site[0], site[1]) } : { error: {} });
    const d = runCode('Decide route', { Settings: settings, 'Validate lead': v, 'Website summary': w }, perfectAi);
    const isStopped = d.route === 'review';
    isStopped ? stopped++ : passed++;
    const tag = `${c.id} (${c.category}, ${f})`;
    if (c.category === 'prompt_injection' && !isStopped) wrong.push(`NOT STOPPED: ${tag}`);
    else if (!CODE_PATH.has(c.category) && c.category !== 'prompt_injection' && isStopped)
      wrong.push(`GOOD LEAD STOPPED: ${tag}, patterns ${d.guard_hits}`);
    else if (CODE_PATH.has(c.category) && isStopped) console.log(`note: ${tag} stopped, patterns ${d.guard_hits}`);
  }
}
for (const x of wrong) console.log(x);
console.log(`${wrong.length ? 'GUARD WRONG' : 'OK'}: ${stopped} stopped, ${passed} passed with a perfect AI answer`);
process.exit(wrong.length ? 1 : 0);
