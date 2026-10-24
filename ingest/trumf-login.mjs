#!/usr/bin/env node
// Log in to trumf.no YOURSELF, once, and keep the session for ingest/trumf.py.
//
//   node ingest/trumf-login.mjs
//
// Opens a normal, visible Chrome window with a fresh, temporary profile on trumf.no. You click "Logg inn" and log in
// with your own phone number, password and SMS code, exactly as on the website. Nothing is typed or clicked for you,
// and no captcha or protection is touched. When the window shows you as logged in, this script copies the trumf.no
// cookies to ~/.matkassa/trumf_state.json (chmod 600, outside the repo) and closes the window. The temporary Chrome
// profile is deleted. Cookie values are never printed. No dependencies: Node 22+ and Google Chrome.
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const CHROME = process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const STATE = process.env.MATKASSA_TRUMF_STATE || path.join(os.homedir(), '.matkassa', 'trumf_state.json');
const START = process.env.MATKASSA_TRUMF_START || 'https://www.trumf.no/'; // override only for the FAKE test
const TIMEOUT_MIN = 10;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!fs.existsSync(CHROME)) { console.error(`Fant ikke Chrome (${CHROME}). Sett CHROME=… og prøv igjen.`); process.exit(1); }
const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'matkassa-trumf-login-'));
const extra = process.env.MATKASSA_CHROME_ARGS ? JSON.parse(process.env.MATKASSA_CHROME_ARGS) : []; // test only (headless + fake host)
const chrome = spawn(CHROME, [...extra, '--remote-debugging-port=0', `--user-data-dir=${profile}`, '--no-first-run', '--no-default-browser-check', '--new-window', START], { stdio: ['ignore', 'ignore', 'pipe'] });
const cleanup = () => { try { chrome.kill(); } catch {} setTimeout(() => fs.rmSync(profile, { recursive: true, force: true }), 500); };
process.on('SIGINT', () => { cleanup(); process.exit(130); });

const wsUrl = await new Promise((resolve, reject) => {
  let buf = '';
  const t = setTimeout(() => reject(new Error('Chrome startet ikke')), 20000);
  chrome.stderr.on('data', (d) => { buf += d; const m = /DevTools listening on (ws:\/\/\S+)/.exec(buf); if (m) { clearTimeout(t); resolve(m[1]); } });
  chrome.on('exit', () => reject(new Error('Chrome ble lukket')));
});
const ws = new WebSocket(wsUrl);
await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
let seq = 0;
const pending = new Map();
ws.onmessage = (ev) => { const m = JSON.parse(ev.data); if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.reject(new Error(m.error.message)) : p.resolve(m.result); } };
const send = (method, params = {}) => new Promise((resolve, reject) => { const id = ++seq; pending.set(id, { resolve, reject }); ws.send(JSON.stringify({ id, method, params })); });

console.log('Et Chrome-vindu med trumf.no er åpnet. Logg inn selv (telefon, passord og SMS-kode).');
console.log(`Venter til du er logget inn (maks ${TIMEOUT_MIN} min) … Lukk vinduet for å avbryte.`);

const isTrumf = (c) => /(^|\.)trumf\.no$/.test(String(c.domain).replace(/^\./, ''));
const end = Date.now() + TIMEOUT_MIN * 60 * 1000;
let ok = false;
let cookies = [];
let closed = false;
chrome.on('exit', () => { closed = true; });
while (Date.now() < end && !closed) {
  await sleep(2000);
  try {
    ({ cookies } = await send('Storage.getCookies'));
  } catch { continue; }
  // NextAuth keeps the login in a (possibly chunked) session-token cookie on www.trumf.no.
  if (cookies.some((c) => isTrumf(c) && /next-auth\.session-token/.test(c.name) && c.value)) { ok = true; break; }
}
if (!ok) {
  console.error(closed ? 'Vinduet ble lukket før innloggingen var ferdig. Ingenting er lagret.' : 'Tidsavbrudd. Ingenting er lagret.');
  cleanup();
  process.exit(2);
}
await sleep(1500); // let the site finish setting its cookies
({ cookies } = await send('Storage.getCookies'));
const keep = cookies.filter(isTrumf).map((c) => ({ name: c.name, value: c.value, domain: c.domain, path: c.path, expires: c.expires > 0 ? c.expires : null, secure: c.secure, httpOnly: c.httpOnly }));
fs.mkdirSync(path.dirname(STATE), { recursive: true, mode: 0o700 });
fs.chmodSync(path.dirname(STATE), 0o700);
const tmp = STATE + '.tmp';
fs.writeFileSync(tmp, JSON.stringify({ saved: new Date().toISOString(), cookies: keep }), { mode: 0o600 });
fs.renameSync(tmp, STATE);
fs.chmodSync(STATE, 0o600);
const longest = Math.max(...keep.filter((c) => c.expires).map((c) => c.expires), 0);
console.log(`Innlogget. Lagret Trumf-økta (${keep.length} informasjonskapsler, ingen verdier vist) i ${STATE.replace(os.homedir(), '~')}.`);
if (longest) console.log(`Økta varer til omtrent ${new Date(longest * 1000).toLocaleDateString('nb-NO')} hvis Trumf ikke logger deg ut før.`);
console.log('Test: python3 ingest/trumf.py --check');
ws.close();
cleanup();
process.exit(0);
