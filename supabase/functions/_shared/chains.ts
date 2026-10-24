// Server-side receipt fetchers for the weekly pull (Supabase Edge Functions, Deno).
// STATUS: written, NOT tested against Supabase or the real chain APIs (no project, no Deno here). Mirrors the logic
// of ingest/rema.py and ingest/trumf.py, which are tested against FAKE servers (test/ingest.test.py).
// Unofficial APIs, the user's own data only, gentle pacing, nothing bypassed.

export type Line = { name: string; ean: string | null; qty: number | null; unit: string | null; amount: number; group: string | null; category: null };
export type Receipt = { id: string; source: string; chain: string; store: string; date: string; time: string | null; total: number; currency: 'NOK'; category: null; lines: Line[] };

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const oslo = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Europe/Oslo', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
function localWhen(v: unknown): { date: string | null; time: string | null } {
  if (v == null || v === '$undefined') return { date: null, time: null };
  const s = String(v).replace(/^\$D/, '');
  const d = typeof v === 'number' ? new Date(v > 1e11 ? v : v * 1000) : new Date(s);
  if (Number.isNaN(d.getTime())) return { date: /^\d{4}-\d{2}-\d{2}/.test(s) ? s.slice(0, 10) : null, time: null };
  const [date, time] = oslo.format(d).split(' ');
  return { date, time: time.slice(0, 5) };
}
const num = (v: unknown): number | null => {
  if (v == null || v === '' || v === '$undefined') return null;
  if (typeof v === 'number') return v;
  const n = parseFloat(String(v).replace(/[\s ]|kr/g, '').replace(',', '.'));
  return Number.isFinite(n) ? n : null;
};

async function retrying(url: string, init: RequestInit, tries = 4): Promise<Response> {
  for (let i = 0; ; i++) {
    try {
      const res = await fetch(url, { ...init, redirect: 'manual' });
      if ([429, 500, 502, 503, 504].includes(res.status) && i < tries - 1) { await sleep(2 ** i * 3000); continue; }
      return res;
    } catch (e) {
      if (i === tries - 1) throw e;
      await sleep(2 ** i * 3000);
    }
  }
}

/* ---------- REMA 1000 (api.rema.no, Firebase token from the Æ login) ---------- */
// Public app keys from the REMA app (documented in rema1000-cli), the same as in ingest/rema.py. Not user secrets.
const REMA_API = 'https://api.rema.no';
const BELLA_KEY = 'fb5e24884b504d0bad761098f77e6605';
const FIREBASE_API_KEY = 'AIzaSyBi9PlJsUo5FAqljPHuh0WQCsaOSW4rFQs';

