# Plan: Mattilbud-app (tilbud, handleliste og matforbruk)
*Opprettet 2026-10-24 · Status: Fase 1–2 bygget og deployet, REMA-kvitteringer koblet til, fase 6 (EAN + per bruker + testagent) bygget · venter på Oles test på iPhone · Eier: Jarvis · Teknisk vurdering: David*

**Live:** https://olecny.github.io/matkassa/ · Repo: github.com/olecny/matkassa (bare appkode)

## Mål
En norsk app på mobilen som (1) viser ukens mattilbud fra kjedene Ole handler i, (2) har en handleliste som sier fra når en vare er på tilbud, og (3) sporer matforbruket totalt og per kategori. Kategoriene kan tilpasses for hver bruker, først Ole.

**Ferdig når:** appen er installert på Oles telefon via *Legg til på Hjem-skjerm*, viser denne ukens tilbud, har en handleliste som virker offline og viser forbruk per kategori for minst én måned med ekte kvitteringsdata.

## Researchfunn (Jarvis + David, 2026-10-24)

### Tilbudsdata
| Kilde | Hva | Vurdering |
|---|---|---|
| **Tjek** (`squid-api.tjek.com/v2`, motoren bak eTilbudsavis/mattilbud) | Strukturerte tilbud fra kundeavisene. Kjedene legger dem inn selv, så ingen OCR trengs. Ca. 1 800 tilbud per uke fra 16 kjeder | **Hovedkilde.** Gratis, uten innlogging, og CORS er åpent, så appen kan hente direkte. Uoffisiell og uten vilkår, så den kan endres |
| **REMA kampanje-API** (`/v1/papirflycampaign/campaigns`, se [rema1000-cli](https://github.com/Alfredvc/rema1000-cli)) | REMA-kundeavisen med priser og GTIN | Kontrollkilde for REMA |
| **Kassalapp API** ([kassal.app/api](https://kassal.app/api)) | Priser og prishistorikk, gratis hobbynivå | **Ikke egnet:** har ingen tilbud, og ifølge egen FAQ heller ingen ferske priser fra REMA, KIWI eller Coop |
| PDF-kundeaviser + OCR | Reserveløsning | Bare om Tjek forsvinner |

Lærdom fra [kundeavis-mcp](https://github.com/donadelicc/kundeavis-mcp): Tjek gir ingen kategorier, så vi trenger et eget nøkkelordkart. Tilbudene forsvinner når de utløper, så vi må arkivere selv om vi vil ha prishistorikk. Tilbudsdata skal **ikke** ligge i et offentlig repo.

### Forbruksdata (kvitteringer)
| Kilde | Hva | Vurdering |
|---|---|---|
| **Trumf** (Kiwi, Meny, Spar, Joker) | Innsyn gir JSON med varelinjer per kvittering ([trumf_receipt_tools](https://github.com/olejorgenb/trumf_receipt_tools)). Det finnes også et uoffisielt API ([trumf-data-fetch](https://github.com/ttyridal/trumf-data-fetch)) | **Best.** Strukturert og uten OCR |
| **REMA Æ** | Det uoffisielle API-et gir varelinjer med pris, rabatt, GTIN og **REMAs egen varegruppe** | Svært bra, siden kategoriene nesten kommer gratis. Innlogging skjer med Firebase-telefonlogin. Ingen offisiell eksport er funnet |
| **Coop medlem** | Digitale kvitteringer finnes i appen | Ingen eksport eller API er funnet. GDPR-innsyn (art. 15/20) er mulig, men formatet er ukjent |
| **Foto eller PDF av kvittering** | For alt annet | Claude Code tolker dem i en økt (gratis på Pro, langt bedre enn Tesseract). Tesseract.js i appen er siste utvei |
| **Bank-CSV** | Bare totaler | Brukes til avstemming, ikke kategorier |

GDPR-innsyn passer til å **hente historikk bakover**, ikke til ukentlig synk.

## Arkitektur (Daves anbefaling)
```
Telefon (PWA, norsk, offline)              Mac (Jarvis-maskinen)
┌───────────────────────────────┐          ┌────────────────────────────────┐
│ Tilbud   ← Tjek direkte (CORS)│          │ ingest.py (Python, stdlib)     │
│ Handleliste (IndexedDB)       │          │  • REMA-adapter   ┐ tokens kun  │
│ Forbruk + kategorier          │◄─ import─│  • Trumf-adapter  ┘ i .env      │
│ Eksport/backup                │   JSON   │  • Claude Code tolker foto/PDF │
└───────────────────────────────┘          │  → spending.json (privat repo) │
                                           └────────────────────────────────┘
```
- **PWA** på GitHub Pages med bare appkoden, aldri data. Installeres via *Legg til på Hjem-skjerm*.
- **Lokal data først** (IndexedDB + `navigator.storage.persist()`). Sannheten for forbruksdata ligger på Mac / i et privat repo, så iOS-tømming av lagring ikke gjør skade.
- **Hver kilde har sin egen adapter**, så det er lett å bytte når et uoffisielt API brekker.
- **Kategorimotor:** kjedens varegruppe og EAN kommer først, deretter Oles regler (f.eks. «Tine Lettmelk → Meieri»). Ukategoriserte varer havner i en kø og blir til nye regler når de sorteres.
- **Flerbruker senere:** Supabase gratisnivå med kategorier per bruker, bare når det trengs.

## Beslutninger
**Ole må avgjøre (Jarvis spør samlet):**
1. iPhone eller Android? *(antatt: iPhone)*
2. Hvilke kjeder handler du mest i? Det bestemmer om REMA- eller Trumf-adapteren kommer først.
3. Er det greit å bruke uoffisielle API-er mot **din egen** REMA-/Trumf-data? *Anbefalt: ja (personlig bruk). Alternativer: bare innsyn og kvitteringer / bare manuelt.*
4. Skal Friday sende GDPR-innsynsforespørsler til Trumf, REMA og Coop nå for å få historikk? *Anbefalt: ja. Det er gratis og har lavest risiko. Det er en utgående handling, så du godkjenner utkastene.*
5. Kategorier: standardlisten under eller din egen?
6. Skal tilbud arkiveres ukentlig i et privat repo for prishistorikk? *Anbefalt: ja.*
7. Skal Astrid føre månedstotaler inn i regnskapsboka automatisk eller ved forespørsel? *Anbefalt: ved forespørsel først.*

**Besluttet av Ole (2026-10-24):**
8. **Område:** appen henter posisjonen automatisk ved første start (avrundet ~1 km), med Trondheim som reserve hvis du sier nei eller det feiler. Mer → Område beholdes. Ingen nye spørsmål ved hver start.
9. **Ukentlig synk:** ja. launchd på Mac-en kjører `ingest/sync.sh` søndag kl. 20:00 (kvitteringer + REMA-tilbud til det private datarepoet).
10. **Premium-kopi:** ja. Egen app med samme funksjoner og mer premium utseende etter emilkowal.ski-skillene, på olecny.github.io/matkassa-premium, for sammenligning. Egen lagring (isolert), med enveis kopi fra Matkassa.

**Besluttet av Ole (2026-10-24, runde 2), bygget av David 2026-10-25:**
11. **Hjem** som første fane i begge appene (forbruk denne måneden mot samme tid forrige måned, toppkategorier, trend; åpne varer med tilbudsmerke; «Tilbud for deg»).
12. **Konto med Supabase (gratis), lokal-først.** Appen virker uten konto; «Logg inn» vises bare når `js/cloud-config.js` er fylt ut. Tabeller per element med RLS `user_id = auth.uid()`. Første innlogging: *Slå sammen* (standard) eller *Bruk kontoens data*. På samme element vinner enheten som endret det sist før synk. GitHub-nøkkelen legges **ikke** i Supabase (databasen avviser det). Ole lager prosjektet selv (SUPABASE.md).
13. **«Koble til» kjeder:** ikke mulig rent i en PWA (REMA: reCAPTCHA + låst retur-URL; Trumf: innlogging bare på trumf.no; Coop: ingen dokumentert vei). Valgt: Ole logger inn selv én gang per kjede **på Mac-en**; Mac-en (eller serveren, via Vault-krypterte økter og en ukentlig Edge Function) henter etterpå. Coop bare via innsyn. GitHub/Mac-veien beholdes som reserve.
14. **Åpning for andre:** ikke nå. Kun Ole og testere til Ole har tatt stilling til vilkår (ToS), GDPR (behandlingsansvar, PERSONVERN.md) og sikkerhet (SUPABASE.md → Risiko og juss).

**Antatt (kan endres når som helst):**
- Appnavn: «Matkassa» (arbeidsnavn). UI på norsk (bokmål), lys og mørk modus.
- Standardkategorier: Meieri, Kjøtt/fisk, Frukt/grønt, Brød/bakst, Tørrvarer, Snacks/godteri, Drikke, Frossen, Husholdning, Annet.
- Bare gratis tjenester: GitHub Pages og GitHub Actions/Mac, ingen betalte API-er.

## Team (agenter)
| Agent | Status | Rolle i oppgaven | Verktøy / modell |
|---|---|---|---|
| Jarvis | finnes | Orkestrerer, snakker med Ole og krysser av gates | – |
| David | finnes | Bygger PWA, adaptere, ingest-skript og kategorimotor | alle / opus |
| Friday | finnes | Utkast til innsynsforespørsler (Trumf/REMA/Coop). Sender først når Ole har godkjent | e-post |
| Astrid | finnes | Månedstotaler per kategori inn i regnskapsboka (fase 4) | Excel |
| Maria | ny (2026-10-24) | Tester appen ende til ende etter hver endring (`test/e2e.mjs`, `test/privacy.sh`), skriver PASS/FAIL-rapport | Bash, Read, Write / sonnet |

## Faser

### Fase 0: Oppsett og beslutninger
- [ ] Ole svarer på beslutning 1–7
- [x] Opprett repo `mattilbud-app/` (git init) med README
- [ ] Friday lager utkast til innsynsforespørsler hvis beslutning 4 = ja
**Gate 0:**
- [ ] Alle 7 beslutninger er notert i denne planen
- [ ] (Ole) Innsynsutkast godkjent og sendt, eller valgt bort

### Fase 1: MVP – Tilbud + handleliste (~2–3 økter) · **Hvem:** David
- [x] Tjek-adapter: hent ukens tilbud for Oles kjeder og normaliser pris og enhetspris *(alle 14 dagligvarekjeder rundt Trondheim, filter i appen)*
- [x] Tilbudsvisning: søk, filtrer på kjede og kategori (nøkkelordkart), gyldig til-dato
- [x] Handleliste: legg til, kryss av og slett. Lagres i IndexedDB
- [x] Matching: «Melk – på tilbud hos Kiwi, 19,90» på listevarer
- [x] PWA: manifest, service worker, offline-cache av siste tilbud
- [x] Deploy til GitHub Pages (bare appkode)
**Gate 1:**
- [x] Skjermbilde i 390×844 viser ekte tilbud fra denne uken
- [x] Handlelisten virker i flymodus *(testet headless med offline-modus; ikke på ekte iPhone ennå)*
- [x] Ingen tilbudsdata er committet i det offentlige repoet (`git ls-files` sjekket)
- [ ] (Ole) Installert på telefonen og testet i butikken

### Fase 2: Forbruk v1 (~2–3 økter) · **Hvem:** David
- [ ] `ingest.py` på Mac med REMA- og/eller Trumf-adapter (tokens i `.env`) *(skjelett `ingest/rema.py` laget, utestet uten token; Trumf importeres direkte i appen)*
- [x] Import av Trumf-innsyns-JSON (historikk) *(testet med testfil, ikke ekte innsyn ennå)*
- [x] Felles kvitteringsformat (`spending.json`): dato, kjede, varelinjer, beløp, kategori *(se `ingest/README.md`)*
- [x] Kategorimotor med Oles regler og kø for «Ukategorisert»
- [x] Forbruksvisning: per måned, per kategori og trend. JSON-import og -eksport
**Gate 2:**
- [ ] Minst én måned med ekte kvitteringer er importert og ≥ 90 % av beløpet er kategorisert
- [x] Summen per måned stemmer med kvitteringene (testskript)
- [x] Ingen tokens i git (`git grep` sjekket)

### Fase 3: Kvitteringer fra foto/PDF (~2 økter) · **Hvem:** David + Jarvis
- [ ] Mappe `inbox/` der Ole slipper bilder og PDF-er (f.eks. via iCloud)
- [ ] Claude Code-rutine eller -skill som tolker kvitteringer til `spending.json`
- [ ] Kategoriseringsforslag som Ole godkjenner i appen
**Gate 3:**
- [ ] 5 ekte kvitteringsbilder blir tolket med riktig totalsum

### Fase 4: Integrasjoner og prishistorikk · **Hvem:** David + Astrid
- [ ] Ukentlig arkiv av tilbud i et privat repo (hvis beslutning 6 = ja)
- [ ] Astrid: månedstotaler per kategori inn i regnskapsboka
- [ ] Budsjett per kategori med varsel i appen
**Gate 4:**
- [ ] Astrid har ført én måned uten avvik mot appen

### Fase 5: Verifiser og overlever
- [x] README med hvordan du installerer, importerer og legger til kategorier
- [x] Rad i Projects-tabellen i `CLAUDE.md`
- [ ] Oppføring i `project-jarvis/project-log.md`
**Gate 5:**
- [ ] (Ole) Har brukt appen i én hel handleuke

### Fase 6: Strekkode (EAN) og læring per bruker · **Hvem:** David + Maria
- [x] Research: har tilbudene strekkoder? *(Tjek: **nei**, ingen EAN/GTIN i `v2/offers`, 0 av 1 097 tilbud; v4 krever API-nøkkel. REMA Superpris-kampanjen: 16 av 16 tilbud har GTIN, men krever egen REMA-innlogging. Kassalapp: EAN → navn/merke/kategori, gratis hobbynivå men krever API-nøkkel, bare fra Mac, ikke tatt i bruk)*
- [x] EAN først, navn som reserve: profilen kjenner varene på strekkode; tilbud med strekkode matches på EAN, resten på navn; «strekkode»-merke viser treffet
- [x] REMA Superpris med GTIN: `rema.py --offers` → `rema-offers.json` i brukerens private datarepo → appen fletter GTIN inn i Tjek-tilbudet (samme pris + felles ord) *(denne uken: 13 av 1 099 tilbud ≈ 1,2 % har EAN, alle hos REMA)*
- [x] Kategorisperre i navnematchingen («Egg» ≠ «Egg nudler»)
- [x] Per bruker: ingen Ole-standarder i koden (tomt synk-repo, område-velger), `sync.sh` med eget repo i `ingest/.env` og sperre mot offentlige repoer
- [x] Testagent Maria + `test/e2e.mjs` (CDP, 390×844, falske data) + `test/privacy.sh`
**Gate 6:**
- [x] Enhetstester, e2e (falsk og `--live`) og personvernsjekk grønne
- [x] (Maria) Uavhengig testrapport *(PASS, 1 major + 4 minor, alle rettet i 0.4.1)*
- [ ] (Ole) «strekkode»-treff sett på telefonen etter `ingest/sync.sh`

### Fase 7: Ekte flerbruker · **Hvem:** David · *grunnmur bygget 2026-10-25 (0.6.0), venter på Oles Supabase-prosjekt*
I dag er appen «per bruker» ved at alt ligger på brukerens egen enhet: profilen («Tilbud for deg») bygges bare av kvitteringene i den enhetens IndexedDB, og hver bruker har sin egen REMA-innlogging, sitt eget private datarepo og sin egen lesenøkkel. Det skalerer ikke til folk uten Mac/GitHub. Veien videre, når det trengs:
- [x] **Innlogging:** Supabase gratisnivå, e-post + passord og innloggingslenke (`js/cloud.js`, uten bibliotek). *Sign in with Apple: senere*
- [x] **Data per bruker:** `receipts`, `list_items`, `categories`, `rules`, `settings` (+ `chain_connections`) med `user_id` og **RLS** på alle (`supabase/migrations/`), testet på lokal Postgres (`test/rls.sh`)
- [ ] **Profil per bruker:** bygges fortsatt i klienten fra brukerens egne kvitteringer (ingen deling mellom brukere); eventuelt lagret i `profile` for raskere oppstart
- [x] **Kvitteringskilder:** Mac-skript per bruker skriver til Supabase med brukerens egen innlogging (`ingest/cloud.py`); Edge Functions `connect` + `fetch-receipts` med økter kryptert i Vault og ukentlig pg_cron *(skrevet og testet med falske tjenester, ikke kjørt på ekte Supabase)*
- [ ] **Tilbud med EAN:** felles, ikke-personlig tilbudstabell (Tjek + REMA Superpris) som en planlagt jobb fyller; ev. Kassalapp-oppslag EAN → navn med nøkkel bare på serveren
- [x] **Personvern:** sletting i appen + kaskade ved sletting av bruker (testet), PERSONVERN.md (utkast), ingen kvitteringsdata eller tokens i logger. *Databehandleravtale: Ole i Supabase-dashboardet*
- [x] Migrering: første innlogging slår sammen enhetens data med kontoen
**Gate 7:**
- [x] To testbrukere ser bare sine egne data (RLS-test på lokal Postgres, 11 sjekker)
- [ ] (Ole) Supabase-prosjekt laget og `js/cloud-config.js` fylt ut (SUPABASE.md)
- [ ] (Ole) Godkjent kostnad (0 kr) og vilkår før andre enn testere får konto

## Risikoer
- **Uoffisielle API-er (Tjek, REMA, Trumf) brekker eller bryter vilkår** → én adapter per kilde, sjeldne kall, bare egen data, og kvitteringstolking som reserve.
- **Tjek har ingen kategorier** → eget nøkkelordkart (idéer fra kundeavis-mcp, MIT).
- **iOS tømmer PWA-lagring** → `storage.persist()`, sannheten på Mac / i privat repo, eksport og backup.
- **Dårlig OCR på termokvitteringer** → strukturerte kilder først, Claude Code i stedet for Tesseract.
- **Lekkasje av tokens eller persondata** → tokens bare i `.env` på Mac, data aldri på offentlige Pages.

## Ikke verifisert ennå
Dagens innsynsprosess hos Trumf (gammel URL gir 404), innsynsformat hos REMA og Coop, Tjeks vilkår og om REMA-, Trumf- eller Coop-appene har en offisiell kvitteringseksport.
Fra 0.6.0: `trumf.py` mot ekte trumf.no (feltnavn fra åpne prosjekter, paginering ukjent), Coop-innsynsformatet (importen er gjettet), Supabase-migrasjonene og Edge Functions på et ekte prosjekt (RLS bare testet på lokal Postgres med en Supabase-stand-in), Vault-tilgangen for `postgres`-rollen i Supabase.

## Logg
| Tid | Fase | Hva skjedde |
|---|---|---|
| 2026-10-24 | 0 | Plan laget. Jarvis researchet kilder, og David verifiserte API-er og anbefalte arkitektur |
| 2026-10-24 | 1–2 | David bygget Matkassa (PWA): Tjek-tilbud fra 14 kjeder, handleliste med tilbudsmatching, offline, forbruk med Trumf/spending.json-import, regelmotor, backup; REMA-skjelett på Mac. Deployet til olecny.github.io/matkassa. Testet headless (390×844, lys/mørk, offline). Antatte standardvalg for beslutning 1 og 5; ingen e-post sendt, ingen innlogging |
| 2026-10-24 | 2 | REMA koblet til: Ole logget inn med rema1000-cli (token kun i ~/.rema1000). `rema.py` leser tokenet derfra; første ekte kjøring ga 101 kvitteringer (2024-07-09 → 2026-10-20), 748 varelinjer, varelinjesum = total på alle. Automatisk kategorisering 96,0 % av beløpet (testskript). Import i appen på telefonen gjenstår (Ole) |
| 2026-10-24 | 6 | David: gjennomgang av Jarvis' tillegg (synk, service worker, skjul kjeder, læring) og rettinger. Strekkode-research: Tjek har ingen EAN (0/1 097), REMA Superpris 16/16 med GTIN → flettet inn, 13 av 1 099 tilbud ≈ 1,2 % har EAN denne uken. EAN-først matching, kategorisperre, per-bruker-oppsett (tomt synk-repo, område, `sync.sh` med eget repo + sperre mot offentlige repoer). Ny testagent Maria, `test/e2e.mjs` (51/51 falsk, 43/43 + 8 hoppet over live), 39/39 enhetstester, personvernsjekk grønn. Rettet: service worker hang på svakt nett (nå 3 s cache-fallback), synk prøvde på nytt ved hver app-veksling etter feil, «Tilbud for deg» ignorerte kjedefilter, repo-feltet kunne ikke tømmes, små knapper < 44 px |
| 2026-10-24 | 6 | Maria testet 0.4.0: PASS, 1 major + 4 minor. David rettet i 0.4.1: service worker åpnet på ~9 s ved svakt nett (3 s per nivå i lastekjeden) → etter én treg forespørsel serveres resten fra cache, målt 3,3 s; vannrett rulling på 320 px; tom-tilstand når alle kjeder er skjult (peker til Mer → Kjeder); tilbudskoblet handlelistevare viste skjult kjede; backup-gjenoppretting kan ikke lenger endre synk-repo, og ødelagte innstillinger (område uten koordinater) renses (`js/settings.js`). Tester: enhet 47/47, e2e 61/61 (falsk) og 53/53 + 8 hoppet over (live), personvern 8/8 |
| 2026-10-24 | 6 | David, 0.5.0: posisjon ved første start (spør én gang, avrundet ~1 km, fallback Trondheim, kort «Finn tilbud nær deg» når iOS trenger et trykk, eksisterende område beholdes; omlasting under henting settes i kø). Ukentlig synk: launchd-agent `no.matkassa.weekly-sync` søndag 20:00 (`ingest/launchd/`, logg + `last-run.txt` + macOS-varsel ved feil, tokens maskeres); kickstart-test: OK, 101 kvitteringer + 16 strekkodetilbud pushet. Service worker sletter bare egne cacher (delt opprinnelse). Matkassa Premium bygget og deployet (`../matkassa-premium/`, egen IndexedDB og cacher, enveis kopi uten token, DESIGN.md). Tester Matkassa: enhet 56/56, e2e 89/89 (falsk) og 81/81 + 8 hoppet over (live), personvern 8/8. Premium: enhet 75/75, e2e 109/109 og 101/101 + 8 hoppet over, personvern 8/8 |
| 2026-10-25 | 6–7 | David, 0.6.0 (Premium 0.6.0-premium.1). Marias funn: 16 px sorteringsvalg (ingen iOS-zoom) + test for alle felt ≥ 16 px; Premium: slipphastighet over siste ~100 ms og 0 hvis siste bevegelse > 80 ms før slipp (10/10 kjøringer grønne), FLIP-gli ved avkrysning, 320 px/150 % tekst (bryting, faste knapper i arket). **Hjem**-fane i begge. **Konto** (Supabase, lokal-først, synk begge veier, sammenslåing ved første innlogging) med RLS testet lokalt; Edge Functions + Vault + pg_cron skrevet (ikke kjørt på ekte Supabase). **Trumf** fra Mac-en (`trumf-login.mjs` + `trumf.py`, testet mot falsk trumf.no), **Coop** bare via innsyn (CSV/JSON-import, gjettet format), samme kjøp fra to kilder slås sammen. `sync.sh` leverer til konto og/eller privat repo. Ingen kontoer laget, ingen innlogging på Oles vegne. |
