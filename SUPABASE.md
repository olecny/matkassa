# Konto og synk med Supabase – oppsett for Ole

Matkassa virker fullt uten konto (alt ligger på telefonen). Med en **Matkassa-konto** synkes kvitteringer,
handleliste, kategorier og regler mellom enhetene dine, og Mac-en (eller senere serveren) leverer kvitteringene rett
inn i kontoen din, **uten GitHub-repo og uten GitHub-nøkkel**. Begge appene (Matkassa og Matkassa Premium) kan bruke
**samme** Supabase-prosjekt og samme konto.

Gratis: Supabase *Free plan* (500 MB database, 50 000 brukere, Edge Functions inkludert). Ingen betalingskort trengs.

> **Status:** schema + RLS er testet på lokal Postgres (`test/rls.sh`, 11 sjekker). Appens innlogging og synk er
> testet mot en falsk Supabase (e2e). Edge Functions er testet under Node med falske tjenester. **Ingenting er kjørt mot
> et ekte Supabase-prosjekt ennå**, fordi det krever at du lager kontoen selv. Ta stegene under i rekkefølge.

## Hvilke verdier går hvor

| Verdi | Hvor finner du den | Hvor skal den | Hemmelig? |
|---|---|---|---|
| Project URL `https://<ref>.supabase.co` | Project Settings → **API** (eller Connect) | `js/cloud-config.js` → `url` (begge repoene) | Nei, offentlig |
| **anon public** key (eller **publishable** key `sb_publishable_…`) | Project Settings → **API Keys** | `js/cloud-config.js` → `anonKey` (begge repoene) | Nei, offentlig med vilje: gir ingen tilgang uten innlogget bruker + RLS |
| **service_role** / **secret** key (`sb_secret_…`) | Project Settings → API Keys | **Ingen steder hos oss.** Supabase gir den selv til Edge Functions. | **JA. Aldri i appen, repoet, chatten eller e-post.** |
| Databasepassord | Lages i steg 1 | Passordbehandleren din. Trengs ikke av appen. | JA |
| `CRON_SECRET` (steg 8) | Du lager den: `openssl rand -hex 32` | `supabase secrets set …` + Vault (SQL) | JA |
| Trumf-/REMA-innlogging | Du logger inn selv på Mac-en | `~/.matkassa/` på Mac-en, evt. kryptert i Vault (steg 8) | JA, vises aldri |

GitHub-nøkkelen (`github_pat_…`) blir **aldri** sendt til Supabase. Appen sender bare område og kjedevalg fra
innstillingene, og databasen avviser innstillinger som inneholder `sync` eller `token` (testet).

## 1. Lag kontoen og prosjektet (du gjør dette selv)
1. Gå til **supabase.com** → *Start your project* → logg inn (GitHub eller e-post).
2. *New organization*: navn f.eks. «Ole», type *Personal*, plan **Free**.
3. *New project*: navn `matkassa`, **Region: North EU (Stockholm)** (data i EU/EØS), lag et sterkt databasepassord
   og lagre det i passordbehandleren. Vent til prosjektet er klart (1–2 min).

## 2. Lag tabellene og tilgangsreglene (RLS)
1. Venstremenyen → **SQL Editor** → *New query*.
2. Lim inn hele `supabase/migrations/20261024120000_matkassa_sync.sql` → **Run**. Skal gi «Success. No rows returned».
3. Ny query: lim inn `supabase/migrations/20261024120100_chain_connections.sql` → **Run**.
4. Sjekk: **Table Editor** viser `receipts`, `list_items`, `categories`, `rules`, `settings`, `chain_connections`,
   alle merket **RLS enabled**. (Begge filene kan kjøres på nytt uten skade.)

## 3. Innlogging (Authentication)
1. **Authentication → Sign In / Providers → Email**: på (standard). La **Confirm email** stå på.
2. **Authentication → URL Configuration**:
   - *Site URL*: `https://olecny.github.io/matkassa/`
   - *Redirect URLs* → *Add URL*: `https://olecny.github.io/matkassa/` og `https://olecny.github.io/matkassa-premium/`
     (innloggingslenken på e-post sender deg tilbake hit).
3. **Bare deg og testere foreløpig:** når du og testerne har laget konto, slå av **Allow new users to sign up**
   (Authentication → Sign In / Providers). Nye testere kan du invitere under Authentication → Users → *Invite user*.
   Å åpne for alle er en egen beslutning (se *Risiko og juss* nederst).

