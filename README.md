# PE Deal Radar

![tests](https://github.com/ChuchoMonster/pe-deal-radar/actions/workflows/tests.yml/badge.svg)

A small Python prototype that screens new private-company fundraises from SEC Form D filings, keeps the operating companies (not the funds), tracks each company's fundraising history, and optionally looks up leadership contacts. It does the first pass of a private-equity deal-sourcing analyst's job.

About 650 lines of Python, standard library only. See **[examples/weekly-deal-radar-sample.md](examples/weekly-deal-radar-sample.md)** for the kind of weekly report it feeds.

## What's here

| File | Role |
|---|---|
| `deal_radar.py` | Pulls, parses and filters Form D filings into `output/survivors.{json,csv}` |
| `enrich_history.py` | Adds each company's full Form D history (the lifecycle / "aging" signal) to `output/survivors_enriched.json` |
| `blitz_enrich.py` | Blitz API contact lookup: company LinkedIn, then decision-makers with titles, then verified work emails. Writes `output/blitz_enriched.json`, `output/blitz_contacts.csv` |
| `fullenrich_enrich.py` | FullEnrich waterfall for companies Blitz couldn't cover. Uses officer names from the Form D plus the company domain |
| `examples/weekly-deal-radar-sample.md` | A sample weekly report built from one run |

## How it works

| Step | What | Automated? |
|---|---|---|
| 1. Discover | EDGAR full-text search lists Form D filings in a date range | Yes, `deal_radar.py` (free, no key) |
| 2. Parse | Fetch each filing's `primary_doc.xml`. Extract issuer, industry, offering size, securities, named officers | Yes, `deal_radar.py` |
| 3. Filter | US only, drop amendments, pooled investment funds, real estate, LPs/SPVs and name-flagged vehicles, $1M floor | Yes, `deal_radar.py` |
| 4. Lifecycle | EDGAR submissions API gives each company's full filing history: first-time vs. serial vs. *aging* raiser | Yes, `enrich_history.py` (free) |
| 5. Company research | What the company does, the round and investors, and catching vehicles the structured data hides | **No. Done interactively with Claude** (web research in a chat session) |
| 6. Domain discovery | Map legal entity name to operating brand, website domain and LinkedIn company page | **No. Done interactively with Claude.** Results are hard-coded in the `DISCOVERED` map in `blitz_enrich.py` |
| 7. Contacts | Feed the company LinkedIn URL into Blitz people search, then email lookup. Then FullEnrich for the gaps | Yes, `blitz_enrich.py`, `fullenrich_enrich.py` (paid credits) |

Steps 5 and 6 are **not in the code**. In this prototype they were manual research steps run with Claude, and their output was pasted into `DISCOVERED` and into the sample report's memos. Automating them would mean adding a web-search step.

### The domain-discovery trick (step 6)
Holding companies and SPVs often file under names that differ from their website. If searching the brand finds nothing, search the **legal entity name** and read the top result's title. Examples:
- *First Ottawa Bancshares → American Commercial Bank & Trust → acbandt.com*
- *Howdy 12.0 LLC → Howdy Homemade Ice Cream*

## Run it

```bash
cp .env.example .env   # or export the variables
export SEC_USER_AGENT="Your Name your.email@example.com"   # required by SEC

python3 deal_radar.py        # ~1–2 min for a 300-filing sample
python3 enrich_history.py    # adds filing-history lifecycle signal
python3 blitz_enrich.py      # optional, uses Blitz credits, incremental (cached)
python3 fullenrich_enrich.py # optional, uses FullEnrich credits
```

Settings at the top of `deal_radar.py`: `START`/`END` dates, `MIN_OFFERING`, `SCAN_LIMIT`. Results go to `output/`, which is git-ignored.

### Environment variables

| Variable | Used by | Notes |
|---|---|---|
| `SEC_USER_AGENT` | `deal_radar.py`, `enrich_history.py` | SEC asks for a name and email in the User-Agent. The placeholder default is `Your Name your.email@example.com`, so replace it |
| `BLITZ_API_KEY` | `blitz_enrich.py` | Blitz API key |
| `FULLENRICH_API_KEY` | `fullenrich_enrich.py` | FullEnrich key. Without it, the script lists its targets and exits |

Keys are read from the environment first, then from a local `.env`.

## Tests

- `python3 -W ignore::ResourceWarning -m unittest discover -s tests -v` from the repo root. Standard library only, nothing to install.
- Covers Form D XML parsing, EDGAR search pagination, every survivor filter, the filing-history lifecycle signal, and the Blitz / FullEnrich target selection.
- No network and no keys: SEC, Blitz and FullEnrich calls are replaced with fakes and fictional fixtures in `tests/fixtures/`.
- Runs on every push and pull request via GitHub Actions.

## Known limitations

- **Stage isn't in Form D.** "Series A/B/C" is inferred from how many raises there were and their size, not read from the filing.
- **Some fund/SPV noise remains.** A few vehicles tagged "Other"/"Investing" still slip through the structured filters. The manual research pass catches the rest.
- **The sample is the most recent N filings**, not a full month. A production version would run on a schedule and build up history over time, which is what makes the aging signal useful.
- **Blitz coverage skews toward established companies.** In the sample run, Blitz reached 17 of 29 companies (25 decision-makers, 14 verified emails). The misses were either people missing from Blitz's index or companies with no web presence at all. For those, the officers named in the Form D are the starting point.
- **API drift.** Blitz endpoints moved under `/v2`. People search is `/v2/search/waterfall-icp-keyword` (results nested under `.person`), and email lookup takes `person_linkedin_url`.

## Use responsibly

Government data and official APIs only. Respect SEC's User-Agent and rate limits; the script sleeps to stay under 10 requests a second. Output is educational research, not investment advice. Contact data from paid enrichment APIs is personal data, so handle it under the providers' terms and applicable privacy and anti-spam law.
