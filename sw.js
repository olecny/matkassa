// Matkassa service worker: precache the app shell, cache offer images.
// Offer data itself is stored by the app in IndexedDB, so offers work offline too.
const VERSION = 'matkassa-v3';
const SHELL = [
  './',
  'index.html',
  'styles.css',
  'manifest.webmanifest',
  'js/app.js',
  'js/db.js',
  'js/tjek.js',
  'js/categories.js',
  'js/spending.js',
  'icons/icon.svg',
  'icons/icon-192.png',
  'icons/icon-512.png',
  'icons/apple-touch-icon.png',
];
const IMG_CACHE = 'matkassa-img';
const IMG_MAX = 400;

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VERSION && k !== IMG_CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

async function trim(cacheName, max) {
  const c = await caches.open(cacheName);
  const keys = await c.keys();
  for (let i = 0; i < keys.length - max; i++) await c.delete(keys[i]);
}

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);

  // App shell: network first so updates show up at once; cache when offline.
  if (url.origin === self.location.origin) {
    e.respondWith(
      caches.open(VERSION).then(async (c) => {
        try {
          const res = await fetch(req, { cache: 'no-cache' });
          if (res.ok) c.put(req, res.clone());
          return res;
        } catch {
          const cached = await c.match(req, { ignoreSearch: true });
          return cached || (req.mode === 'navigate' ? c.match('index.html') : Response.error());
        }
      }),
    );
    return;
  }

  // Offer images: cache-first.
  if (url.hostname === 'image-transformer-api.tjek.com') {
    e.respondWith(
      caches.open(IMG_CACHE).then(async (c) => {
        const cached = await c.match(req);
        if (cached) return cached;
        try {
          const res = await fetch(req);
          if (res.ok || res.type === 'opaque') { c.put(req, res.clone()); e.waitUntil(trim(IMG_CACHE, IMG_MAX)); }
          return res;
        } catch (err) {
          return Response.error();
        }
      }),
    );
  }
  // Tjek API: network only (the app keeps its own copy in IndexedDB).
});