## 4. Koble appene til prosjektet
1. **Project Settings → API Keys**: kopier *Project URL* og *anon public* (eller *publishable*) key.
2. Lim dem inn i `js/cloud-config.js` i **begge** repoene (`mattilbud-app/` og `matkassa-premium/`):
   ```js
   export const CLOUD = {
     url: 'https://<ref>.supabase.co',
     anonKey: '<anon public key>',
   };
   ```
   Eller gi dem til Jarvis/David, så gjør vi det. Verdiene er offentlige med vilje; **service_role/secret-nøkkelen
   skal aldri inn her**.
3. Commit og deploy (GitHub Pages). Nå vises **Mer → Konto → Logg inn** i appene. Uten verdier vises den ikke.

## 5. Lag din konto i appen
1. Matkassa → **Mer → Konto** → skriv e-post og passord (minst 8 tegn) → **Opprett konto**.
2. Trykk på bekreftelseslenken i e-posten, og **Logg inn**. (Eller *Send innloggingslenke*: åpne lenken på samme enhet.)
3. Første gang, hvis både telefonen og kontoen har data, spør appen: **Slå sammen** (anbefalt: beholder alt, samme
   kvittering telles én gang) eller **Bruk kontoens data**. Etterpå synker appen av seg selv noen sekunder etter hver
   endring, når appen åpnes, og med *Synk nå*.
4. På neste enhet: logg inn med samme konto, så kommer alt.

## 6. Mac-en leverer kvitteringene til kontoen (erstatter GitHub-veien)
```bash
cd "~/Ole Storage/Claude/mattilbud-app"
python3 ingest/cloud.py login      # e-post + passord for Matkassa-kontoen (passordet vises ikke)
python3 ingest/cloud.py status
```
Fra nå laster den ukentlige jobben (søndag 20:00, `ingest/sync.sh`) nye kvitteringer rett inn i kontoen din.
Kvitteringer som alt finnes i kontoen (kanskje endret i appen) røres ikke. GitHub-veien (`MATKASSA_DATA_REPO` i
`ingest/.env`) virker fortsatt ved siden av, som reserve. Når kontoen har virket et par uker, kan du fjerne
GitHub-nøkkelen i appen (*Mer → Synk fra Mac → Glem nøkkel*) og linjen i `ingest/.env`.

## 7. Trumf og REMA på Mac-en (du logger inn selv)
```bash
node ingest/trumf-login.mjs          # Chrome åpnes på trumf.no: logg inn selv (telefon, passord, SMS-kode)
python3 ingest/trumf.py --check      # «Trumf-økta virker.»
python3 ingest/trumf.py --out /tmp/trumf-test.json   # prøvehenting, se antall i utskriften
rema1000 login                       # REMA (rema1000-cli), har du gjort før
```
Når Trumf-økta går ut (omtrent 3–12 måneder), sier den ukentlige jobben fra (macOS-varsel + `ingest/logs/last-run.txt`)
med kommandoen over.

## 8. Valgfritt: serveren henter hver søndag (Mac-en trengs ikke ukentlig)
Krever Supabase CLI (gratis): `brew install supabase/tap/supabase`.
```bash
supabase login                                   # åpner nettleseren, du logger inn selv
supabase link --project-ref <ref>                # <ref> = delen før .supabase.co
supabase functions deploy connect
supabase functions deploy fetch-receipts --no-verify-jwt
openssl rand -hex 32                             # = CRON_SECRET, lim inn i neste linje (ikke del den)
supabase secrets set CRON_SECRET=<verdien>
```
I dashboardet: **Database → Extensions**: slå på `pg_cron` og `pg_net`. Så i **SQL Editor**:
```sql
select vault.create_secret('https://<ref>.supabase.co', 'matkassa_project_url');
select vault.create_secret('<samme CRON_SECRET>', 'matkassa_cron_secret');
```
Kjør deretter `supabase/schedule/weekly_pull.sql` (søndag 18:00 UTC). Koble til kjedene fra Mac-en:
```bash
python3 ingest/cloud.py connect trumf     # etter trumf-login.mjs
python3 ingest/cloud.py connect rema      # etter rema1000 login
```
Økta lagres **kryptert i Vault**, kan bare leses av serveren, sendes aldri tilbake til noen app, og **Koble fra** i
appen sletter den. Prøv én gang for hånd: `curl -X POST https://<ref>.supabase.co/functions/v1/fetch-receipts -H "x-cron-secret: <verdien>"`
og se *Mer → Konto → Kvitteringer fra kjedene* («hentet …»).

**Status:** steg 8 er skrevet og testet med falske tjenester, men ikke kjørt på ekte Supabase. Gjør det sammen med
David første gang.

