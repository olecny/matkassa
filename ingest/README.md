# ingest – kvitteringsdata fra Mac til Matkassa

Skript som kjører på Mac-en (Jarvis-maskinen) og lager `spending.json`, som du importerer i appen
(**Forbruk → Importer fil**). Data og tokens forlater aldri Mac-en / telefonen, og blir aldri committet
(`.env` og `spending*.json` er git-ignorert).

| Skript | Status |
|---|---|
| `rema.py` | Testet mot en ekte konto (101 kvitteringer, varelinjesum = total). `--offers` henter REMAs Superpris-tilbud med strekkoder (GTIN). Endepunkter fra [rema1000-cli](https://github.com/Alfredvc/rema1000-cli) `API.md` |
| `sync.sh` | Kjører `rema.py` og pusher til **ditt eget private** datarepo, som appen synker fra |
| Trumf | Trengs ikke på Mac: Trumf-innsyn (JSON) importeres direkte i appen |
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

## Synk til appen (`sync.sh`) – for hvem som helst

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

Ekte flerbruker uten Mac og GitHub (kontoer, Supabase med radnivåsikkerhet) er beskrevet som fase 7 i `plan.md`.

## Formatet `rema-offers.json` (`matkassa.offers/1`)
`{schema, generated, source:"rema-campaign", chain, offers:[{id, title, desc, price, prePrice, unitPrice, unit, from, till, img, eans:[GTIN…], group}]}`.
Offentlige tilbud, ingen persondata, men hentet med din innlogging, så de ligger i det private repoet.
