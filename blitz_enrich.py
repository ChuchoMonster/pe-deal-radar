"""
Blitz enrichment for the PE Deal Radar survivors — domain-discovery version.

Blitz's keyword company-search is fuzzy and misses brand-new filers, and its
domain->linkedin endpoint is gone. So we discover each company's LinkedIn COMPANY
url up front (web research, captured in DISCOVERED below) and feed it STRAIGHT into
the people search — which only needs the company LinkedIn url. This reaches
companies whose *people* are in Blitz's index even when the *company* isn't.

Per company: company LinkedIn url -> waterfall-icp-keyword (leaders) -> email.
Company DESCRIPTION comes from the web-research pass; Blitz supplies people +
titles + verified emails.

Reads BLITZ_API_KEY from the environment (or a local .env). urllib only (no requests).
All live Blitz endpoints are under /v2.
"""
import csv
import json
import os
import time
import urllib.request
import urllib.error

V2 = "https://api.blitz-api.ai/v2"
OUT = "output/blitz_enriched.json"

# Discovered up front: legal entity name -> {domain, linkedin company url}.
# "" linkedin = no company page found (stealth / ambiguous) -> Blitz can't help.
DISCOVERED = {
    "Panorama Artificial Intelligence Corp.": {"domain": "gradial.com", "linkedin": "https://www.linkedin.com/company/gradialai"},
    "Rythm Health, Inc.":            {"domain": "rythmhealth.com", "linkedin": "https://www.linkedin.com/company/rythmhealth"},
    "Rejuvenate Bio Inc":            {"domain": "rejuvenatebio.com", "linkedin": "https://www.linkedin.com/company/rejuvenate-bio"},
    "Ceek Women's Health, Inc.":     {"domain": "ceekwomenshealth.com", "linkedin": "https://www.linkedin.com/company/ceekwomenshealth"},
    "Spaxial Interactive, Inc.":     {"domain": "", "linkedin": ""},
    "Emblok, Inc.":                  {"domain": "emblok.com", "linkedin": "https://www.linkedin.com/company/emblok"},
    "Portage AI Inc.":               {"domain": "portage.ai", "linkedin": "https://www.linkedin.com/company/portage-ai"},
    "5D Patient Journey, Inc.":      {"domain": "", "linkedin": ""},
    "Classic.com, Inc.":             {"domain": "classic.com", "linkedin": "https://www.linkedin.com/company/classicdotcom"},
    "Scitara Corp":                  {"domain": "scitara.com", "linkedin": "https://www.linkedin.com/company/scitara-corporation"},
    "SymKardia, Inc.":               {"domain": "symkardia.com", "linkedin": "https://www.linkedin.com/company/symkardia"},
    "Siensmetrica, Inc.":            {"domain": "siensmetrica.com", "linkedin": "https://www.linkedin.com/company/siensmetrica"},
    "Pierogi Therapeutics, Inc":     {"domain": "pierogitherapeutics.com", "linkedin": "https://www.linkedin.com/company/pierogi-therapeutics"},
    "Tahcar Inc":                    {"domain": "tahcar.com", "linkedin": "https://www.linkedin.com/company/tahcar"},
    "PromoShare, Inc.":              {"domain": "promoshare.com", "linkedin": "https://www.linkedin.com/company/promoshare"},
    "Stridekick, Inc.":              {"domain": "stridekick.com", "linkedin": ""},
    "imagi Education, Inc.":         {"domain": "imagilabs.com", "linkedin": "https://www.linkedin.com/company/imagilabs"},
    "Global Pain Center Corp.":      {"domain": "override.health", "linkedin": "https://www.linkedin.com/company/override-chronic-pain"},
    "Findara Inc.":                  {"domain": "findara.io", "linkedin": ""},
    "Harmony AI, Inc.":              {"domain": "petharmony.ai", "linkedin": "https://www.linkedin.com/company/askharmony"},
    "34 GiGs, Inc.":                 {"domain": "34gigs.com", "linkedin": "https://www.linkedin.com/company/34gigs"},
    "Emulated, Inc.":                {"domain": "", "linkedin": ""},
    "Integrated Reality Labs, Inc.": {"domain": "playslap.com", "linkedin": "https://www.linkedin.com/company/irl-game-labs"},
    # 2nd-pass discovery: legal name -> operating brand (often differs)
    "TBG Acquisitions, Inc.":        {"domain": "tbgdonuts.com", "linkedin": "https://www.linkedin.com/company/tbgfac"},
    "Commencement Bancorp, Inc.":    {"domain": "commencementbank.com", "linkedin": "https://www.linkedin.com/company/commencement-bank"},
    "FIRST OTTAWA BANCSHARES, INC.": {"domain": "acbandt.com", "linkedin": "https://www.linkedin.com/company/acbandt"},
    "TNEMEC CO INC":                 {"domain": "tnemec.com", "linkedin": "https://www.linkedin.com/company/tnemec-company-inc."},
    "Howdy 12.0, LLC":               {"domain": "howdyhomemade.com", "linkedin": "https://www.linkedin.com/company/howdy-homemade-ice-cream"},
    "Dreamcatcher Holdco, LLC":      {"domain": "dreamcatcher-events.com", "linkedin": "https://www.linkedin.com/company/dreamcatcher-events"},
}

# Pure holding/single-asset SPVs with no web presence — nothing for Blitz to find
SKIP = {
    "CTV6 Holdings, LLC", "LQ MN 1 LLC",
}

