// Edge Function `connect`: stores a chain session for the weekly server pull, encrypted in Vault.
// Called from the Mac (`python3 ingest/cloud.py connect trumf|rema`) with the USER's JWT, never with a service key.
// STATUS: written, NOT tested (no Supabase project yet). Deploy: `supabase functions deploy connect`.
//
// Security: the caller is identified by their own JWT (Supabase Auth); the session is written only through the
// service-role-only SQL function matkassa_store_chain_token (Vault). Nothing is ever sent back, and the secret is
// never logged.
const URL_ = Deno.env.get('SUPABASE_URL')!;
const ANON = Deno.env.get('SUPABASE_ANON_KEY')!;
const SERVICE = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!; // server-side only, set by Supabase
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

Deno.serve(async (req) => {
  if (req.method !== 'POST') return json(405, { error: 'POST only' });
  const auth = req.headers.get('Authorization') || '';
  const who = await fetch(`${URL_}/auth/v1/user`, { headers: { apikey: ANON, Authorization: auth } });
  if (!who.ok) return json(401, { error: 'not logged in' });
  const user = await who.json();
  let body: { chain?: string; secret?: string };
  try { body = await req.json(); } catch { return json(400, { error: 'bad json' }); }
  if (!['trumf', 'rema'].includes(String(body.chain))) return json(400, { error: 'chain must be trumf or rema' });
  if (typeof body.secret !== 'string' || body.secret.length < 10 || body.secret.length > 20000) return json(400, { error: 'bad secret' });
  try { JSON.parse(body.secret); } catch { return json(400, { error: 'secret must be JSON' }); }
  const r = await fetch(`${URL_}/rest/v1/rpc/matkassa_store_chain_token`, {
    method: 'POST',
    headers: { apikey: SERVICE, Authorization: `Bearer ${SERVICE}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ p_user: user.id, p_chain: body.chain, p_token: body.secret }),
  });
  if (!r.ok) return json(500, { error: 'could not store' });
  return json(200, { ok: true, chain: body.chain });
});
