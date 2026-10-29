# Matkassa (mattilbud-app)

Norsk PWA for iPhone: **ukens mattilbud**, **handleliste** som sier fra når en vare er på tilbud, og
**matforbruk** per måned og kategori. Arbeidsnavn «Matkassa». Plan: [`plan.md`](plan.md).

**Live:** https://olecny.github.io/matkassa/ · Premium-kopi for sammenligning: https://olecny.github.io/matkassa-premium/
(`../matkassa-premium/`, samme funksjoner, mer «premium» utseende og bevegelse, egen lagring)

## Bruk
- **Hjem** (første fane): hva du har brukt på mat denne måneden mot samme tid forrige måned, de største kategoriene og
  en liten trend for 6 måneder (trykk → Forbruk), opptil 4 varer fra handlelisten med tilbudsmerke (trykk →
  Handleliste) og en rad «Tilbud for deg» når appen har lært noe. Nye brukere får tomme tilstander med hva de kan gjøre.
- **Installer:** åpne lenken i Safari → Del → *Legg til på Hjem-skjerm*.
- **Område:** første gang appen åpnes uten valgt område, spør den om posisjonen én gang (avrundet til ca. 1 km, lagres
  bare på enheten). Sier du nei, eller den feiler, brukes Trondheim. Svarer ikke telefonen uten et trykk (iOS), vises
  kortet «Finn tilbud nær deg» med en knapp. Du blir ikke spurt på nytt ved hver start. Bytt når som helst i Mer → Område.
  Har du allerede valgt område, endres ingenting.
- **Tilbud:** henter alle aktive kundeaviser fra 14 dagligvarekjeder via Tjek (eTilbudsavis), rundt valgt område.
  Søk, filtrer på kjede (huskes) og kategori, sorter på pris, kilo-/literpris eller rabatt. Trykk **+** for å legge i handlelisten.
  Tilbudene lagres på telefonen og vises også uten nett. Oppdateres automatisk når de er over 6 timer gamle, eller med ↻.
- **Handleliste:** legg til, kryss av, slett. Hver vare får «På tilbud hos KIWI – 19,90 kr» hvis noe matcher denne uken (trykk for flere).
  Virker offline.
- **Forbruk:** *Importer fil* (Trumf-innsyn JSON, Coop-innsyn CSV/JSON, `spending.json`, Matkassa-backup) eller *Ny kvittering* for hånd.
  Viser måned, per kategori, siste 12 måneder, en kø med ukategoriserte varer (velg kategori → ny regel) og kvitteringene.
