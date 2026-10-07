"""
PE Deal Radar — prototype pull of SEC Form D filings.

Pulls recent Form D filings from EDGAR (free, no key), parses the structured
primary_doc.xml for each, and filters down to operating-company capital raises
that look like real deal-sourcing targets:

  - US issuers only
  - new notices only (not amendments)
  - exclude pooled investment funds (they're funds raising, not companies)
  - exclude real estate (that's its own desk)
  - minimum offering size floor (cuts the long tail of tiny raises)

Output: a clean JSON + CSV + a readable markdown table of survivors, plus a
breakdown of what got filtered and why.
"""
import csv
import json
import os
import re
import time
import urllib.request
import urllib.parse

# ---- config ---------------------------------------------------------------
# SEC requires a descriptive User-Agent with contact info:
# https://www.sec.gov/os/accessing-edgar-data
UA = os.environ.get("SEC_USER_AGENT", "Your Name your.email@example.com")
START = "2026-05-18"
END = "2026-06-18"
MIN_OFFERING = 1_000_000          # floor: cut sub-$1M raises
SCAN_LIMIT = 300                  # how many recent filings to pull for this sample
REQ_SLEEP = 0.13                  # be polite to SEC (<10 req/s)
OUTDIR = "output"

US_STATES = {
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA",
    "KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT",
    "VA","WA","WV","WI","WY","DC","PR","GU","VI","AS","MP",
}
# Form D industryGroupType values that mean "real estate"
# (SEC spells these with "and", not "&" — getting this wrong leaks REITs through)
REAL_ESTATE = {"Commercial", "Construction", "REITS and Finance", "Residential", "Other Real Estate"}
# "Investing" entities are investment vehicles, not operating companies → fund noise.
POOLED_FUND = {"Pooled Investment Fund", "Investing"}
# Second-layer catch for fund/RE/SPV vehicles that mis-tag their industry group:
# name markers (REIT, Fund, StartEngine series, "Capital Partners"), or the issuer
# is a Limited Partnership (in Form D land, LPs are overwhelmingly funds/SPVs).
NAME_VEHICLE = re.compile(r"\b(REIT|REITs|Fund|StartEngine)\b|Capital Partners|\ba series of\b", re.I)


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def fts_page(frm):
    params = {"forms": "D", "startdt": START, "enddt": END, "from": frm}
    url = "https://efts.sec.gov/LATEST/search-index?" + urllib.parse.urlencode(params)
    return json.loads(get(url))


def collect_filings(limit):
    out, frm, seen = [], 0, set()
    while len(out) < limit:
        data = fts_page(frm)
        hits = data.get("hits", {}).get("hits", [])
        if not hits:
            break
        for h in hits:
            src = h.get("_source", {})
            acc = src.get("adsh", "")
            if acc in seen:
                continue
            seen.add(acc)
            ciks = src.get("ciks") or []
            out.append({
                "accession": acc,
                "cik": str(int(ciks[0])) if ciks else "",
                "name": (src.get("display_names") or [""])[0],
                "file_date": src.get("file_date", ""),
                "biz_location": (src.get("biz_locations") or [""])[0],
            })
        frm += len(hits)
        time.sleep(REQ_SLEEP)
    return out[:limit]


# Form D primary_doc.xml is flat, machine-generated, namespace-free — regex
# extraction is reliable and sidesteps the broken pyexpat in this Python build.
def _block(s, tag):
    m = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", s, re.S)
    return m.group(1) if m else ""


def _val(s, tag):
    m = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", s, re.S)
    v = m.group(1).strip() if m else ""
    return v or None