## Hvorfor ikke «Koble til REMA/Trumf» rett i appen?
Målet var: logg inn i Matkassa → *Koble til REMA* → kort innlogging → ferdig. Det går ikke rent i en web-app:
- **REMA:** innloggingen (id.rema.no / Firebase telefon-innlogging) er beskyttet med **reCAPTCHA** og sender deg bare
  tilbake til REMAs egen adresse (`ae-appen…/redirect`). En web-app kan ikke ta imot den innloggingen uten å omgå
  reCAPTCHA eller lese REMAs nettverkstrafikk, og det gjør vi ikke.
- **Trumf:** innloggingen skjer på id.trumf.no (telefon, passord og SMS-kode) og gir bare en økt på trumf.no.
  Trumf tilbyr ingen innlogging for andre apper, og en web-app kan ikke lese trumf.no sine informasjonskapsler.
- **Coop:** ingen dokumentert måte å hente egne kvitteringer på. De eneste kjente veiene er å dekode Coop-appens
  trafikk, og det gjør vi ikke. Bruk **innsyn**: coop.no → Min side → *Bestill innsyn*, og importer fila
  (CSV/JSON) under *Forbruk → Importer fil*. Formatet er ikke offentlig, så importen er laget for vanlige varianter
  og må sjekkes på din første ekte fil.

Beste ærlige løsning: **én innlogging per kjede på Mac-en** (du logger inn selv, i en vanlig nettleser/CLI), deretter
går resten av seg selv, enten via Mac-en hver søndag (steg 6–7) eller via serveren (steg 8). I appen viser
*Mer → Konto* status per kjede og *Koble fra*.

## Forholdet til den private GitHub-synken
| | GitHub-repo (i dag) | Matkassa-konto (nytt) |
|---|---|---|
| Hvem har tilgang | Den som har en GitHub-nøkkel med lesetilgang | Bare innlogget bruker, egne rader (RLS) |
| Oppsett for nye brukere | Privat repo + finkornet nøkkel + Mac | E-post og passord |
| Retning | Mac → repo → app (bare lesing) | Begge veier: app ↔ konto ↔ andre enheter; Mac/server → konto |
| Handleliste/kategorier mellom enheter | Nei | Ja |
| Nøkkel på telefonen | GitHub-nøkkel (lesetilgang) | Ingen; bare en innloggingsøkt |

GitHub-nøkkelen blir **ikke** lagt i Supabase: den trengs ikke der, og det ville samlet en nøkkel til private repoer
på en server uten grunn. Den blir værende bare på enheten, til du sletter den.

## Slette data (GDPR)
- **I appen:** *Mer → Konto → Slett dataene mine i skyen* sletter alle radene dine og kjedeøktene (dataene på
  telefonen beholdes).
- **Hele kontoen:** Authentication → Users → velg brukeren → *Delete user*. Alt brukeren eier slettes automatisk
  (`on delete cascade`, også øktene i Vault; testet i `test/rls.sh`).

## Risiko og juss (les før andre enn du og testerne får bruke det)
- **Vilkår (ToS):** REMA, Trumf og Coop har ingen offentlige API-er for dette. Vi henter bare brukerens egne data, med
  brukerens egen innlogging, i rolig tempo, uten å omgå captcha eller annen beskyttelse. Det er likevel uoffisielt:
  kjedene kan endre eller stenge det når som helst, og vilkårene deres kan forby automatisert henting. For deg selv
  er risikoen liten; for en tjeneste for andre bør du spørre kjedene eller bruke innsyn.
- **GDPR:** så snart andre enn du lagrer data i ditt Supabase-prosjekt, er **du behandlingsansvarlig**. Du trenger da
  en personvernerklæring (utkast: [`PERSONVERN.md`](PERSONVERN.md)), et grunnlag (samtykke), databehandleravtale med
  Supabase (DPA, finnes i dashboardet), mulighet for innsyn og sletting (finnes), og EU-region (steg 1).
  Kvitteringer kan avsløre helse, religion og vaner, så behandle dem som sensitive.
- **Tokensikkerhet:** kjedeøktene er like verdifulle som innloggingen hos kjeden. De ligger kryptert i Vault, kan bare
  leses av serveren (service role), logges aldri og sendes aldri tilbake. Lekker service_role-nøkkelen, kan alt
  leses: den skal derfor bare finnes hos Supabase.
- **Når API-ene endres:** henting feiler da for den kjeden. Den ukentlige jobben merker det (status *Feiler*/*Utløpt*
  i appen, macOS-varsel på Mac-en), resten virker videre. Innsyn (Trumf/Coop) er alltid reserven.
- **Gratisplanen:** et Supabase-prosjekt uten trafikk på 7 dager kan bli satt på pause; gjenopprett gratis i
  dashboardet. Den ukentlige jobben og vanlig bruk holder det som regel aktivt.

**Ole bestemmer før dette åpnes for andre brukere. Foreløpig er det for Ole og testere.**
