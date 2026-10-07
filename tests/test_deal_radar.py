"""Tests for deal_radar.py: Form D parsing, EDGAR pagination and the survivor filter.

No network: every HTTP call is replaced with fixtures or fakes.
"""
import csv
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import deal_radar

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text()


class ParseFormDTests(unittest.TestCase):
    def parse(self, fixture_name, cik="9999901", accession="0009999901-26-000001"):
        with mock.patch.object(deal_radar, "get", return_value=fixture(fixture_name)) as get:
            result = deal_radar.parse_formd(cik, accession)
        return result, get

    def test_requests_primary_doc_with_undashed_accession(self):
        _, get = self.parse("formd_operating.xml")
        get.assert_called_once_with(
            "https://www.sec.gov/Archives/edgar/data/9999901/000999990126000001/primary_doc.xml"
        )

    def test_extracts_issuer_and_offering_fields(self):
        d, _ = self.parse("formd_operating.xml")
        self.assertEqual(d["entity"], "Lanternfish Robotics, Inc.")
        # entityTypeOtherDesc must not be confused with entityType
        self.assertEqual(d["entity_type"], "Corporation")
        self.assertEqual((d["city"], d["state"]), ("Austin", "TX"))
        self.assertEqual(d["jurisdiction"], "DELAWARE")
        self.assertEqual(d["year_inc"], "2022")
        self.assertEqual(d["industry"], "Other Technology")
        self.assertEqual(d["revenue_range"], "Decline to Disclose")
        self.assertEqual(d["date_first_sale"], "2026-05-01")
        self.assertEqual(d["min_investment"], "25000")
        self.assertEqual(d["num_invested"], "12")
        self.assertFalse(d["is_amendment"])
        self.assertFalse(d["is_fund"])

    def test_offering_amounts_are_integers(self):
        d, _ = self.parse("formd_operating.xml")
        self.assertEqual(d["offering_amount"], 5_000_000)
        self.assertEqual(d["amount_sold"], 2_000_000)

    def test_only_securities_flagged_true_are_listed(self):
        d, _ = self.parse("formd_operating.xml")
        self.assertEqual(d["securities"], ["Equity", "OptionToAcquire"])

    def test_related_persons_keep_roles_and_skip_nameless_entries(self):
        d, _ = self.parse("formd_operating.xml")
        self.assertEqual(d["persons"], [
            {"name": "Avery Testwell", "roles": ["Executive Officer", "Director"]},
            {"name": "Morgan Placeholder", "roles": ["Director"]},
        ])

    def test_pooled_fund_amendment_with_indefinite_offering(self):
        d, _ = self.parse("formd_pooled_fund.xml")
        self.assertTrue(d["is_fund"])
        self.assertTrue(d["is_amendment"])
        self.assertEqual(d["entity_type"], "Limited Partnership")
        self.assertIsNone(d["offering_amount"])  # "Indefinite" is not a number
        self.assertEqual(d["amount_sold"], 0)
        self.assertIsNone(d["year_inc"])  # overFiveYears carries no <value>
        self.assertEqual(d["persons"], [])


class HelperTests(unittest.TestCase):
    def test_to_int(self):
        self.assertEqual(deal_radar._to_int("42"), 42)
        self.assertIsNone(deal_radar._to_int(None))
        self.assertIsNone(deal_radar._to_int("Indefinite"))

    def test_val_treats_whitespace_only_as_missing(self):
        self.assertIsNone(deal_radar._val("<city>   </city>", "city"))
        self.assertIsNone(deal_radar._val("<other>x</other>", "city"))
        self.assertEqual(deal_radar._val("<city> Reno </city>", "city"), "Reno")

    def test_vehicle_name_pattern(self):
        flagged = ["Harbor Growth Fund II, LLC", "StartEngine Collectibles Series 7",
                   "Northgate Capital Partners LLC", "Unit 4, a series of Example Holdings",
                   "Example REIT Inc."]
        clean = ["Fundamental Labs, Inc.", "Refund Robotics Corp", "Capital Bikes Inc."]
        for name in flagged:
            self.assertRegex(name, deal_radar.NAME_VEHICLE)
        for name in clean:
            self.assertNotRegex(name, deal_radar.NAME_VEHICLE)


