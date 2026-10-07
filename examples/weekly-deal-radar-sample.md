# PE Deal Radar — Weekly Private-Capital Screen
### Sample run · filings from the past month, generated June 18, 2026

> A script reads recent private-company fundraises filed with the SEC (Form D), throws out
> the funds and real estate, and surfaces the operating companies actually raising money.
> The company research and memos below were then done interactively with Claude (web research),
> not by the code in this repo.
>
> *Educational research, not investment advice. All data from public SEC filings + public web sources.*

---

## What this run did

| Step | Result |
|---|---|
| Form D filings scanned (SEC EDGAR, free) | **300** most recent |
| Pooled investment funds removed (PE/VC/hedge funds raising their *own* capital) | 194 were funds |
| Amendments, foreign issuers, real estate, sub-$1M raises removed | — |
| **Operating-company capital raises surfaced** | **31** |
| Researched in depth below | 6 |

**The filter funnel** (why this isn't just a data dump):

```
300 filings  ──►  remove 194 fund filings  ──►  remove amendments / non-US /
                  real estate / LPs / SPVs / sub-$1M  ──►  31 real company raises
```

Two-thirds of all Form D activity is funds raising money. The point of the filter is to
throw that away and keep the companies — the deals.

---

## This week's screen — ranked by raise size

| Company | What it does | Raise | Stage signal | Location |
|---|---|---|---|---|
| **TBG Food Acquisition Corp** | Dunkin'/Baskin-Robbins franchise roll-up (PE platform, Beekman Group) | $296.4M | 1st SEC raise of a 20-yr-old platform | Foster City, CA |
| **Panorama AI Corp (dba Gradial)** | AI personalization for retailers | $65.0M | 4th raise — Series B led by Madrona | Seattle, WA |
| **Rythm Health** | Healthcare tech | $31.1M | 4th raise since 2025 (fast climber) | San Francisco, CA |
| **Rejuvenate Bio** | Gene therapy for aging (Harvard lab spinout) | $27.0M | 2nd raise; $40M+ total to date | San Diego, CA |
| **Ceek Women's Health** | Gynecological medical devices (Nella line) | $27.0M | 🟡 5th raise since 2019 — *aging* | Portland, OR |
| **Classic.com** | Classic-car marketplace + price data | $6.0M | 🟡 5th raise since 2021 | Miami, FL |
| Spaxial Interactive | Tech (first raise) | $25.0M | 1st raise | Fort Lauderdale, FL |
| Emblok | Biotech (first raise) | $12.0M | 1st raise | Tampa, FL |
| Portage AI | Enterprise AI implementation | $7.0M | 1st raise (fresh seed) | Newport, RI |
| Harmony AI | Tech (first raise) | $2.0M | 1st raise | — |

*…plus 21 more in the full survivors list (`output/survivors.csv` when you run it).*

---

## Four screening memos (researched interactively with Claude)

### 🚀 Gradial (filed as "Panorama Artificial Intelligence Corp.") — GROWTH
- **Business:** Privacy-first AI personalization platform for retailers; predicts and converts shoppers using first-party data.
- **The filing:** $65M offering, fully sold, equity. 4th Form D since Nov 2023.
- **What enrichment added:** The legal name hides a known company — it operates as **Gradial**. The latest round is a **$35M Series B led by Madrona**, with Pruven Capital, General Advance, and Outsiders Fund. ~$1.3M revenue, 12-person team (2025).
- **Read:** A genuine venture-backed growth story climbing the rounds. The kind of company a growth-equity fund tracks for the *next* round.
- **Why it matters:** the company name on the SEC filing ≠ the brand. Only the research connects them.

### 🟡 Ceek Women's Health — AGING / POTENTIAL BUYOUT
- **Business:** Medical devices for gynecological care — the Nella speculum line (NuSpec, VuSleeve, VuLight). Founded 2015.
- **The filing:** $27M offering. **5th Form D, first filed 2019.**
- **What enrichment added:** ~$24.7M raised over the years; investors include Northstar Ventures and Squadron Capital. Slow, steady raising — not a rocket ship.
- **Read:** This is the PE-relevant signal in action. A real product company that has been raising for 6+ years without an exit reads as a **maturing asset under pressure to find liquidity** — exactly the profile a buyout or secondary fund wants to know. *The "lateness" of the filing is the point.*

### 🧬 Rejuvenate Bio — DEEP-TECH / ACADEMIC SPINOUT
- **Business:** Combination gene therapy targeting multiple age-related diseases; spun out of a **Harvard genetics lab** (2018).
- **The filing:** $27M offering, equity. 2nd Form D since 2021.
- **What enrichment added:** $40M+ raised (Merck Animal Health, Digitalis Ventures, KdT Ventures, Kendall Capital) + $13M non-dilutive DoD/SOCOM funding. Proven in dogs, advancing to humans.
- **Read:** Prominent academic origin + strategic corporate investor (Merck) + government grants = a credible, well-syndicated deep-tech bet.

### 🍩 TBG Food Acquisition Corp — THE ONE THE FILTER ALMOST MISLABELED
- **The filing:** $296M — by far the biggest, tagged blandly as "Business Services," first-ever SEC raise. Looked like it might be a shell/vehicle.
- **What enrichment revealed:** It's a **PE-backed quick-service-restaurant roll-up** — 75 Dunkin' and 8 Baskin-Robbins locations, operating since 2005, owned by **The Beekman Group** (a middle-market PE firm). (Filing lists Foster City, CA; public records say Tuckahoe, NY — a discrepancy worth noting.)
- **Read:** Not noise — this *is* private equity. A platform company raising capital to keep acquiring franchises. The structured filing could never tell you this; one research pass did.
- **Why it matters:** shows why the research layer exists — and what a PE "platform roll-up" actually looks like in the wild.

---

## What's automated vs. what was done by hand

- **Automated (code in this repo):** pull Form D filings, parse them, filter out funds / real estate / vehicles, attach each company's Form D history, and (optionally) look up leadership contacts via Blitz / FullEnrich.
- **Done interactively with Claude:** the web research behind "What it does", the round/investor details, the legal-name-to-brand matching, and the memo write-ups above.
- **Human judgment:** setting the screen (size, sector, geography) and deciding which companies are worth a closer look.

---
*Sources: company data from [SEC EDGAR](https://www.sec.gov/cgi-bin/browse-edgar) Form D filings; enrichment from [Crunchbase](https://www.crunchbase.com/organization/panorama-ai), [The SaaS News](https://www.thesaasnews.com/news/gradial-raises-35-million-series-b), [PitchBook](https://pitchbook.com/profiles/company/300926-98), [The Beekman Group](https://thebeekmangroup.com/), [Rejuvenate Bio](https://rejuvenatebio.com/press-releases/series), [BioSpace](https://www.biospace.com/business/rejuvenate-crowdfunds-development-of-gene-therapy-for-aging-chronic-diseases).*
