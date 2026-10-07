"""
Add the lifecycle signal: for each survivor, pull its full EDGAR filing history
(via the free submissions API) and count prior Form D raises with dates.

  - first-ever Form D  -> fresh company, likely early
  - several over years  -> growth-stage, climbing the rounds
  - last one years ago  -> "aging", potential buyout / secondary target (PE angle)
"""
import json
import os
import time
import urllib.request

# SEC requires a descriptive User-Agent with contact info:
# https://www.sec.gov/os/accessing-edgar-data
UA = os.environ.get("SEC_USER_AGENT", "Your Name your.email@example.com")


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def filing_history(cik):
    url = f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json"
    data = json.loads(get(url))
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    d_dates = sorted(dt for fm, dt in zip(forms, dates) if fm in ("D", "D/A"))
    return {
        "company_name": data.get("name"),
        "all_form_d_dates": d_dates,
        "num_form_d": len(d_dates),
        "first_form_d": d_dates[0] if d_dates else None,
        "latest_form_d": d_dates[-1] if d_dates else None,
    }


def main():
    survivors = json.load(open("output/survivors.json"))
    for s in survivors:
        try:
            s["history"] = filing_history(s["cik"])
        except Exception as e:
            s["history"] = {"error": str(e)}
        time.sleep(0.13)

    json.dump(survivors, open("output/survivors_enriched.json", "w"), indent=2)

    print(f"{'OFFERING':>14}  {'#D':>3}  {'FIRST D':<10} {'INDUSTRY':<20} COMPANY")
    print("-" * 100)
    for s in survivors:
        h = s.get("history", {})
        n = h.get("num_form_d", "?")
        first = h.get("first_form_d") or "?"
        signal = ""
        if isinstance(n, int):
            if n == 1:
                signal = "first raise"
            elif first and first < "2021":
                signal = f"serial since {first[:4]} (aging?)"
            else:
                signal = f"{n} raises"
        print(f"${s['offering_amount']:>13,}  {n:>3}  {first:<10} {(s['industry'] or '')[:20]:<20} "
              f"{s['entity']}  [{signal}]")


if __name__ == "__main__":
    main()
