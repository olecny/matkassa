# ingest – kvitteringsdata fra Mac til Matkassa

Skript som kjører på Mac-en (Jarvis-maskinen) og lager `spending.json`, som du importerer i appen
(**Forbruk → Importer fil**). Data og tokens forlater aldri Mac-en / telefonen, og blir aldri committet
(`.env` og `spending*.json` er git-ignorert).

| Skript | Status |
|---|---|
| `rema.py` | Testet mot en ekte konto (101 kvitteringer, varelinjesum = total). `--offers` henter REMAs Superpris-tilbud med strekkoder (GTIN). Endepunkter fra [rema1000-cli](https://github.com/Alfredvc/rema1000-cli) `API.md` |
| `trumf-login.mjs` | Du logger inn selv på trumf.no i et vanlig Chrome-vindu; lagrer bare trumf.no-økta i `~/.matkassa/trumf_state.json` (0600). Testet mot en falsk side, **ikke mot ekte trumf.no** (krever Oles innlogging) |
| `trumf.py` | Trumf-kvitteringer (Kiwi, Meny, Spar, Joker) med varelinjer og strekkoder → `spending.json`, kilde `trumf`. Testet mot falsk trumf.no (FAKE RSC-svar); **ikke mot ekte data ennå** |
| `merge.py` | Slår sammen REMA + Trumf (+ evt. flere) og fjerner samme kjøp fra to kilder |
| `cloud.py` | Mac → **din Matkassa-konto** (Supabase): `login`, `upload`, `connect trumf|rema`, `status`. Se [SUPABASE.md](../SUPABASE.md) |
| `sync.sh` | Henter fra REMA og/eller Trumf (det du har logget inn på), slår sammen, og leverer til kontoen din og/eller **ditt eget private** datarepo |
| `launchd/` | Kjører `sync.sh` automatisk hver søndag kl. 20:00 (se under) |
| Trumf-innsyn | Kan fortsatt importeres direkte i appen (JSON); dobbelt med `trumf.py` slås sammen |
| Coop | **Ingen dokumentert API** for egne kvitteringer, så ingen skraper (vi dekoder ikke Coop-appens trafikk). Bestill innsyn: coop.no → Min side → *Bestill innsyn*, og importer CSV/JSON i appen. Formatet er gjettet (FAKE-eksempler i `test/fake/`) og må sjekkes på første ekte fil |
| Kvitteringsfoto/PDF | Fase 3: Claude Code tolker bilder til samme format |

## REMA (`rema.py`)

Bare standardbiblioteket (Python 3.9+).

```bash
rema auth login                                     # én gang, med DITT telefonnummer (rema1000-cli)
cd ingest
python3 rema.py --out spending-rema.json            # alle transaksjoner API-et gir
python3 rema.py --out spending-rema.json --since 2026-09-01
python3 rema.py --offers rema-offers.json           # REMA Superpris med strekkoder (trenger `brew install brotli`)
python3 rema.py --dump-heads                        # skriv rå transaksjonsliste (for feilsøking)
```

**Innlogging:** REMA-appen logger inn med telefonnummer (id.rema.no → Firebase). Logg inn med
[rema1000-cli](https://github.com/Alfredvc/rema1000-cli) (`rema auth login`); `rema.py` leser tokenet fra
`~/.rema1000/tokens.json` selv, så du trenger ikke kopiere det noe sted. (Alternativ: `REMA_FIREBASE_REFRESH_TOKEN`
i `ingest/.env`.) Skriptet bytter det mot et kortlivet ID-token ved hver kjøring og skriver det aldri ut. Del aldri tokenet.

**Strekkoder på tilbud:** Kampanje-endepunktet svarer alltid brotli-komprimert, som Pythons standardbibliotek ikke
kan pakke ut. `rema.py` bruker `brotli`-modulen eller `brotli`-kommandoen (`brew install brotli`, gratis) hvis de finnes;
ellers hoppes tilbudene over og kvitteringene synkes som vanlig.

Endepunkter (base `https://api.rema.no`, header `Ocp-Apim-Subscription-Key` + `Authorization: Bearer <firebase-id-token>`):

| Kall | Hva |
|---|---|
| `GET /v1/bella/transaction/v2/heads` | Liste over kjøp (feltene i `transactions[]` er ikke dokumentert; skriptet leter etter id/dato/beløp tolerant) |
| `GET /v1/bella/transaction/v2/rows/{id}` | Varelinjer: `productDescription`, `prodtxt3` (GTIN), `productGroupDescription` (REMAs varegruppe), `amount`, `discount`, `deposit`, `pieces`, `volume`, `unit` |

Dette er et **uoffisielt** API mot din egen konto. Det kan endres uten varsel. Kjør sjelden (f.eks. én gang i uka).

## Trumf (`trumf-login.mjs` + `trumf.py`)

Bare Node 22+ og Python-standardbiblioteket; Google Chrome må være installert.

```bash
node ingest/trumf-login.mjs                  # 1. Chrome åpnes på trumf.no: logg inn SELV (telefon, passord, SMS-kode)
python3 ingest/trumf.py --check              # 2. «Trumf-økta virker.»
python3 ingest/trumf.py --out spending-trumf.json [--since 2026-01-01]
```
- **Slik virker det:** `trumf.py` leser de samme sidene som trumf.no viser deg under *Mine kvitteringer*
  (`/trumf-profil/kvitteringer`, React Server Component-svar med `RSC: 1`): transaksjoner (`batchId`, `belop`,
  `beskrivelse`, `transaksjonsTidspunkt`, `harKvittering`) og per kvittering `varelinjer` (`produktBeskrivelse`, `ean`,
  `antall`, `enhetsType`, `belop`). Kjeden tas fra kvitteringen (Kiwi/Meny/Spar/Joker …). Bonus-/partnerkjøp uten
  kvittering (bensin o.l.) hoppes over.
- **Skånsomt:** maks én side i sekundet, nye kjøp hentes bare én gang (tidligere kvitteringer gjenbrukes),
  nye forsøk ved 429/5xx/nettfeil.
- **Økta:** trumf.no fornyer innloggingen underveis; skriptet lagrer de nye informasjonskapslene (0600). Når den er
  utløpt, avslutter det med kode 2 og ber deg kjøre `trumf-login.mjs` igjen. Verdier skrives aldri ut.
- **Kilder (bare lest, ingen kode kopiert):** holdude/TrumfScraper, palhatlem/grocious, ttyridal/trumf-data-fetch,
  olejorgenb/trumf_receipt_tools.
- **Ikke verifisert:** sidene er uoffisielle. Feltnavnene er hentet fra åpne prosjekter fra 2026; om listen pagineres
  (bare siste måneder?) vet vi først etter Oles første ekte kjøring.

## `spending.json` – felles kvitteringsformat (`matkassa.spending/1`)

Alle kilder (REMA-skriptet, Claude-tolkede kvitteringer, fremtidige adaptere) skriver dette formatet.
Appen godtar også en ren liste med kvitteringer.

```json
{
  "schema": "matkassa.spending/1",
  "generated": "2026-10-24T18:00:00+02:00",
  "source": "rema",
  "receipts": [
    {
      "id": "rema-1001414032394",
      "source": "rema",
      "chain": "REMA 1000",
      "store": "REMA 1000 Sentrum",
      "date": "2026-10-20",
      "time": "17:32",
      "total": 412.50,
      "currency": "NOK",
      "category": null,
      "lines": [
        {
          "name": "COCA-COLA UTEN SUKKER 1.5L 4PK",
          "ean": "7090000248123",
          "qty": 1,
          "unit": "stk",
          "amount": 91.90,
          "discount": 0,
          "deposit": 12.0,
          "group": "BRUS (STOR)",
          "category": null
        }
      ]
    }
  ]
}
```
*(Verdiene over er bare et eksempel på formatet, ikke ekte data.)*

| Felt | Påkrevd | Betydning |
|---|---|---|
| `id` | ja | Stabil, unik id. Brukes til å unngå duplikater ved ny import (samme id = oppdateres) |
| `source` | ja | `rema`, `trumf`, `claude`, `manual` … |
| `chain`, `store` | ja (minst én) | Kjede og butikknavn |
| `date` | ja | `YYYY-MM-DD` (også `dd.mm.yyyy` godtas) |
| `time` | nei | `HH:MM` |
| `total` | ja* | Betalt beløp i kr (tall). *Kan utelates hvis `lines` finnes, da brukes summen |
| `category` | nei | Kategori-id for hele kvitteringen når den ikke har varelinjer |
| `lines[].name` | ja | Varenavn slik det står på kvitteringen |
| `lines[].amount` | ja | Linjebeløp i kr (inkl. pant, etter rabatt) |
| `lines[].ean` | nei | Strekkode/GTIN, gir de sikreste reglene |
| `lines[].group` | nei | Kjedens egen varegruppe (REMA). Brukes som hint av kategorimotoren |
| `lines[].category` | nei | Kategori-id hvis kilden allerede vet den (`meieri`, `kjott`, `frukt`, `brod`, `torr`, `snacks`, `drikke`, `frossen`, `hus`, `annet` eller en egen) |
| `qty`, `unit`, `discount`, `deposit` | nei | Info |

**Kategorimotoren i appen:** `lines[].category` → EAN-regel → tekstregel (lengste først) → innebygd
nøkkelordkart på varenavnet → nøkkelordkart på `group` → *Ukategorisert*. Differanse over 1 kr mellom
`total` og summen av linjene havner i *Ukategorisert*.

## Synk til appen (`sync.sh`)

`sync.sh` henter fra kildene du har logget inn på (REMA: `~/.rema1000/tokens.json`, Trumf: `~/.matkassa/trumf_state.json`),
slår dem sammen med `merge.py`, og leverer til:
- **Matkassa-kontoen din** (anbefalt, ingen GitHub-nøkkel): kjør `python3 ingest/cloud.py login` én gang. Se [SUPABASE.md](../SUPABASE.md).
- **og/eller ditt private datarepo** (den eldre veien, under), hvis `MATKASSA_DATA_REPO` er satt.

En kilde som feiler (f.eks. utløpt Trumf-innlogging) stopper ikke de andre, men jobben ender med feil (kode 3) og et
macOS-varsel med hva du må gjøre.

### Den eldre veien: privat GitHub-repo – for hvem som helst

Hver bruker har sin egen innlogging, sitt eget private repo og sin egen nøkkel. Ingenting deles mellom brukere,
og «Tilbud for deg» lærer bare av kvitteringene på brukerens egen telefon.

1. `rema auth login` med ditt eget telefonnummer.
2. Lag et **privat** GitHub-repo, f.eks. `<deg>/matkassa-data` (tomt).
3. `cp ingest/.env.example ingest/.env` og sett `MATKASSA_DATA_REPO=<deg>/matkassa-data`.
4. Kjør `ingest/sync.sh`. Den kloner repoet til `data/` (git-ignorert), skriver `spending.json` og
   `rema-offers.json` og pusher. Den **nekter å pushe til et offentlig repo**, og stopper hvis `data/` peker på et annet repo.
5. Lag en *fine-grained* GitHub-nøkkel med bare **Contents: Read** på akkurat det repoet, og lim den inn i appen
   (Mer → Synk fra Mac, sammen med repo-navnet). Appen henter fila når den åpnes, maks én gang i timen.
   Nøkkelen lagres bare på den enheten (ikke i backup). På iPhone har Safari og hjem-skjerm-appen hver sin lagring:
   lim den inn i appen du faktisk bruker.

### Automatisk hver uke (launchd)

`ingest/launchd/` gjør at Mac-en kjører `sync.sh` selv, **søndag kl. 20:00**:

```bash
ingest/launchd/install.sh             # installerer ~/Library/LaunchAgents/no.matkassa.weekly-sync.plist
ingest/launchd/install.sh --run-now   # … og kjører én gang med en gang
launchctl kickstart gui/$(id -u)/no.matkassa.weekly-sync   # kjør nå (når som helst)
ingest/launchd/uninstall.sh           # fjern jobben (loggene beholdes)
cat ingest/logs/last-run.txt          # status for siste kjøring
```

| Fil | Hva |
|---|---|
| `matkassa-weekly-sync.plist.template` | Mal med plassholdere (`__APP_DIR__`, `__PATH__`, tidspunkt). `install.sh` fyller inn og validerer med `plutil` |
| `run-sync.sh` | Det launchd starter: kjører `sync.sh`, logger, skriver status, varsler ved feil |
| `install.sh` / `uninstall.sh` | Installer/fjern for innlogget bruker (`launchctl bootstrap/bootout gui/<uid>`) |

- **Logg:** `ingest/logs/sync.log` (git-ignorert, de siste 2 000 linjene). launchd selv skriver til `ingest/logs/launchd.log`.
- **Status:** `ingest/logs/last-run.txt` med `status=OK` eller `status=FEIL`, start/slutt, exit-kode og siste linje fra synken.
  Ved feil kommer også et macOS-varsel («Matkassa: ukentlig synk feilet»).
- **PATH:** launchd starter jobber med en minimal PATH. `install.sh` finner `python3`, `git`, `brotli` og `gh` der de er
  nå og skriver mappene inn i plist-en. Installerer du dem et annet sted, eller flytter mappen, kjør `install.sh` på nytt.
- **Innlogging:** `git push` bruker macOS-nøkkelringen (osxkeychain), REMA-tokenet leses fra `~/.rema1000/tokens.json`.
  Ingenting skrives ut: git kjører stille uten spørsmål (`GIT_TERMINAL_PROMPT=0`), og alt som ligner et token maskeres i loggen.
- **Offentlig repo:** `sync.sh` nekter fortsatt å pushe hvis datarepoet er offentlig (da blir status `FEIL`).
- **Sover eller av:** sover Mac-en søndag 20:00, kjører jobben når den våkner. Er den **slått av**, hoppes uka over til
  neste søndag; kjør da `launchctl kickstart …` eller `ingest/launchd/run-sync.sh` for hånd.
- REMA-innloggingen utløper av og til. Da feiler synken med en melding i status/varsel; kjør `rema auth login` på nytt.

Ekte flerbruker uten Mac og GitHub (kontoer, Supabase med radnivåsikkerhet) er beskrevet som fase 7 i `plan.md`.

## Formatet `rema-offers.json` (`matkassa.offers/1`)
`{schema, generated, source:"rema-campaign", chain, offers:[{id, title, desc, price, prePrice, unitPrice, unit, from, till, img, eans:[GTIN…], group}]}`.
Offentlige tilbud, ingen persondata, men hentet med din innlogging, så de ligger i det private repoet.
