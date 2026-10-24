// Edge Function `fetch-receipts`: the weekly server pull. Started by pg_cron (supabase/schedule/weekly_pull.sql)
// with the x-cron-secret header; for every connected chain it fetches NEW receipts into that user's rows.
// STATUS: written, NOT tested (no Supabase project, no Deno here). Deploy with JWT verification off, since the
// cron call carries its own secret: `supabase functions deploy fetch-receipts --no-verify-jwt`
// and set the secret: `supabase secrets set CRON_SECRET=<same value as in Vault>`.
import { fetchRema, fetchTrumf } from '../_shared/chains.ts';

const URL_ = Deno.env.get('SUPABASE_URL')!;
const SERVICE = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!; // server-side only
const CRON_SECRET = Deno.env.get('CRON_SECRET') || '';
const H = { apikey: SERVICE, Authorization: `Bearer ${SERVICE}`, 'Content-Type': 'application/json' };
const rest = async (path: string, init: RequestInit = {}) => {
  const r = await fetch(`${URL_}/rest/v1/${path}`, { ...init, headers: { ...H, ...(init.headers || {}) } });
  if (!r.ok) throw new Error(`db ${r.status}`);
  return r.status === 204 ? null : r.json().catch(() => null);
};
const rpc = (fn: string, args: unknown) => rest(`rpc/${fn}`, { method: 'POST', body: JSON.stringify(args) });

function sameSecret(a: string, b: string) {
  if (!a || a.length !== b.length) return false;
  let d = 0;
  for (let i = 0; i < a.length; i++) d |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return d === 0;
}

Deno.serve(async (req) => {
  if (!sameSecret(CRON_SECRET, req.headers.get('x-cron-secret') || '')) return new Response('forbidden', { status: 403 });
  const conns: { user_id: string; chain: string }[] = await rest('chain_connections?select=user_id,chain&status=neq.expired');
  const summary: Record<string, number | string> = {};
  for (const c of conns) {
    const key = `${c.user_id.slice(0, 8)}:${c.chain}`; // no full ids or secrets in logs
    try {
      const secret: string = await rpc('matkassa_read_chain_token', { p_user: c.user_id, p_chain: c.chain });
      if (!secret) throw new Error('no secret');
      const known = new Set<string>(((await rest(`receipts?select=id&user_id=eq.${c.user_id}&id=like.${c.chain === 'rema' ? 'rema' : 'trumf'}-*`)) || []).map((r: { id: string }) => r.id));
      const res = c.chain === 'rema' ? await fetchRema(secret, known) : await fetchTrumf(secret, known);
      if (res.receipts.length) {
        const rows = res.receipts.map((r) => ({ user_id: c.user_id, id: r.id, data: r, deleted: false }));
        await rest('receipts?on_conflict=user_id,id', { method: 'POST', body: JSON.stringify(rows), headers: { Prefer: 'resolution=ignore-duplicates,return=minimal' } });
      }
      if (res.secret !== secret) await rpc('matkassa_store_chain_token', { p_user: c.user_id, p_chain: c.chain, p_token: res.secret });
      await rpc('matkassa_fetch_result', { p_user: c.user_id, p_chain: c.chain, p_error: null });
      summary[key] = res.receipts.length;
    } catch (e) {
      const msg = String((e as Error).message || e).slice(0, 200);
      await rpc('matkassa_fetch_result', { p_user: c.user_id, p_chain: c.chain, p_error: msg }).catch(() => {});
      summary[key] = `error: ${msg}`;
    }
  }
  console.log('weekly pull', JSON.stringify(summary));
  return new Response(JSON.stringify({ ok: true, connections: conns.length }), { headers: { 'Content-Type': 'application/json' } });
});