class CollectFilingsTests(unittest.TestCase):
    @staticmethod
    def hit(adsh, cik="0000123456", name="Example Co"):
        return {"_source": {"adsh": adsh, "ciks": [cik], "display_names": [name],
                            "file_date": "2026-06-01", "biz_locations": ["Austin, TX"]}}

    def test_pages_until_empty_and_dedupes_accessions(self):
        pages = {
            0: {"hits": {"hits": [self.hit("A-1"), self.hit("A-2")]}},
            2: {"hits": {"hits": [self.hit("A-2"), self.hit("A-3", cik="0000000007")]}},
            4: {"hits": {"hits": []}},
        }
        calls = []

        def fake_page(frm):
            calls.append(frm)
            return pages[frm]

        with mock.patch.object(deal_radar, "fts_page", side_effect=fake_page), \
                mock.patch.object(deal_radar.time, "sleep"):
            out = deal_radar.collect_filings(10)

        self.assertEqual(calls, [0, 2, 4])
        self.assertEqual([f["accession"] for f in out], ["A-1", "A-2", "A-3"])
        # leading zeros stripped from the CIK
        self.assertEqual(out[2]["cik"], "7")
        self.assertEqual(out[0]["biz_location"], "Austin, TX")

    def test_stops_at_limit(self):
        page = {"hits": {"hits": [self.hit(f"B-{i}") for i in range(5)]}}
        with mock.patch.object(deal_radar, "fts_page", return_value=page) as fts, \
                mock.patch.object(deal_radar.time, "sleep"):
            out = deal_radar.collect_filings(3)
        self.assertEqual(len(out), 3)
        fts.assert_called_once_with(0)

    def test_missing_cik_becomes_blank(self):
        page = {"hits": {"hits": [{"_source": {"adsh": "C-1"}}]}}
        with mock.patch.object(deal_radar, "fts_page", side_effect=[page, {"hits": {"hits": []}}]), \
                mock.patch.object(deal_radar.time, "sleep"):
            out = deal_radar.collect_filings(5)
        self.assertEqual(out[0]["cik"], "")
        self.assertEqual(out[0]["name"], "")


def parsed(**overrides):
    """A parse_formd() result for a filing that passes every filter."""
    d = {
        "entity": "Quietbrook Software, Inc.", "entity_type": "Corporation",
        "state": "CA", "city": "Oakland", "jurisdiction": "DELAWARE", "year_inc": "2021",
        "industry": "Other Technology", "revenue_range": None, "is_amendment": False,
        "date_first_sale": "2026-05-02", "securities": ["Equity"], "min_investment": "0",
        "offering_amount": 3_000_000, "amount_sold": 1_000_000, "num_invested": "4",
        "is_fund": False, "persons": [{"name": "Riley Sample", "roles": ["Executive Officer"]}],
    }
    d.update(overrides)
    return d