- **Ukentlig synk:** Mac-en kjører `ingest/sync.sh` hver søndag kl. 20:00 via launchd (kvitteringer + REMA-tilbud til
  det private datarepoet). Status: `cat ingest/logs/last-run.txt`. Se [ingest/README.md](ingest/README.md#automatisk-hver-uke-launchd).
- **Konto (valgfritt):** vises i Mer bare når `js/cloud-config.js` har et Supabase-prosjekt. Logg inn med e-post og
  passord (eller innloggingslenke), så synkes kvitteringer, handleliste, kategorier og regler begge veier mellom
  enhetene dine. Appen virker fullt uten konto. Første innlogging spør om du vil slå sammen eller bruke kontoens data.
  Oppsett for Ole: [SUPABASE.md](SUPABASE.md). Personvern: [PERSONVERN.md](PERSONVERN.md) (utkast).
- **Kjeder:** REMA og Trumf kobles til **fra Mac-en** (du logger inn selv), Coop via innsyn. Hvorfor ikke rett i appen:
  se [SUPABASE.md](SUPABASE.md#hvorfor-ikke-koble-til-rematrumf-rett-i-appen).
- **Mer:** synk fra ditt eget private repo (valgfritt, se [ingest/README.md](ingest/README.md)), område, skjul kjeder, rediger kategorier (navn, farge, legg til, slett), se/slett regler, eksporter/importer backup.

Alle data ligger i IndexedDB på enheten (`navigator.storage.persist()` blir forespurt). Ta backup jevnlig;
iOS kan tømme lagring for web-apper som ikke brukes.

## Kjøre lokalt
```bash
python3 -m http.server 8765      # åpne http://localhost:8765/
node test/unit.test.mjs          # enhetstester (import, summer, profil, EAN, fletting)
node test/e2e.mjs                # headless Chrome 390×844 over CDP, falskt nett fra test/fake/ → test/tmp/e2e-report.md
node test/e2e.mjs --live         # samme mot ekte Tjek-tilbud (bare lesing)
test/privacy.sh                  # ingen tokens/persondata i det offentlige repoet
test/rls.sh                      # Supabase-schema + RLS + FAKE-seed (to ganger) på en midlertidig lokal Postgres (brew install postgresql@17)
python3 test/ingest.test.py      # trumf.py, merge.py, cloud.py og sync.sh mot falsk trumf.no + falsk Supabase
python3 test/helper.test.py      # REMA-hjelperen (ingest/helper.py) med falsk rema-binær; ekte ~/.rema1000 røres aldri
node test/trumf-login.test.mjs   # trumf-login.mjs mot en falsk innloggingsside (headless)
node test/functions.test.mjs     # Edge Functions under Node med falske tjenester
```
Testagenten **Maria** (`project-jarvis/.claude/agents/maria.md`) kjører disse og skriver en PASS/FAIL-rapport.
All testdata i `test/fake/` er oppdiktet og merket `FAKE`.
Ingen byggesteg, ingen avhengigheter: vanilla HTML/CSS/JS-moduler.

## Struktur
| Fil | Hva |
|---|---|
| `index.html`, `styles.css` | UI (lys/mørk modus via `prefers-color-scheme`) |
| `js/app.js` | Visninger, handleliste, matching, forbruk, dialoger |
| `js/tjek.js` | Tjek-adapter: `GET /v2/catalogs` (r_lat/r_lng/r_radius) → `GET /v2/offers?catalog_id=…`, normalisering (pris, førpris, enhetspris, gyldighet, bilde) |
| `js/profile.js` | Læring: profil av egne kvitteringer, EAN-først matching med navn som reserve |
| `js/settings.js` | Innstillinger: standardverdier og validering (backup kan ikke endre synk-repo/nøkkel) |
| `js/extra-offers.js` | Tilbud med strekkode (REMA Superpris fra datarepoet) flettet inn i Tjek-tilbudene |
| `js/categories.js` | Standardkategorier, norsk nøkkelordkart, regelmotor |
| `js/spending.js` | Import (Trumf / Coop / spending.json / backup), sammenslåing og fjerning av samme kjøp fra to kilder, fordeling per kategori, måned mot måned (Hjem) |
| `js/cloud.js`, `js/cloud-config.js` | Valgfri konto: Supabase-klient uten bibliotek (innlogging, synk begge veier, `reconcile`) og offentlig prosjektoppsett |
| `supabase/` | Migrasjoner (tabeller + RLS, kjedeøkter i Vault), Edge Functions (`connect`, `fetch-receipts`), ukentlig pg_cron, RLS-test |
| `js/db.js` | Liten IndexedDB-nøkkel/verdi-lagring |
| `sw.js`, `manifest.webmanifest`, `icons/` | PWA: app-skall og tilbudsbilder caches |
| `ingest/` | Mac-side: `rema.py`, `trumf-login.mjs` + `trumf.py`, `merge.py`, `cloud.py`, `sync.sh`, `launchd/` (ukentlig jobb) og formatene `spending.json` / `rema-offers.json` ([ingest/README.md](ingest/README.md)) |
| `test/` | `unit.test.mjs`, `e2e.mjs`, `privacy.sh`, `fake/*-FAKE.json` (oppdiktet testdata). `test/tmp/` er git-ignorert |

## Datakilder og forbehold
- **Tjek** (`squid-api.tjek.com/v2`) er uoffisielt og uten nøkkel. CORS er åpent. Merk: API-et svarer 401 til
  `HeadlessChrome` som user-agent (bot-filter), vanlig Safari/Chrome går fint.
- Kategorier for tilbud gjettes fra varenavnet (ca. 88 % treff denne uken). Ukjente havner under *Annet*. Egne regler går foran.
- Tilbudsdata og persondata committes **aldri** (se `.gitignore`). Repoet inneholder bare appkode.

## Deploy
GitHub Pages fra `main` (rot). `git push` → Pages bygger på ~1 min. Ved endring av app-skallet: bump `VERSION` i `sw.js`
(og `APP_VERSION` i `js/app.js`). Cachene heter `matkassa-v*`, og service workeren sletter bare egne cacher, fordi
Matkassa Premium deler opprinnelsen `olecny.github.io` (den bruker `matkassa-premium-*` og egen IndexedDB). Service workeren henter app-skallet fra nett først, men faller tilbake til cache etter 3 s,
og etter én treg forespørsel serveres resten av lastingen fra cache (svakt nett i butikken).

## Status
0.6.0: Hjem-fane, valgfri konto med synk (Supabase, testet mot falsk backend + RLS på lokal Postgres), Trumf-kvitteringer
fra Mac-en (testet mot falsk trumf.no), Coop-innsyn-import (gjettet format), fjerning av samme kjøp fra to kilder.
REMA-kvitteringer er koblet til via `ingest/` (ekte konto). Venter på: Oles Supabase-prosjekt (SUPABASE.md), Oles første
Trumf-innlogging, test på Oles iPhone. Se `plan.md`.

## Tilbud for deg (læring, per bruker)
`js/profile.js` bygger en profil av **kvitteringene på denne enheten**, altså bare brukerens egne kjøp: hvert produkt
får en vekt (antall kjøp, halvert per 120 dager). Varelinjer med samme strekkode (EAN) er samme vare selv om teksten
varierer. Matching mot tilbud:
1. **Strekkode først:** har tilbudet EAN og du har kjøpt den EAN-en, er det et sikkert treff (merket «strekkode»).
2. **Navn som reserve:** ordene i navnet vektes med IDF, slik at merkenavn som går igjen («Tine») teller mindre enn
   ordet som sier hva varen er («helmelk»). Et tilbud må dekke minst halvparten av et produkts ord, og kategorien må
   stemme («Egg» treffer ikke «Egg nudler»).

**Ærlig tall:** Tjek-tilbudene har ingen strekkoder, så nesten all matching er navnebasert. Bare REMAs Superpris-tilbud
har GTIN (via `ingest/rema.py --offers` og synk); uka 2026-10-24 hadde 13 av 1 099 tilbud (≈ 1,2 %) strekkode.
Handlelistevarer lagt til fra et tilbud husker strekkoden og finner samme vare igjen senere uker.
Profilen bygges på telefonen, og ingenting sendes noe sted.

## Skjule kjeder
Mer → Kjeder: kryss vekk kjeder du ikke bruker. De forsvinner fra tilbud, filtre og handlelistens tilbudsmatching.
