"""Tests for the follow-on scripts: filing history, Blitz and FullEnrich candidate building.

All HTTP calls are faked; scripts that read ./output/ are run inside a temporary directory.
"""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import blitz_enrich
import enrich_history
import fullenrich_enrich


class InTempDir(unittest.TestCase):
    """Runs each test from an empty temporary working directory with an output/ folder."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        old = os.getcwd()
        os.chdir(tmp.name)
        self.addCleanup(os.chdir, old)
        os.makedirs("output")

    @staticmethod
    def write_json(path, data):
        Path(path).write_text(json.dumps(data))


class FilingHistoryTests(unittest.TestCase):
    def test_counts_only_form_d_and_amendments_in_date_order(self):
        submissions = {"name": "QUIETBROOK SOFTWARE INC", "filings": {"recent": {
            "form": ["D", "8-K", "D/A", "D", "S-1"],
            "filingDate": ["2024-03-01", "2024-04-01", "2019-07-15", "2026-05-20", "2025-01-01"],
        }}}
        with mock.patch.object(enrich_history, "get", return_value=json.dumps(submissions)) as get:
            h = enrich_history.filing_history("42")
        get.assert_called_once_with("https://data.sec.gov/submissions/CIK0000000042.json")
        self.assertEqual(h["all_form_d_dates"], ["2019-07-15", "2024-03-01", "2026-05-20"])
        self.assertEqual(h["num_form_d"], 3)
        self.assertEqual((h["first_form_d"], h["latest_form_d"]), ("2019-07-15", "2026-05-20"))
        self.assertEqual(h["company_name"], "QUIETBROOK SOFTWARE INC")

    def test_company_with_no_form_d(self):
        submissions = {"name": "X", "filings": {"recent": {"form": ["10-K"], "filingDate": ["2025-01-01"]}}}
        with mock.patch.object(enrich_history, "get", return_value=json.dumps(submissions)):
            h = enrich_history.filing_history("1")
        self.assertEqual(h["num_form_d"], 0)
        self.assertIsNone(h["first_form_d"])
        self.assertIsNone(h["latest_form_d"])


class LifecycleSignalTests(InTempDir):
    def test_signals_and_errors_are_recorded(self):
        self.write_json("output/survivors.json", [
            {"entity": "First Timer Inc", "cik": "1", "offering_amount": 2_000_000, "industry": "Biotechnology"},
            {"entity": "Veteran Co", "cik": "2", "offering_amount": 3_000_000, "industry": "Other"},
            {"entity": "Climber Co", "cik": "3", "offering_amount": 4_000_000, "industry": "Other"},
            {"entity": "Broken Co", "cik": "4", "offering_amount": 5_000_000, "industry": None},
        ])
        histories = {
            "1": {"num_form_d": 1, "first_form_d": "2026-05-01"},
            "2": {"num_form_d": 4, "first_form_d": "2018-02-01"},
            "3": {"num_form_d": 3, "first_form_d": "2022-09-09"},
        }

        def fake_history(cik):
            if cik == "4":
                raise RuntimeError("HTTP 404")
            return histories[cik]

        out = io.StringIO()
        with mock.patch.object(enrich_history, "filing_history", side_effect=fake_history), \
                mock.patch.object(enrich_history.time, "sleep"), redirect_stdout(out):
            enrich_history.main()

        log = out.getvalue()
        self.assertIn("First Timer Inc  [first raise]", log)
        self.assertIn("Veteran Co  [serial since 2018 (aging?)]", log)
        self.assertIn("Climber Co  [3 raises]", log)
        saved = json.loads(Path("output/survivors_enriched.json").read_text())
        self.assertEqual(saved[3]["history"], {"error": "HTTP 404"})
        self.assertEqual(saved[1]["history"]["num_form_d"], 4)


class BlitzKeyTests(InTempDir):
    def test_environment_wins_over_dotenv(self):
        Path(".env").write_text("BLITZ_API_KEY=from-file\n")
        with mock.patch.dict(os.environ, {"BLITZ_API_KEY": "from-env"}):
            self.assertEqual(blitz_enrich.key(), "from-env")

    def test_reads_quoted_value_from_dotenv(self):
        Path(".env").write_text('OTHER=1\n  BLITZ_API_KEY="test-key-123"\n')
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(blitz_enrich.key(), "test-key-123")

    def test_missing_everywhere(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(blitz_enrich.key())


class BlitzParsingTests(unittest.TestCase):
    LI = "https://www.linkedin.com/company/example-co"

    def setUp(self):
        blitz_enrich.credits["n"] = 0

    def test_find_people_prefers_current_title_at_this_company(self):
        response = {"results": [
            {"person": {"full_name": "Riley Sample", "headline": "Builder of things",
                        "linkedin_url": "https://www.linkedin.com/in/riley-sample",
                        "experiences": [
                            {"job_is_current": False, "company_linkedin_url": self.LI, "job_title": "Intern"},
                            {"job_is_current": True, "company_linkedin_url": "https://www.linkedin.com/company/other",
                             "job_title": "Board Member"},
                            {"job_is_current": True, "company_linkedin_url": self.LI, "job_title": "CEO"},
                        ]}},
            {"person": {"first_name": "Casey", "last_name": "Example", "headline": "CFO at Example Co",
                        "linkedin_url": None, "experiences": None}},
        ]}
        with mock.patch.object(blitz_enrich, "post", return_value=response) as post:
            people = blitz_enrich.find_people(self.LI)
        url, payload = post.call_args.args
        self.assertTrue(url.endswith("/v2/search/waterfall-icp-keyword"))
        self.assertEqual(payload["company_linkedin_url"], self.LI)
        self.assertEqual(people, [
            {"name": "Riley Sample", "title": "CEO", "linkedin": "https://www.linkedin.com/in/riley-sample"},
            {"name": "Casey Example", "title": "CFO at Example Co", "linkedin": None},
        ])
        self.assertEqual(blitz_enrich.credits["n"], 2)

    def test_find_people_tolerates_failed_request(self):
        with mock.patch.object(blitz_enrich, "post", return_value=None):
            self.assertEqual(blitz_enrich.find_people(self.LI), [])

    def test_enrich_email_falls_back_to_all_emails(self):
        with mock.patch.object(blitz_enrich, "post", return_value={"email": "riley@example.com"}):
            self.assertEqual(blitz_enrich.enrich_email("li"), "riley@example.com")
        with mock.patch.object(blitz_enrich, "post",
                               return_value={"email": None, "all_emails": [{"email_address": "c@example.org"}]}):
            self.assertEqual(blitz_enrich.enrich_email("li"), "c@example.org")
        with mock.patch.object(blitz_enrich, "post", return_value=None):
            self.assertEqual(blitz_enrich.enrich_email("li"), "")
        self.assertEqual(blitz_enrich.credits["n"], 3)


class BlitzMainTests(InTempDir):
    DISCOVERED = {
        "Cached Co": {"domain": "cached.example", "linkedin": "https://www.linkedin.com/company/cached"},
        "Fresh Co": {"domain": "fresh.example", "linkedin": "https://www.linkedin.com/company/fresh"},
        "Stealth Co": {"domain": "stealth.example", "linkedin": ""},
    }

    def test_reuses_cache_skips_vehicles_and_handles_missing_linkedin(self):
        base = {"city": "Reno", "state": "NV"}
        self.write_json("output/survivors_enriched.json", [
            dict(base, entity="Cached Co"), dict(base, entity="Fresh Co"),
            dict(base, entity="Stealth Co"), dict(base, entity="Shell Holdings LLC"),
        ])
        self.write_json("output/blitz_enriched.json", [{
            "entity": "Cached Co", "linkedin_url": "https://www.linkedin.com/company/cached",
            "domain": "old.example", "contacts": [{"name": "Old Contact", "email": "old@cached.example"}],
        }])
        calls = []

        def fake_post(url, payload):
            calls.append(url)
            if url.endswith("waterfall-icp-keyword"):
                return {"results": [{"person": {"full_name": "Jordan Fake",
                                                "linkedin_url": "https://www.linkedin.com/in/jordan-fake"}}]}
            return {"email": "jordan@fresh.example"}

        with mock.patch.dict(blitz_enrich.DISCOVERED, self.DISCOVERED, clear=True), \
                mock.patch.object(blitz_enrich, "SKIP", {"Shell Holdings LLC"}), \
                mock.patch.dict(os.environ, {"BLITZ_API_KEY": "test-key"}), \
                mock.patch.object(blitz_enrich, "post", side_effect=fake_post), \
                mock.patch.object(blitz_enrich.time, "sleep"), redirect_stdout(io.StringIO()):
            blitz_enrich.main()

        # Only the uncached company with a LinkedIn page cost any API calls.
        self.assertEqual(len(calls), 2)
        out = {r["entity"]: r for r in json.loads(Path("output/blitz_enriched.json").read_text())}
        self.assertEqual(set(out), {"Cached Co", "Fresh Co", "Stealth Co"})
        self.assertEqual(out["Cached Co"]["contacts"][0]["name"], "Old Contact")
        self.assertEqual(out["Cached Co"]["domain"], "cached.example")  # refreshed from DISCOVERED
        self.assertEqual(out["Fresh Co"]["contacts"][0]["email"], "jordan@fresh.example")
        self.assertEqual(out["Stealth Co"]["contacts"], [])
        self.assertIn("stealth", out["Stealth Co"]["blitz"])
        csv_lines = Path("output/blitz_contacts.csv").read_text().splitlines()
        self.assertEqual(len(csv_lines), 3)  # header + one contact for each of two companies

    def test_refuses_to_run_without_key(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SystemExit):
                blitz_enrich.main()


class SplitNameTests(unittest.TestCase):
    def test_strips_suffixes_and_punctuation(self):
        self.assertEqual(fullenrich_enrich.split_name("Avery Q. Testwell, Jr."), ("Avery", "Testwell"))
        self.assertEqual(fullenrich_enrich.split_name("Morgan Lee Placeholder MD PhD"), ("Morgan", "Placeholder"))

    def test_needs_two_parts(self):
        self.assertIsNone(fullenrich_enrich.split_name("Cher"))
        self.assertIsNone(fullenrich_enrich.split_name("Prince, Jr."))
        self.assertIsNone(fullenrich_enrich.split_name(None))


class BuildCandidatesTests(InTempDir):
    def test_targets_only_companies_with_a_domain_and_no_email(self):
        persons = [
            {"name": "Dana Director", "roles": ["Director"]},
            {"name": "Erin Exec", "roles": ["Executive Officer"]},
            {"name": "Riley Sample", "roles": ["Executive Officer"]},  # same surname as the Blitz person
            {"name": "Frankie Promoter", "roles": ["Promoter"]},
            {"name": "Gale Fourth", "roles": ["Director"]},
        ]
        self.write_json("output/survivors_enriched.json", [
            {"entity": "Gap Co", "persons": persons},
            {"entity": "Covered Co", "persons": persons},
            {"entity": "Nodomain Co", "persons": persons},
        ])
        self.write_json("output/blitz_enriched.json", [
            {"entity": "Gap Co", "domain": "gap.example",
             "contacts": [{"name": "Riley Sample", "linkedin": "https://www.linkedin.com/in/riley", "email": ""}]},
            {"entity": "Covered Co", "domain": "covered.example",
             "contacts": [{"name": "Has Email", "email": "has@covered.example"}]},
            {"entity": "Nodomain Co", "domain": "", "contacts": []},
        ])
        cands = fullenrich_enrich.build_candidates()

        self.assertEqual({c["company_name"] for c in cands}, {"Gap Co"})
        # Blitz person first, then executives before directors, capped at three contacts.
        self.assertEqual([(c["firstname"], c["lastname"]) for c in cands],
                         [("Riley", "Sample"), ("Erin", "Exec"), ("Dana", "Director")])
        self.assertEqual(cands[0]["linkedin_url"], "https://www.linkedin.com/in/riley")
        self.assertTrue(all(c["domain"] == "gap.example" for c in cands))


class FullEnrichKeyTests(InTempDir):
    def test_blank_dotenv_value_is_treated_as_missing(self):
        Path(".env").write_text("FULLENRICH_API_KEY=\n")
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(fullenrich_enrich.load_key())

    def test_without_key_lists_targets_and_never_calls_the_api(self):
        self.write_json("output/survivors_enriched.json",
                        [{"entity": "Gap Co", "persons": [{"name": "Erin Exec", "roles": ["Executive Officer"]}]}])
        self.write_json("output/blitz_enriched.json", [{"entity": "Gap Co", "domain": "gap.example", "contacts": []}])
        out = io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(fullenrich_enrich, "post") as post, redirect_stdout(out):
            fullenrich_enrich.main()
        post.assert_not_called()
        self.assertIn("1 companies, 1 contacts", out.getvalue())
        self.assertIn("FULLENRICH_API_KEY not set", out.getvalue())


if __name__ == "__main__":
    unittest.main()