class FilterPipelineTests(unittest.TestCase):
    """Runs deal_radar.main() end to end with the network replaced by fakes."""

    def run_main(self, results):
        filings = [{"accession": acc, "cik": str(i + 1), "name": "", "file_date": "2026-06-01",
                    "biz_location": ""} for i, acc in enumerate(results)]

        def fake_parse(cik, accession):
            r = results[accession]
            if isinstance(r, Exception):
                raise r
            return dict(r)

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = io.StringIO()
        with mock.patch.object(deal_radar, "collect_filings", return_value=filings), \
                mock.patch.object(deal_radar, "parse_formd", side_effect=fake_parse), \
                mock.patch.object(deal_radar, "OUTDIR", tmp.name), \
                mock.patch.object(deal_radar.time, "sleep"), redirect_stdout(out):
            deal_radar.main()
        survivors = json.loads(Path(tmp.name, "survivors.json").read_text())
        with open(Path(tmp.name, "survivors.csv"), newline="") as fh:
            rows = list(csv.DictReader(fh))
        return survivors, rows, out.getvalue()

    def test_each_filter_drops_its_case(self):
        survivors, _, log = self.run_main({
            "keep": parsed(),
            "foreign": parsed(state="ONTARIO"),
            "amend": parsed(is_amendment=True),
            "fund-flag": parsed(is_fund=True),
            "investing": parsed(industry="Investing"),
            "reit": parsed(industry="REITS and Finance"),
            "lp": parsed(entity_type="Limited Partnership"),
            "vehicle": parsed(entity="Harbor Growth Fund II, LLC"),
            "small": parsed(offering_amount=999_999),
            "indefinite": parsed(offering_amount=None),
            "broken": ValueError("bad xml"),
        })
        self.assertEqual([s["accession"] for s in survivors], ["keep"])
        for reason, n in [("non_us", 1), ("amendment", 1), ("pooled_fund", 2), ("real_estate", 1),
                          ("limited_partnership", 1), ("vehicle_name", 1), ("below_min", 2),
                          ("parse_error", 1)]:
            self.assertIn(f"dropped ({reason}): {n}\n", log)
        self.assertIn("SURVIVORS: 1", log)

    def test_filters_apply_in_order_so_each_filing_counts_once(self):
        # A foreign amendment of a fund is counted only as non-US.
        _, _, log = self.run_main({"x": parsed(state=None, is_amendment=True, is_fund=True)})
        self.assertIn("dropped (non_us): 1", log)
        self.assertIn("dropped (amendment): 0", log)
        self.assertIn("dropped (pooled_fund): 0", log)

    def test_min_offering_floor_is_inclusive(self):
        survivors, _, _ = self.run_main({"edge": parsed(offering_amount=deal_radar.MIN_OFFERING)})
        self.assertEqual(len(survivors), 1)

    def test_survivors_sorted_by_offering_and_flag_open_rounds(self):
        survivors, rows, _ = self.run_main({
            "mid": parsed(entity="Mid Co", offering_amount=4_000_000, amount_sold=4_000_000),
            "big": parsed(entity="Big Co", offering_amount=9_000_000, amount_sold=None),
            "small": parsed(entity="Small Co", offering_amount=2_000_000, amount_sold=500_000),
        })
        self.assertEqual([s["entity"] for s in survivors], ["Big Co", "Mid Co", "Small Co"])
        self.assertEqual([s["actively_raising"] for s in survivors], [True, False, True])
        self.assertEqual(survivors[0]["cik"], "2")
        self.assertEqual([r["actively_raising"] for r in rows], ["Y", "N", "Y"])

    def test_csv_row_layout(self):
        _, rows, _ = self.run_main({"keep": parsed(securities=["Equity", "Debt"]),
                                    "nobody": parsed(entity="Solo Co", persons=[], offering_amount=1_500_000)})
        self.assertEqual(rows[0]["securities"], "Equity|Debt")
        self.assertEqual(rows[0]["lead_person"], "Riley Sample")
        self.assertEqual(rows[0]["offering_amount"], "3000000")
        self.assertEqual(rows[1]["lead_person"], "")

    def test_industry_distribution_counts_every_parsed_filing(self):
        _, _, log = self.run_main({
            "a": parsed(industry="Biotechnology"),
            "b": parsed(industry="Biotechnology", state="BERLIN"),
            # (kept non-US: a *surviving* filing with no industry crashes the summary print)
            "c": parsed(industry=None, state="BERLIN"),
        })
        self.assertIn("   2  Biotechnology", log)
        self.assertIn("   1  Unknown", log)


if __name__ == "__main__":
    unittest.main()