def _to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def parse_formd(cik, accession):
    acc_nodash = accession.replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/primary_doc.xml"
    xml = get(url)

    pi = _block(xml, "primaryIssuer")
    addr = _block(pi, "issuerAddress")
    od = _block(xml, "offeringData")

    securities = []
    sec_block = _block(od, "typesOfSecuritiesOffered")
    for m in re.finditer(r"<is(\w+?)Type>(.*?)</is\1Type>", sec_block):
        if m.group(2).strip().lower() == "true":
            securities.append(m.group(1))

    persons = []
    for blk in re.findall(r"<relatedPersonInfo>(.*?)</relatedPersonInfo>", xml, re.S):
        fn = _val(blk, "firstName") or ""
        ln = _val(blk, "lastName") or ""
        roles = [r.strip() for r in re.findall(r"<relationship>(.*?)</relationship>", blk, re.S) if r.strip()]
        nm = f"{fn} {ln}".strip()
        if nm:
            persons.append({"name": nm, "roles": roles})

    is_fund = ("<investmentFundInfo" in xml) or bool(re.search(r"<isPooledInvestmentFundType>\s*true", xml))

    return {
        "entity": _val(pi, "entityName"),
        "entity_type": _val(pi, "entityType"),
        "state": _val(addr, "stateOrCountry"),
        "city": _val(addr, "city"),
        "jurisdiction": _val(pi, "jurisdictionOfInc"),
        "year_inc": _val(_block(pi, "yearOfInc"), "value"),
        "industry": _val(od, "industryGroupType"),
        "revenue_range": _val(od, "revenueRange"),
        "is_amendment": (_val(od, "isAmendment") == "true"),
        "date_first_sale": _val(_block(od, "dateOfFirstSale"), "value"),
        "securities": securities,
        "min_investment": _val(od, "minimumInvestmentAccepted"),
        "offering_amount": _to_int(_val(od, "totalOfferingAmount")),
        "amount_sold": _to_int(_val(od, "totalAmountSold")),
        "num_invested": _val(od, "totalNumberAlreadyInvested"),
        "is_fund": is_fund,
        "persons": persons,
    }


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    print(f"Scanning up to {SCAN_LIMIT} most-recent Form D filings ({START} to {END})...")
    filings = collect_filings(SCAN_LIMIT)
    print(f"  pulled {len(filings)} filing references")

    survivors, dropped = [], {"non_us": 0, "amendment": 0, "pooled_fund": 0,
                              "real_estate": 0, "limited_partnership": 0,
                              "vehicle_name": 0, "below_min": 0, "parse_error": 0}
    industry_counts = {}

    for i, f in enumerate(filings):
        try:
            d = parse_formd(f["cik"], f["accession"])
        except Exception:
            dropped["parse_error"] += 1
            continue
        time.sleep(REQ_SLEEP)

        ind = d["industry"] or "Unknown"
        industry_counts[ind] = industry_counts.get(ind, 0) + 1

        if d["state"] not in US_STATES:
            dropped["non_us"] += 1; continue
        if d["is_amendment"]:
            dropped["amendment"] += 1; continue
        if d["is_fund"] or ind in POOLED_FUND:
            dropped["pooled_fund"] += 1; continue
        if ind in REAL_ESTATE:
            dropped["real_estate"] += 1; continue
        if (d["entity_type"] or "") == "Limited Partnership":
            dropped["limited_partnership"] += 1; continue
        if NAME_VEHICLE.search(d["entity"] or ""):
            dropped["vehicle_name"] += 1; continue
        if d["offering_amount"] is None or d["offering_amount"] < MIN_OFFERING:
            dropped["below_min"] += 1; continue

        # round still open if not yet fully sold (totalRemaining > 0)
        d["actively_raising"] = (d["amount_sold"] is None) or (d["amount_sold"] < d["offering_amount"])
        d.update({"cik": f["cik"], "accession": f["accession"], "file_date": f["file_date"]})
        survivors.append(d)
        if (i + 1) % 50 == 0:
            print(f"  ...processed {i+1}, {len(survivors)} survivors so far")

    survivors.sort(key=lambda x: x["offering_amount"], reverse=True)

    # write outputs
    with open(f"{OUTDIR}/survivors.json", "w") as fh:
        json.dump(survivors, fh, indent=2)
    with open(f"{OUTDIR}/survivors.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["entity", "industry", "actively_raising", "state", "city",
                    "offering_amount", "amount_sold", "year_inc", "date_first_sale",
                    "securities", "lead_person", "cik", "accession", "file_date"])
        for s in survivors:
            w.writerow([s["entity"], s["industry"], "Y" if s["actively_raising"] else "N",
                        s["state"], s["city"], s["offering_amount"], s["amount_sold"],
                        s["year_inc"], s["date_first_sale"], "|".join(s["securities"]),
                        s["persons"][0]["name"] if s["persons"] else "",
                        s["cik"], s["accession"], s["file_date"]])

    # summary
    print("\n=== FILTER SUMMARY ===")
    print(f"scanned: {len(filings)}")
    for k, v in dropped.items():
        print(f"  dropped ({k}): {v}")
    print(f"SURVIVORS: {len(survivors)}")
    print("\n=== industry distribution (all scanned) ===")
    for k, v in sorted(industry_counts.items(), key=lambda x: -x[1]):
        print(f"  {v:>4}  {k}")
    print(f"\n=== TOP SURVIVORS (by offering size) ===")
    for s in survivors[:20]:
        amt = f"${s['offering_amount']:,}"
        sold = f"${s['amount_sold']:,}" if s['amount_sold'] is not None else "?"
        print(f"  {amt:>16} sold {sold:>14}  {s['industry']:<22} {s['entity']}  ({s['city']}, {s['state']})")


if __name__ == "__main__":
    main()