export async function fetchRema(secret: string, knownIds: Set<string>, max = 40): Promise<{ receipts: Receipt[]; secret: string }> {
  const s = JSON.parse(secret) as { refresh_token: string; device_id?: string };
  const tok = await retrying(`https://securetoken.googleapis.com/v1/token?key=${FIREBASE_API_KEY}`, {
    method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ grant_type: 'refresh_token', refresh_token: s.refresh_token }),
  });
  if (!tok.ok) throw new Error(tok.status === 400 ? 'expired: REMA login' : `REMA token ${tok.status}`);
  const t = await tok.json();
  const next = JSON.stringify({ ...s, refresh_token: t.refresh_token || s.refresh_token });
  const h = {
    Authorization: `Bearer ${t.id_token}`, 'Ocp-Apim-Subscription-Key': BELLA_KEY, 'X-App': 'Bella', 'X-Platform': 'iOS',
    'X-App-Version': '3.13.0.1181', 'X-Device-ID': s.device_id || crypto.randomUUID().toUpperCase(),
    'X-Correlation-ID': crypto.randomUUID().toUpperCase(), 'Accept-Language': 'no', Accept: 'application/json',
  };
  const heads = await retrying(`${REMA_API}/v1/bella/transaction/v2/heads`, { headers: h });
  if (!heads.ok) throw new Error(`REMA heads ${heads.status}`);
  const hj = await heads.json();
  const txs: Record<string, unknown>[] = Array.isArray(hj) ? hj : hj.transactions || [];
  const out: Receipt[] = [];
  for (const head of txs) {
    const tid = head.id ?? head.transactionId ?? head.receiptId;
    if (tid == null || knownIds.has(`rema-${tid}`)) continue;
    if (out.length >= max) break;
    const rowsRes = await retrying(`${REMA_API}/v1/bella/transaction/v2/rows/${tid}`, { headers: h });
    if (!rowsRes.ok) continue;
    const rows = await rowsRes.json();
    const when = localWhen(head.purchaseDate ?? head.transactionDate ?? head.date);
    if (!when.date) continue;
    const lines: Line[] = (rows.rows || []).map((r: Record<string, unknown>) => ({
      name: String(r.productDescription || r.prodtxt1 || 'Ukjent vare').trim(),
      ean: /^\d{8,14}$/.test(String(r.prodtxt3 || '')) ? String(r.prodtxt3) : null,
      qty: num(r.unit === 'Kg' || r.unit === 'KG' ? r.volume : r.pieces),
      unit: r.unit === 'Kg' || r.unit === 'KG' ? 'kg' : r.unit === 'EA' ? 'stk' : (r.unit as string) || null,
      amount: num(r.amount) || 0, group: (r.productGroupDescription as string) || null, category: null,
    }));
    const total = num(head.amount ?? head.totalAmount) ?? lines.reduce((a, l) => a + l.amount, 0);
    out.push({ id: `rema-${tid}`, source: 'rema', chain: 'REMA 1000', store: String(head.storeName || 'REMA 1000'), date: when.date, time: when.time, total: Math.round(total * 100) / 100, currency: 'NOK', category: null, lines });
    await sleep(500);
  }
  return { receipts: out, secret: next };
}

/* ---------- Trumf (trumf.no "Mine kvitteringer", RSC payloads, the user's own session cookies) ---------- */
type Cookie = { name: string; value: string; domain: string; path?: string; expires?: number | null };
const TRUMF = 'https://www.trumf.no';
const CHAINS: [string, string][] = [['EUROSPAR', 'Eurospar'], ['SPAR', 'Spar'], ['KIWI', 'Kiwi'], ['MENY', 'Meny'], ['JOKER', 'Joker'], ['NÆRBUTIKKEN', 'Nærbutikken'], ['KJØPMANNSHUSET', 'Kjøpmannshuset'], ['ODA', 'Oda']];
const chainOf = (t: string) => (CHAINS.find(([k]) => new RegExp(`\\b${k}\\b`).test(t.toUpperCase())) || [])[1] || null;

/** Every JSON object in an RSC payload with `key` as a direct field (string-aware brace matching). */
export function jsonObjects(text: string, key: string): Record<string, unknown>[] {
  const needle = `"${key}"`;
  const hits: number[] = [];
  for (let i = text.indexOf(needle); i >= 0; i = text.indexOf(needle, i + 1)) hits.push(i);
  if (!hits.length) return [];
  const out: Record<string, unknown>[] = [];
  const stack: number[] = [];
  let inStr = false, esc = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (inStr) { if (esc) esc = false; else if (ch === '\\') esc = true; else if (ch === '"') inStr = false; continue; }
    if (ch === '"') inStr = true;
    else if (ch === '{') stack.push(i);
    else if (ch === '}' && stack.length) {
      const start = stack.pop()!;
      if (!hits.some((h) => h > start && h < i)) continue;
      try { const o = JSON.parse(text.slice(start, i + 1)); if (o && typeof o === 'object' && key in o) out.push(o); } catch { /* not JSON */ }
    }
  }
  return out;
}
const rv = (v: unknown) => (v === '$undefined' ? null : typeof v === 'string' && v.startsWith('$D') ? v.slice(2) : v);

