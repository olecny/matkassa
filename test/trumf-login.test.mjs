// Test for ingest/trumf-login.mjs without touching trumf.no: headless Chrome maps www.trumf.no to a FAKE local page
// that "logs in" by itself after a moment (sets a NextAuth-style session cookie). Checks that the script notices,
// saves only trumf.no cookies to a 0600 file, never prints the values, and cleans up. Run: node test/trumf-login.test.mjs
import http from 'node:http';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
let failed = 0;
const ok = (c, name, d = '') => { if (!c) failed++; console.log(`${c ? 'PASS' : 'FAIL'} ${name}${!c && d ? ` — ${d}` : ''}`); };

const page = `<!doctype html><title>FAKE trumf.no</title><p>FAKE login page (test)</p>
<script>setTimeout(() => { document.cookie = 'next-auth.session-token=FAKE-LOGIN-VALUE-123; path=/; max-age=3600'; document.cookie = 'other=FAKE-OTHER; path=/'; }, 1500);</script>`;
const server = http.createServer((req, res) => { res.writeHead(200, { 'Content-Type': 'text/html' }); res.end(page); });
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const port = server.address().port;
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'matkassa-trumf-login-test-'));
const state = path.join(tmp, 'sub', 'trumf_state.json');

const child = spawn(process.execPath, [path.join(ROOT, 'ingest', 'trumf-login.mjs')], {
  env: { ...process.env, MATKASSA_TRUMF_STATE: state, MATKASSA_TRUMF_START: `http://www.trumf.no:${port}/`,
    MATKASSA_CHROME_ARGS: JSON.stringify(['--headless=new', '--host-resolver-rules=MAP www.trumf.no 127.0.0.1']) },
  stdio: ['ignore', 'pipe', 'pipe'],
});
let out = '';
child.stdout.on('data', (d) => (out += d));
child.stderr.on('data', (d) => (out += d));
const code = await new Promise((r) => { const t = setTimeout(() => { child.kill(); r('timeout'); }, 60000); child.on('exit', (c) => { clearTimeout(t); r(c); }); });
server.close();

ok(code === 0, 'trumf-login: notices the login and exits 0', `${code}: ${out.slice(-300)}`);
const saved = fs.existsSync(state) ? JSON.parse(fs.readFileSync(state, 'utf8')) : null;
ok(saved && saved.cookies.some((c) => c.name === 'next-auth.session-token' && c.value === 'FAKE-LOGIN-VALUE-123'), 'trumf-login: saves the session cookie');
ok(saved && saved.cookies.every((c) => /trumf\.no$/.test(String(c.domain).replace(/^\./, ''))), 'trumf-login: only trumf.no cookies');
ok(fs.existsSync(state) && (fs.statSync(state).mode & 0o777) === 0o600 && (fs.statSync(path.dirname(state)).mode & 0o777) === 0o700, 'trumf-login: file 0600 in a 0700 folder');
ok(!out.includes('FAKE-LOGIN-VALUE') && !out.includes('FAKE-OTHER') && /Innlogget/.test(out), 'trumf-login: never prints cookie values');
fs.rmSync(tmp, { recursive: true, force: true });
console.log(failed ? `\n${failed} FAILED` : '\nAll trumf-login tests passed');
process.exit(failed ? 1 : 0);
