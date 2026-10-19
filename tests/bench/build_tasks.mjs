// Builds tests/bench/lead-route.jsonl by EXECUTING the workflow's own Code
// nodes ("Validate lead", "Website summary", "Build scoring request") with the
// Settings node's values, and by fetching the mock sites through the same
// mock_sites_base URL the workflow uses. Nothing is retyped.
//
// Run from the repo root with the mock sites up:
//   python tests/mock_sites/server.py   (other terminal)
//   node tests/bench/build_tasks.mjs
import fs from 'node:fs';
import path from 'node:path';

const REPO = process.argv[2] || path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')), '..', '..');
const OUT = path.join(REPO, 'tests', 'bench', 'lead-route.jsonl');
const wf = JSON.parse(fs.readFileSync(path.join(REPO, 'workflows', 'lead-qualifier.json'), 'utf8'));
const node = (name) => wf.nodes.find((n) => n.name === name);

// Settings node -> plain object, exactly as n8n's Set node would output it.
const settings = {};
for (const a of node('Settings').parameters.assignments.assignments) settings[a.name] = a.value;

const codeOf = (name) => node(name).parameters.jsCode;
// Run a Code node: it sees $('Node name').first().json and $input.first().json and returns [{ json }].
function runCode(name, nodes, input) {
  const $ = (n) => ({ first: () => ({ json: nodes[n] }) });
  const $input = { first: () => ({ json: input }) };
  const fn = new Function('$', '$input', codeOf(name));
  return fn($, $input)[0].json;
}

// Same payload the test runner sends (tests/run_tests.py build_payload), minus test flags, which only mark excluded leads.
function payload(caseObj) {
  const lead = { ...caseObj.lead };
  if (typeof lead.message === 'object') lead.message = lead.message.repeat.repeat(lead.message.times);
  lead.source = 'test-run';
  return lead;
}

// "Read website" node: HTTP GET, 8 s timeout, on error continue with { error }.
async function readWebsite(url) {
  if (!url) return {};
  try {
    const r = await fetch(url, { signal: AbortSignal.timeout(node('Read website').parameters.options.timeout), redirect: 'follow' });
    return { html: await r.text() };
  } catch (e) {
    return { error: { message: String(e && e.cause ? e.cause.message || e.message : e.message) } };
  }
}

const EXCLUDE = new Set(['broken_input', 'duplicate', 'simulated_bad_ai_output', 'simulated_api_error']);
const sets = [['set1', 'tests/leads.json'], ['set2', 'tests/leads-set2.json']];
const lines = [];
let schema = null;
for (const [setName, file] of sets) {
  const data = JSON.parse(fs.readFileSync(path.join(REPO, file), 'utf8'));
  for (const c of data.leads) {
    if (EXCLUDE.has(c.category)) continue;
    const body = payload(c);
    const v = runCode('Validate lead', { 'New lead': { body }, Settings: settings });
    if (!v.valid) throw new Error(`${c.id} failed validation: ${v.errors}`);
    const r = await readWebsite(v.fetch_url);
    const w = runCode('Website summary', { 'Validate lead': v }, r);
    const b = runCode('Build scoring request', { Settings: settings, 'Validate lead': v, 'Website summary': w });
    const req = b.request;
    if (req.messages.length !== 1 || req.messages[0].role !== 'user') throw new Error('unexpected message shape');
    schema = req.output_config.format.schema;
    lines.push(JSON.stringify({
      id: c.id,
      set: setName,
      category: c.category,
      website_status: w.website_status,
      system: req.system,
      prompt: req.messages[0].content,
      check: { type: 'route', value: c.expected },
    }));
    console.error(`${c.id.padEnd(6)} ${c.category.padEnd(18)} website=${w.website_status.padEnd(12)} expected=${c.expected.join('|')}`);
  }
}
fs.mkdirSync(path.dirname(OUT), { recursive: true });
const header = `# llm-bench task file for the lead-qualifier model study. Built by executing the workflow's own Code nodes; see tests/bench/README.md. Labels owner-reviewed 2026-10-19.`;
fs.writeFileSync(OUT, header + '\n' + lines.join('\n') + '\n');
fs.writeFileSync(path.join(REPO, 'tests', 'bench', 'output-schema.json'), JSON.stringify({
  about: "Exact JSON schema the workflow's 'Build scoring request' node passes to the Anthropic API as output_config.format (type json_schema). The system prompt does not describe the output format; the workflow relies on this schema. A fair benchmark must enforce it the same way or the model may not answer in JSON at all.",
  model: settings.model, effort: settings.effort, max_tokens: 4000,
  thresholds: { min_confidence: settings.min_confidence, high_fit_min: settings.high_fit_min, low_fit_max: settings.low_fit_max },
  schema,
}, null, 2) + '\n');
console.error(`wrote ${lines.length} tasks to ${OUT}`);
