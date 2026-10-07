"""
FullEnrich enrichment — closes "Gap B" (company exists, but its people aren't in
Blitz's index). FullEnrich is an email/phone WATERFALL (runs ~15 providers and
returns the best hit), and it works from {first, last, domain} — no LinkedIn match
needed. That's the exact shape we already have: officer names from the Form D
filing + domains from our discovery step.

Targets: companies that have a domain but no verified email yet. For each, we feed
the Form D's named officers (Executive Officers first) + any Blitz-found person who
lacked an email. Async bulk API: submit -> poll.

Key: set FULLENRICH_API_KEY in the environment or in a local .env
(get one at https://app.fullenrich.com/settings).
"""
import json
import os
import re
import time
import urllib.request
import urllib.error

BASE = "https://api.fullenrich.com"
OUT = "output/fullenrich_results.json"
SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v", "md", "phd", "do", "esq", "facc"}


def load_key():
    if os.environ.get("FULLENRICH_API_KEY"):
        return os.environ["FULLENRICH_API_KEY"]
    if os.path.exists(".env"):
        for line in open(".env"):
            if line.strip().startswith("FULLENRICH_API_KEY="):
                v = line.split("=", 1)[1].strip().strip('"').strip("'")
                if v:
                    return v
    return None


def split_name(full):
    parts = [p for p in re.sub(r"[.,]", " ", full or "").split() if p.lower() not in SUFFIXES]
    if len(parts) < 2:
        return None
    return parts[0], parts[-1]


def post(url, payload, key):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read().decode())


def get(url, key):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read().decode())


def build_candidates():
    """One contact per (company, person): officers + Blitz people who lacked an email."""
    survivors = {s["entity"]: s for s in json.load(open("output/survivors_enriched.json"))}
    blitz = {r["entity"]: r for r in json.load(open("output/blitz_enriched.json"))}
    cands = []
    for name, b in blitz.items():
        dom = b.get("domain")
        if not dom:
            continue  # FullEnrich needs a domain
        has_email = any(c.get("email") for c in b.get("contacts", []))
        if has_email:
            continue  # already have a verified email — skip to save credits
        seen, picked = set(), []
        # 1) Blitz people we found but couldn't email (we even have their LinkedIn)
        for c in b.get("contacts", []):
            nm = split_name(c.get("name", ""))
            if nm and nm[1].lower() not in seen:
                seen.add(nm[1].lower())
                picked.append({"firstname": nm[0], "lastname": nm[1], "domain": dom,
                               "company_name": name, "linkedin_url": c.get("linkedin")})
        # 2) Form D officers (Executive Officer roles first, then directors), cap 3
        persons = survivors[name].get("persons", [])
        execs = [p for p in persons if any("Executive" in r for r in p.get("roles", []))]
        for p in execs + persons:
            if len(picked) >= 3:
                break
            nm = split_name(p.get("name", ""))
            if nm and nm[1].lower() not in seen:
                seen.add(nm[1].lower())
                picked.append({"firstname": nm[0], "lastname": nm[1], "domain": dom,
                               "company_name": name})
        for c in picked:
            cands.append(c)
    return cands


def main():
    key = load_key()
    cands = build_candidates()
    targets = sorted({c["company_name"] for c in cands})
    print(f"FullEnrich targets: {len(targets)} companies, {len(cands)} contacts (domain + name, no verified email yet)\n")
    for t in targets:
        print(f"  • {t}")

    if not key:
        print("\n*** FULLENRICH_API_KEY not set — script is wired and ready. ***")
        print("Add the key to .env (or export it), get one at")
        print("https://app.fullenrich.com/settings, then re-run: python3 fullenrich_enrich.py")
        return

    print(f"\nSubmitting {len(cands)} contacts to FullEnrich bulk...")
    contacts = [{k: v for k, v in c.items() if v} for c in cands]
    sub = post(f"{BASE}/contact/enrich/bulk", {"contacts": contacts}, key)
    eid = sub.get("enrichment_id")
    print(f"enrichment_id={eid}, polling...")

    results = []
    interval, start = 2, time.time()
    while time.time() - start < 300:
        data = get(f"{BASE}/bulk/{eid}", key)
        if data.get("status") == "completed":
            results = data.get("results", [])
            break
        if data.get("status") == "failed":
            print("FullEnrich job failed"); return
        time.sleep(interval); interval = min(interval * 2, 30)

    # map results back to companies
    by_company = {}
    found = 0
    for r in results:
        em = r.get("email") or r.get("emails", [{}])[0].get("email") if isinstance(r.get("emails"), list) else r.get("email")
        nm = f"{r.get('firstname','')} {r.get('lastname','')}".strip()
        co = r.get("company_name") or "?"
        rec = {"name": nm, "email": em, "phone": r.get("phone"),
               "linkedin": r.get("linkedin_url"), "status": r.get("email_status")}
        by_company.setdefault(co, []).append(rec)
        if em:
            found += 1

    json.dump(by_company, open(OUT, "w"), indent=2)
    print(f"\n=== FullEnrich results ===")
    for co, ppl in by_company.items():
        for p in ppl:
            if p["email"]:
                print(f"  {co:<34} {p['name']:<22} {p['email']}  [{p.get('status') or ''}]")
    new_cos = sum(1 for ppl in by_company.values() if any(p["email"] for p in ppl))
    print(f"\nNew emails: {found} across {new_cos} companies (Gap-B closure)")


if __name__ == "__main__":
    main()
