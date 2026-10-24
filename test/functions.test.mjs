// Smoke test for the Supabase Edge Functions under Node (type stripping), with a stubbed Deno runtime and a stubbed
// fetch that plays Supabase (PostgREST + Auth) and trumf.no with FAKE fixtures. This checks the functions' own logic
// (auth, secrets never echoed, rows go to the right user, status updates); it does NOT prove they run on Supabase.
// Run: node test/functions.test.mjs
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const FAKE = path.join(ROOT, 'test', 'fake');
let failed = 0;
const ok = (c, name, d = '') => { if (!c) failed++; console.log(`${c ? 'PASS' : 'FAIL'} ${name}${!c && d ? ` — ${d}` : ''}`); };

const ENV = { SUPABASE_URL: 'https://fn-fake.supabase.co', SUPABASE_ANON_KEY: 'FAKE-anon', SUPABASE_SERVICE_ROLE_KEY: 'FAKE-service-role', CRON_SECRET: 'FAKE-cron-secret-0123456789' };
const handlers = {};
let current = null;
globalThis.Deno = { env: { get: (k) => ENV[k] }, serve: (h) => { handlers[current] = h; } };
const USER = '00000000-0000-0000-0000-00000000000a';
const calls = [];
const secretStore = { trumf: JSON.stringify({ cookies: [{ name: 'next-auth.session-token', value: 'FAKE-SESSION-1', domain: 'www.trumf.no', path: '/' }] }) };
const res = (status, body, headers = {}) => new Response(status === 204 ? null : typeof body === 'string' ? body : JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } });
globalThis.fetch = async (url, init = {}) => {
  const u = new URL(url);
  const h = Object.fromEntries(Object.entries(init.headers || {}).map(([k, v]) => [k.toLowerCase(), v]));
  calls.push({ url: String(url), method: init.method || 'GET', h, body: init.body ? String(init.body) : '' });
  if (u.hostname === 'fn-fake.supabase.co') {
    if (u.pathname === '/auth/v1/user') return h.authorization === 'Bearer FAKE-USER-JWT' ? res(200, { id: USER, email: 'ole-FAKE@example.invalid' }) : res(401, { msg: 'bad jwt' });
    if (h.authorization !== 'Bearer FAKE-service-role') return res(401, { message: 'service role expected' });
    if (u.pathname === '/rest/v1/chain_connections') return res(200, [{ user_id: USER, chain: 'trumf' }]);
    if (u.pathname === '/rest/v1/rpc/matkassa_read_chain_token') return res(200, JSON.stringify(secretStore[JSON.parse(init.body).p_chain]));
    if (u.pathname === '/rest/v1/rpc/matkassa_store_chain_token') { const b = JSON.parse(init.body); secretStore[b.p_chain] = b.p_token; return res(204, ''); }
    if (u.pathname === '/rest/v1/rpc/matkassa_fetch_result') return res(204, '');
    if (u.pathname === '/rest/v1/receipts' && (init.method || 'GET') === 'GET') return res(200, []);
    if (u.pathname === '/rest/v1/receipts') return res(201, '');
  }
  if (u.hostname === 'www.trumf.no') {
    if (!/next-auth\.session-token=FAKE-SESSION-[12]/.test(h.cookie || '')) return res(302, '', { Location: 'https://id.trumf.no/connect/authorize' });
    if (u.pathname === '/api/auth/session') return res(200, { accessToken: 'FAKE' });
    if (u.pathname === '/trumf-profil/kvitteringer') return res(200, fs.readFileSync(path.join(FAKE, 'trumf-rsc-list-FAKE.txt'), 'utf8'), { 'Set-Cookie': 'next-auth.session-token=FAKE-SESSION-2; Path=/; Max-Age=2592000' });
    if (u.pathname.endsWith('FAKE-B1001')) return res(200, fs.readFileSync(path.join(FAKE, 'trumf-rsc-detail-FAKE.txt'), 'utf8'));
    return res(200, '0:{}');
  }
  return res(404, {});
};
const origSetTimeout = globalThis.setTimeout;
globalThis.setTimeout = (fn, ms, ...a) => origSetTimeout(fn, Math.min(ms, 5), ...a); // no real waiting in the test