export async function fetchTrumf(secret: string, knownIds: Set<string>, max = 40): Promise<{ receipts: Receipt[]; secret: string }> {
  const state = JSON.parse(secret) as { cookies: Cookie[] };
  const jar = new Map(state.cookies.filter((c) => /(^|\.)trumf\.no$/.test(c.domain.replace(/^\./, ''))).map((c) => [c.name, c]));
  const cookieHeader = () => [...jar.values()].filter((c) => /(^|\.)www\.trumf\.no$|^\.?trumf\.no$/.test(c.domain) && (!c.expires || c.expires * 1000 > Date.now())).map((c) => `${c.name}=${c.value}`).join('; ');
  const get = async (path: string, rsc = true) => {
    const res = await retrying(TRUMF + path, { headers: { Cookie: cookieHeader(), ...(rsc ? { RSC: '1' } : { Accept: 'application/json' }), 'User-Agent': 'Mozilla/5.0 Matkassa weekly pull' } });
    for (const sc of res.headers.getSetCookie?.() || []) {
      const [nv, ...attrs] = sc.split(';');
      const i = nv.indexOf('=');
      if (i < 0) continue;
      const name = nv.slice(0, i).trim();
      const maxAge = attrs.map((a) => a.trim()).find((a) => /^max-age=/i.test(a));
      const old = jar.get(name);
      jar.set(name, { name, value: nv.slice(i + 1), domain: old?.domain || 'www.trumf.no', path: '/', expires: maxAge ? Date.now() / 1000 + Number(maxAge.split('=')[1]) : old?.expires ?? null });
    }
    if (res.status >= 300 && res.status < 400) {
      if (/id\.trumf\.no|logg-inn|signin/.test(res.headers.get('location') || '')) throw new Error('expired: Trumf login');
      return { status: res.status, text: '', location: res.headers.get('location') || '' };
    }
    if (res.status === 401 || res.status === 403) throw new Error('expired: Trumf login');
    return { status: res.status, text: await res.text(), location: '' };
  };
  const session = await get('/api/auth/session', false);
  const sj = JSON.parse(session.text || 'null');
  if (!sj || !(sj.accessToken || sj.user)) throw new Error('expired: Trumf login');
  let listPath = '/trumf-profil/kvitteringer';
  let list = await get(listPath);
  if (list.status === 404) { listPath = '/profil/kvitteringer'; list = await get(listPath); }
  if (list.status !== 200) throw new Error(`Trumf list ${list.status}`);
  const seen = new Set<string>();
  const out: Receipt[] = [];
  for (const o of jsonObjects(list.text, 'batchId')) {
    const bid = String(rv(o.batchId) ?? '');
    if (!bid || seen.has(bid)) continue;
    seen.add(bid);
    const text = String(rv(o.beskrivelse) || '').trim();
    const total = num(o.belop);
    const hasReceipt = !!rv(o.harKvittering);
    if (!(hasReceipt || chainOf(text)) || !total || total <= 0 || knownIds.has(`trumf-b${bid}`)) continue;
    if (out.length >= max) break;
    const when = localWhen(o.transaksjonsTidspunkt);
    if (!when.date) continue;
    let lines: Line[] = [];
    if (hasReceipt) {
      const d = await get(`${listPath}/${encodeURIComponent(bid)}`);
      for (const k of jsonObjects(d.text, 'varelinjer')) {
        lines = ((k.varelinjer as Record<string, unknown>[]) || []).map((v) => {
          const ean = rv(v.ean);
          const unit = String(rv(v.enhetsType) || '').toLowerCase();
          return { name: String(rv(v.produktBeskrivelse) || 'Ukjent vare').trim(), ean: ean != null && /^\d{8,14}$/.test(String(ean)) ? String(ean) : null, qty: num(v.antall), unit: unit.startsWith('kg') ? 'kg' : unit ? 'stk' : null, amount: num(v.belop) || 0, group: null, category: null };
        });
        if (lines.length) break;
      }
      await sleep(1000);
    }
    const store = text === text.toUpperCase() ? text.toLowerCase().replace(/\b\p{L}/gu, (c) => c.toUpperCase()) : text;
    out.push({ id: `trumf-b${bid}`, source: 'trumf', chain: chainOf(text) || store || 'Trumf', store: store || 'Trumf', date: when.date, time: when.time, total: Math.round(Math.abs(total) * 100) / 100, currency: 'NOK', category: null, lines });
  }
  return { receipts: out, secret: JSON.stringify({ cookies: [...jar.values()] }) };
}
