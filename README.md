# Matkassa (mattilbud-app)

Norsk PWA for iPhone: **ukens mattilbud**, **handleliste** som sier fra når en vare er på tilbud, og
**matforbruk** per måned og kategori. Arbeidsnavn «Matkassa». Plan: [`plan.md`](plan.md).

**Live:** https://olecny.github.io/matkassa/

## Bruk
- **Installer:** åpne lenken i Safari → Del → *Legg til på Hjem-skjerm*.
- **Tilbud:** henter alle aktive kundeaviser fra 14 dagligvarekjeder rundt Trondheim via Tjek (eTilbudsavis).
  Søk, filtrer på kjede (huskes) og kategori, sorter på pris, kilo-/literpris eller rabatt. Trykk **+** for å legge i handlelisten.
  Tilbudene lagres på telefonen og vises også uten nett. Oppdateres automatisk når de er over 6 timer gamle, eller med ↻.
- **Handleliste:** legg til, kryss av, slett. Hver vare får «På tilbud hos KIWI – 19,90 kr» hvis noe matcher denne uken (trykk for flere).
  Virker offline.
- **Forbruk:** *Importer fil* (Trumf-innsyn JSON, `spending.json`, Matkassa-backup) eller *Ny kvittering* for hånd.
  Viser måned, per kategori, siste 12 måneder, en kø med ukategoriserte varer (velg kategori → ny regel) og kvitteringene.
- **Mer:** rediger kategorier (navn, farge, legg til, slett), se/slett regler, eksporter/importer backup.

Alle data ligger i IndexedDB på enheten (`navigator.storage.persist()` blir forespurt). Ta backup jevnlig;
iOS kan tømme lagring for web-apper som ikke brukes.

## Kjøre lokalt
```bash
python3 -m http.server 8765      # åpne http://localhost:8765/
node test/unit.test.mjs          # importer + summer (ingen avhengigheter)
```
Ingen byggesteg, ingen avhengigheter: vanilla HTML/CSS/JS-moduler.

## Struktur
| Fil | Hva |
|---|---|
| `index.html`, `styles.css` | UI (lys/mørk modus via `prefers-color-scheme`) |
| `js/app.js` | Visninger, handleliste, matching, forbruk, dialoger |
| `js/tjek.js` | Tjek-adapter: `GET /v2/catalogs` (r_lat/r_lng/r_radius) → `GET /v2/offers?catalog_id=…`, normalisering (pris, førpris, enhetspris, gyldighet, bilde) |
| `js/categories.js` | Standardkategorier, norsk nøkkelordkart, regelmotor |
| `js/spending.js` | Import (Trumf / spending.json / backup), sammenslåing, fordeling per kategori |
| `js/db.js` | Liten IndexedDB-nøkkel/verdi-lagring |
| `sw.js`, `manifest.webmanifest`, `icons/` | PWA: app-skall og tilbudsbilder caches |
| `ingest/` | Mac-side: `rema.py` (skjelett, utestet) og **`spending.json`-formatet** ([ingest/README.md](ingest/README.md)) |
| `test/` | `unit.test.mjs`. `test/fixtures/` (testdata for skjermbilder) er git-ignorert |

## Datakilder og forbehold
- **Tjek** (`squid-api.tjek.com/v2`) er uoffisielt og uten nøkkel. CORS er åpent. Merk: API-et svarer 401 til
  `HeadlessChrome` som user-agent (bot-filter), vanlig Safari/Chrome går fint.
- Kategorier for tilbud gjettes fra varenavnet (ca. 88 % treff denne uken). Ukjente havner under *Annet*. Egne regler går foran.
- Tilbudsdata og persondata committes **aldri** (se `.gitignore`). Repoet inneholder bare appkode.

## Deploy
GitHub Pages fra `main` (rot). `git push` → Pages bygger på ~1 min. Ved endring av app-skallet: bump `VERSION` i `sw.js`.

## Status
Fase 1 (tilbud + handleliste + PWA) og app-delen av fase 2 (forbruk, import, kategorimotor, backup) er bygget og testet
headless. Venter på: test på Oles iPhone, ekte kvitteringsdata (Trumf-innsyn / REMA-token). Se `plan.md`.

## Tilbud for deg (læring)
`js/profile.js` bygger en profil av kvitteringene: hvert produkt du kjøper får en vekt (antall kjøp, halvert per 120 dager),
og ordene i navnet vektes med IDF, slik at merkenavn som går igjen på mange varer («Tine») teller mindre enn ordet som sier
hva varen er («helmelk»). Et tilbud må dekke minst halvparten av et produkts ord for å telle. Det gir stripa
«Tilbud for deg», sorteringen «For deg» og linja «Du kjøper ofte …». Profilen bygges på telefonen, og ingenting sendes noe sted.

## Skjule kjeder
Mer → Kjeder: kryss vekk kjeder du ikke bruker. De forsvinner fra tilbud, filtre og handlelistens tilbudsmatching.