for (const f of ['connect', 'fetch-receipts']) { current = f; await import(path.join(ROOT, 'supabase', 'functions', f, 'index.ts')); }

// connect
let r = await handlers.connect(new Request('https://x/connect', { method: 'POST', headers: { Authorization: 'Bearer WRONG' }, body: '{}' }));
ok(r.status === 401, 'connect: without a valid user JWT → 401');
const secret = JSON.stringify({ refresh_token: 'FAKE-REMA-REFRESH-TOKEN-xyz' });
r = await handlers.connect(new Request('https://x/connect', { method: 'POST', headers: { Authorization: 'Bearer FAKE-USER-JWT' }, body: JSON.stringify({ chain: 'rema', secret }) }));
const body = await r.text();
ok(r.status === 200 && !body.includes('FAKE-REMA-REFRESH'), 'connect: stores the session and never echoes it', body);
const store = calls.find((c) => c.url.endsWith('/rpc/matkassa_store_chain_token'));
ok(store && JSON.parse(store.body).p_user === USER && JSON.parse(store.body).p_token === secret, 'connect: stored for the caller (user id from their own JWT, not from the request)');
r = await handlers.connect(new Request('https://x/connect', { method: 'POST', headers: { Authorization: 'Bearer FAKE-USER-JWT' }, body: JSON.stringify({ chain: 'coop', secret }) }));
ok(r.status === 400, 'connect: only trumf/rema (no Coop scraping)');

// weekly pull
calls.length = 0;
r = await handlers['fetch-receipts'](new Request('https://x/f', { method: 'POST', headers: { 'x-cron-secret': 'nope' } }));
ok(r.status === 403 && !calls.length, 'fetch-receipts: wrong cron secret → 403, nothing touched');
r = await handlers['fetch-receipts'](new Request('https://x/f', { method: 'POST', headers: { 'x-cron-secret': ENV.CRON_SECRET } }));
ok(r.status === 200, 'fetch-receipts: runs with the cron secret');
const up = calls.find((c) => c.url.includes('/rest/v1/receipts?on_conflict') && c.method === 'POST');
const rows = up ? JSON.parse(up.body) : [];
ok(rows.length === 2 && rows.every((x) => x.user_id === USER && x.data.source === 'trumf') && rows[0].data.lines.length === 3, 'fetch-receipts: new Trumf receipts with lines into that user\'s rows', rows.length);
ok(/ignore-duplicates/.test(up?.h.prefer || ''), 'fetch-receipts: never overwrites receipts already there');
ok(JSON.parse(secretStore.trumf).cookies.some((c) => c.value === 'FAKE-SESSION-2'), 'fetch-receipts: keeps the rotated Trumf session (re-encrypted in Vault)');
const result = calls.find((c) => c.url.endsWith('/rpc/matkassa_fetch_result'));
ok(result && JSON.parse(result.body).p_error === null, 'fetch-receipts: marks the connection as fetched');
secretStore.trumf = JSON.stringify({ cookies: [{ name: 'next-auth.session-token', value: 'FAKE-OLD', domain: 'www.trumf.no' }] });
calls.length = 0;
await handlers['fetch-receipts'](new Request('https://x/f', { method: 'POST', headers: { 'x-cron-secret': ENV.CRON_SECRET } }));
const res2 = calls.find((c) => c.url.endsWith('/rpc/matkassa_fetch_result'));
ok(res2 && /expired/.test(JSON.parse(res2.body).p_error), 'fetch-receipts: an expired login is recorded (status → expired), no crash');
console.log(failed ? `\n${failed} FAILED` : '\nAll Edge Function smoke tests passed');
process.exit(failed ? 1 : 0);
