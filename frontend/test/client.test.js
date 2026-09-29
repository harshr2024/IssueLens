import test from 'node:test';
import assert from 'node:assert/strict';
import { requestTriage, safeIssueUrl } from '../src/client.js';
test('posts to the same-origin API and preserves result metadata', async () => {
  const result = { candidates: [{ number: 12 }], missing_information: [] };
  assert.deepEqual(await requestTriage({ title: 'hello' }, async (url, options) => {
    assert.equal(url, '/triage'); assert.equal(JSON.parse(options.body).title, 'hello');
    return new Response(JSON.stringify(result));
  }), result);
});
test('shows service and network errors', async () => {
  await assert.rejects(requestTriage({}, async () => new Response(JSON.stringify({detail:'Ollama unavailable'}), {status:503})), /Ollama unavailable/);
  await assert.rejects(requestTriage({}, async () => { throw new Error('offline'); }), /API could not be reached/);
  await assert.rejects(requestTriage({}, async () => new Response('{}')), /unexpected response/);
});
test('only links to real GitHub issue URL shapes', () => {
  assert.equal(safeIssueUrl('javascript:alert(1)'), null);
  assert.equal(safeIssueUrl('https://evil.example/issues/1'), null);
  assert.equal(safeIssueUrl('https://github.com/pallets/flask/issues/1'), 'https://github.com/pallets/flask/issues/1');
});
