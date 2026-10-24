// Learns what the user usually buys from receipts, and scores offers against it.
import { normalize, tokens } from './categories.js';

const HALF_LIFE_DAYS = 120; // a purchase four months ago counts half
const SKIP_LINE = /^(pant|bærepose|bæreposer|pose)\b/;
// Words that say nothing about the product (store brands, packaging, units).
const GENERIC = new Set([
  'rema', 'lavpris', 'prima', 'first', 'price', 'xtra', 'coop', 'kiwi', 'meny', 'eldorado', 'stk', 'pk', 'pakning',
  'løsvekt', 'ca', 'pr', 'kg', 'gr', 'ltr', 'med', 'og', 'uten', 'til', 'for', 'fra', 'the', 'eko', 'økologisk',
  'norsk', 'norske', 'stor', 'liten', 'ny', 'nye', 'mix', 'familiepakning', 'boks', 'flaske', 'pose',
]);

const useful = (t) => t.length >= 3 && !/\d/.test(t) && !GENERIC.has(t);
const titleCase = (s) => s.charAt(0).toUpperCase() + s.slice(1).toLowerCase();

/** Product name without sizes and noise, e.g. "TINE HELMELK 3.5% 1.75L" → "tine helmelk". */
export function productKey(name) {
  return tokens(name).filter((t) => !/\d/.test(t)).join(' ');
}

/**
 * Build a profile from receipts: one entry per distinct product the user buys, with a weight
 * (recency-decayed purchase count, 0–1) and its words weighted by IDF, so a brand that appears on many
 * products ("tine") counts less than the word that says what the product is ("helmelk").
 */
export function buildProfile(receipts, now = Date.now()) {
  const products = new Map(); // key → {name, w, n}
  for (const r of receipts || []) {
    const age = r.date ? Math.max(0, (now - Date.parse(r.date)) / 864e5) : 365;
    const decay = Math.pow(0.5, age / HALF_LIFE_DAYS);
    for (const l of r.lines || []) {
      const norm = normalize(l.name);
      if (!norm || SKIP_LINE.test(norm) || (l.amount ?? 0) <= 0) continue;
      const key = productKey(l.name);
      if (!key.split(' ').some(useful)) continue;
      const p = products.get(key) || { name: l.name, w: 0, n: 0 };
      p.w += decay;
      p.n += 1;
      products.set(key, p);
    }
  }
  const df = new Map();
  for (const key of products.keys()) for (const t of new Set(key.split(' ').filter(useful))) df.set(t, (df.get(t) || 0) + 1);
  const P = products.size || 1;
  const maxW = Math.max(0, ...[...products.values()].map((p) => p.w)) || 1;
  const list = [...products].map(([key, p]) => {
    const words = [...new Set(key.split(' ').filter(useful))].map((t) => ({ t, idf: Math.log(1 + P / df.get(t)) }));
    return {
      name: titleCase(key.split(' ').filter((t) => t.length > 1 && !GENERIC.has(t)).join(' ') || key),
      n: p.n,
      w: Math.sqrt(p.w / maxW), // sqrt: favourites lead, but occasional buys still count
      words,
      total: words.reduce((a, x) => a + x.idf, 0),
    };
  });
  return { products: list, receipts: (receipts || []).length };
}

const wordHit = (w, t) => (w === t ? 1 : w.length >= 4 && t.length >= 4 && (w.endsWith(t) || t.endsWith(w)) ? 0.6 : 0);

/**
 * Score an offer (its title words) against the profile: for each bought product, the IDF-weighted share
 * of its words found in the offer (≥ 50 % needed), times how much the user buys it. Best product wins.
 * Returns {score, because} where because is that product ({name, n}).
 */
export function scoreOffer(profile, words) {
  if (!profile || !profile.products.length) return { score: 0, because: null };
  const ws = words.filter(useful);
  if (!ws.length) return { score: 0, because: null };
  let score = 0;
  let because = null;
  for (const p of profile.products) {
    let got = 0;
    for (const { t, idf } of p.words) {
      let h = 0;
      for (const w of ws) if ((h = Math.max(h, wordHit(w, t))) === 1) break;
      got += h * idf;
    }
    const cover = got / p.total;
    if (cover < 0.5) continue;
    const s = cover * p.w;
    if (s > score) { score = s; because = p; }
  }
  return { score, because };
}