CASCADE_LEADERS = [{
    "include_title": ["CEO", "Chief Executive Officer", "Founder", "Co-Founder",
                      "President", "Managing Director", "CFO", "COO", "CTO"],
    "exclude_title": ["Vice President", "VP", "Assistant", "Associate", "intern"],
    "location": ["WORLD"],
    "include_headline_search": False,
}]

credits = {"n": 0}


def key():
    """BLITZ_API_KEY from the environment, falling back to ./.env."""
    if os.environ.get("BLITZ_API_KEY"):
        return os.environ["BLITZ_API_KEY"]
    if os.path.exists(".env"):
        for line in open(".env"):
            if line.strip().startswith("BLITZ_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


KEY = None


def post(url, payload):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, method="POST",
        headers={"x-api-key": KEY, "Content-Type": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(int(e.headers.get("Retry-After", 10))); continue
            if e.code >= 500:
                time.sleep(2 ** attempt); continue
            return None
        except Exception:
            time.sleep(2 ** attempt)
    return None


def find_people(li_url):
    data = post(f"{V2}/search/waterfall-icp-keyword",
                {"company_linkedin_url": li_url, "max_results": 4, "cascade": CASCADE_LEADERS})
    res = data.get("results", []) if isinstance(data, dict) else []
    credits["n"] += len(res)
    out = []
    for r in res:
        person = r.get("person", {}) or {}
        title = person.get("headline")
        for ex in (person.get("experiences") or []):
            if ex.get("job_is_current") and ex.get("company_linkedin_url") == li_url:
                title = ex.get("job_title") or title
                break
        out.append({
            "name": person.get("full_name") or f"{person.get('first_name','')} {person.get('last_name','')}".strip(),
            "title": title,
            "linkedin": person.get("linkedin_url"),
        })
    return out


def enrich_email(li):
    data = post(f"{V2}/enrichment/email", {"person_linkedin_url": li})
    credits["n"] += 1
    if isinstance(data, dict):
        return data.get("email") or (data.get("all_emails") or [{}])[0].get("email_address", "")
    return ""


def main():
    global KEY
    KEY = key()
    if not KEY:
        raise SystemExit("BLITZ_API_KEY not set (export it or add it to .env)")
    survivors = json.load(open("output/survivors_enriched.json"))
    targets = [s for s in survivors if s["entity"] not in SKIP]
    # Incremental: reuse prior results for companies whose LinkedIn url is unchanged
    prior = {}
    if os.path.exists(OUT):
        try:
            prior = {r["entity"]: r for r in json.load(open(OUT))}
        except Exception:
            prior = {}
    print(f"Enriching {len(targets)} companies (skipping {len(SKIP)} no-web SPVs)\n")

    out = []
    for i, s in enumerate(targets, 1):
        name = s["entity"]
        disc = DISCOVERED.get(name, {})
        li = disc.get("linkedin")

        # reuse cached result if we already processed this exact LinkedIn url
        prev = prior.get(name)
        if prev and prev.get("linkedin_url", "") == (li or "") and "contacts" in prev:
            prev["domain"] = disc.get("domain") or prev.get("domain", "")
            out.append(prev)
            tag = f"{len(prev.get('contacts', []))} ppl (cached)" if prev.get("contacts") else "cached"
            print(f"[{i}/{len(targets)}] {name:<38} -> {tag}")
            json.dump(out, open(OUT, "w"), indent=2)
            continue

        rec = {"entity": name, "city": s["city"], "state": s["state"],
               "domain": disc.get("domain") or "", "linkedin_url": li or "", "contacts": []}

        if not li:
            rec["blitz"] = "no LinkedIn company page (stealth)"
            print(f"[{i}/{len(targets)}] {name:<38} -> no LinkedIn page")
            out.append(rec); json.dump(out, open(OUT, "w"), indent=2); continue

        time.sleep(0.25)
        contacts = []
        for p in find_people(li):
            if p["linkedin"]:
                time.sleep(0.25)
                p["email"] = enrich_email(p["linkedin"])
            contacts.append(p)
        rec["contacts"] = contacts
        emails = sum(1 for c in contacts if c.get("email"))
        print(f"[{i}/{len(targets)}] {name:<38} -> {rec['domain'] or '?':<22} "
              f"{len(contacts)} ppl, {emails} emails  (credits: {credits['n']})")
        out.append(rec)
        json.dump(out, open(OUT, "w"), indent=2)
        time.sleep(0.25)

    with open("output/blitz_contacts.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["company", "domain", "company_linkedin", "name", "title", "person_linkedin", "email"])
        for r in out:
            for c in r.get("contacts", []):
                w.writerow([r["entity"], r.get("domain", ""), r.get("linkedin_url", ""),
                            c.get("name", ""), c.get("title", ""), c.get("linkedin", ""), c.get("email", "")])

    n_found = sum(1 for r in out if r.get("contacts"))
    n_contacts = sum(len(r.get("contacts", [])) for r in out)
    n_emails = sum(1 for r in out for c in r.get("contacts", []) if c.get("email"))
    print(f"\n=== DONE ===")
    print(f"companies with contacts: {n_found}/{len(targets)}")
    print(f"contacts: {n_contacts}   verified emails: {n_emails}   approx credits: {credits['n']}")


if __name__ == "__main__":
    main()
