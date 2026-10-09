"""Uji analisis file CSV/Excel, pengetahuan Data Agent, dan pengecekan angka."""
import io
import os
import sys
import unittest
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import _stubs  # noqa: E402

_stubs.install()

import pandas as pd  # noqa: E402

from library_agent import data_engine as de  # noqa: E402

FIX = os.path.join(ROOT, "tests", "fixtures")
HEROES = ["PERTAMINA ENDURO MATIC-S 0.8 LITER"]


def retail_frame():
    base = {"SURVEY_ID": "1", "AVAILABILITY": "1", "OUTLIER_HTO": "DATA USE", "OUTLIER_HET": "DATA USE",
            "SEGMENT": "MCO", "VISCOSITY": "10W-30", "KIMAP": "K1", "DT_PR": "2026-07-31", "HET": 0, "HTO": 0,
            "MARGIN_SURVEY": 0, "TRADE_PROMO": 0, "LOYALTY": 0}
    rows = [
        dict(base, OUTLET_ID="O1", SALES_REGION_CUSTOMER="3", BRAND="PERTAMINA", QNR="PERTAMINA ENDURO MATIC-S 0.8 LITER",
             CONTENT=0.8, HARGA_JUAL=60000, HARGA_TEBUS=52000),
        dict(base, OUTLET_ID="O2", SALES_REGION_CUSTOMER="4", BRAND="AHM", QNR="AHM MPX2 0.8 LITER",
             CONTENT=0.8, HARGA_JUAL=68000, HARGA_TEBUS=60000),
        dict(base, OUTLET_ID="O3", SALES_REGION_CUSTOMER="2", BRAND="SHELL", QNR="SHELL AX7 0.8 LITER",
             CONTENT=0.8, HARGA_JUAL=72000, HARGA_TEBUS=63000),
        dict(base, OUTLET_ID="O4", SALES_REGION_CUSTOMER="2", BRAND="PERTAMINA", QNR="PERTAMINA ENDURO MATIC-S 0.8 LITER",
             CONTENT=0.8, HARGA_JUAL=62000, HARGA_TEBUS=53000),
        dict(base, OUTLET_ID="O5", SALES_REGION_CUSTOMER="2", BRAND="SHELL", QNR="SHELL AX7 0.8 LITER",
             CONTENT=0.8, HARGA_JUAL=70000, HARGA_TEBUS=61000, AVAILABILITY="0"),
    ]
    return pd.DataFrame(rows)


class RealCsvTest(unittest.TestCase):
    def test_detect_and_filters_on_real_samples(self):
        r = pd.read_csv(os.path.join(FIX, "Data_Retail.csv"))
        i = pd.read_csv(os.path.join(FIX, "Data_Industry.csv"))
        self.assertEqual(de.detect_kind(r), "retail")
        self.assertEqual(de.detect_kind(i), "industri")
        pr, nr = de.prepare(r, "retail", HEROES)
        self.assertEqual(nr["rows_used"], 0)
        self.assertEqual(nr["excluded"]["AVAILABILITY bukan 1"], 10)
        pi, ni = de.prepare(i, "industri")
        self.assertEqual(ni["rows_used"], 0)
        self.assertEqual(ni["excluded"]["data_status bukan OK"], 10)

    def test_read_bytes_csv_semicolon_and_excel(self):
        df, _ = de.read_bytes(b"a;b\n1;2\n3;4\n", "x.csv")
        self.assertEqual(list(df.columns), ["a", "b"])
        buf = io.BytesIO()
        retail_frame().to_excel(buf, index=False)
        df2, sheets = de.read_bytes(buf.getvalue(), "data.xlsx")
        self.assertEqual(len(df2), 5)
        self.assertEqual(sheets, ["Sheet1"])


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.df, self.notes = de.prepare(retail_frame(), "retail", HEROES)

    def test_rules_applied(self):
        self.assertEqual(self.notes["excluded"], {"AVAILABILITY bukan 1": 1})
        self.assertAlmostEqual(self.df["HJ_L"].iloc[0], 75000.0)
        self.assertEqual(list(self.df["ZONA"]), ["Zona 1", "Zona 1", "Zona 2", "Zona 2"])

    def test_gap_kimap_preset(self):
        res = de.run_plan({"f1": self.df}, {"file": "f1", "preset": "gap_kimap",
                                            "preset_args": {"metrics": ["HJ_L"], "group_by": ["ZONA"]}})
        rows = {r[0]: dict(zip(res["columns"], r)) for r in res["rows"]}
        self.assertAlmostEqual(rows["Zona 1"]["GAP_HJ_L"], 75000 - 85000)      # PTPL lebih murah -> negatif
        self.assertAlmostEqual(rows["Zona 2"]["GAP_HJ_L"], 77500 - 90000)

    def test_groupby_filter_sort(self):
        res = de.run_plan({"f1": self.df}, {"file": "f1", "filters": [{"column": "brand", "op": "in", "value": ["SHELL", "AHM"]}],
                                            "group_by": ["BRAND"], "metrics": [{"column": "HJ_L", "agg": "mean", "name": "rata_hj"}],
                                            "sort": [{"column": "rata_hj", "desc": True}]})
        self.assertEqual([r[0] for r in res["rows"]], ["SHELL", "AHM"])
        self.assertEqual(res["rows_after_filter"], 2)

    def test_pivot_and_derive(self):
        res = de.run_plan({"f1": self.df}, {"file": "f1", "derive": [{"name": "SELISIH", "expr": "HJ_L - HT_L"}],
                                            "pivot": {"index": ["ZONA"], "columns": "BRAND", "values": "SELISIH", "agg": "mean"}})
        self.assertIn("PERTAMINA", res["columns"])

    def test_invalid_plan_messages(self):
        with self.assertRaises(de.PlanError):
            de.run_plan({"f1": self.df}, {"file": "f1", "group_by": ["TIDAK_ADA"], "metrics": [{"column": "HJ_L"}]})
        with self.assertRaises(de.PlanError):
            de.run_plan({"f1": self.df}, {"file": "f1", "derive": [{"name": "x", "expr": "__import__('os')"}]})

    def test_join_keys(self):
        other = pd.DataFrame({"cus_id": ["O1", "O2", "O9"], "facing": [3, 1, 2]})
        cand = de.find_join_keys(self.df, other)
        self.assertEqual((cand[0]["kolom_file_a"], cand[0]["kolom_file_b"]), ("OUTLET_ID", "cus_id"))
        res = de.run_plan({"a": self.df, "b": other}, {"file": "a", "join": {"file": "b", "left_on": ["OUTLET_ID"],
                                                                            "right_on": ["cus_id"]}, "columns": ["OUTLET_ID", "facing"]})
        self.assertEqual(res["rows_total"], 2)


class ReportFromFileTest(unittest.TestCase):
    def test_retail_rows_build_dataset(self):
        from library_agent import price_data as pdm

        df, _ = de.prepare(retail_frame(), "retail", HEROES)
        agg, monthly = de.retail_report_rows(df, pdm.parse_period("2026-07"), None, HEROES)
        ds = pdm.build_dataset(agg, monthly, HEROES, pdm.parse_period("2026-07"), None)
        self.assertTrue(ds["has_data"])
        hero = ds["zones"]["Nasional"]["heroes"][0]["a"]
        self.assertAlmostEqual(hero["GAP_HJ"], 76250 - (85000 + 90000) / 2)

    def test_industry_rows_build_dataset(self):
        from library_agent import industry_data as idm

        raw = pd.DataFrame([{"dt_pr": "2026-09-30", "data_status": "OK", "htd_ptpl": 40600, "htd_ptpl_plus": 43848.0,
                             "harga_kompetitor_per_liter": 48232.8, "produk_kompetitor": "Shell Omala S2 GX 320",
                             "main_stage": "EARLY", "channel": "Mining", "produk_ptpl": "Masri RG 320", "brand": "SHELL",
                             "sales_region_customer": 7}])
        df, _ = de.prepare(raw, "industri")
        self.assertAlmostEqual(df["GAP_PCT"].iloc[0], 10.0)
        rows = de.industry_report_rows(df, idm.month_period("2026-09"), None, "htd_ptpl_plus", "channel")
        ds = idm.build_dataset(rows, idm.DEFAULT_FOCUS, ["SHELL"], idm.month_period("2026-09"), None)
        self.assertAlmostEqual(ds["stages"]["EARLY"]["table1"]["Masri RG 320"]["Zona 3"]["current"], 10.0)


class KnowledgeCardTest(unittest.TestCase):
    def test_parse_agent_card_format(self):
        from library_agent import knowledge

        card = {"name": "Industry Marketing Intelligence", "capabilities": {"extensions": [{"params": {
            "system_instructions": "ROLE industri", "glossary_terms": ["Channel: segmen industri"],
            "example_queries": {"Jumlah sample valid?": ["select 1"], "Data SHELL Agro?": ["select 2"]},
            "table_info": ["ptpl-curated-prd.DATAMART.survey_industry"]}}]}}
        k = knowledge.parse_definition(card)
        self.assertEqual(k["instruction"], "ROLE industri")
        self.assertEqual([e["sql"] for e in k["examples"]], ["select 1", "select 2"])
        self.assertEqual(k["glossary"], ["Channel: segmen industri"])
        self.assertEqual(k["tables"], ["ptpl-curated-prd.DATAMART.survey_industry"])


class KnowledgeContextOrderTest(unittest.TestCase):
    def test_empty_published_falls_back_to_last_published(self):
        from library_agent import knowledge

        raw = {"data_analytics_agent": {"published_context": {"datasource_references": {}},
                                        "last_published_context": {"system_instruction": "ROLE retail"},
                                        "staging_context": {"system_instruction": "draft"}}}
        self.assertEqual(knowledge.parse_definition(raw)["instruction"], "ROLE retail")

    def test_camel_case_keys(self):
        from library_agent import knowledge

        raw = {"dataAnalyticsAgent": {"publishedContext": {"systemInstruction": "ROLE",
                                                            "exampleQueries": [{"naturalLanguageQuestion": "Q",
                                                                                "sqlQuery": "SELECT 1"}]}}}
        k = knowledge.parse_definition(raw)
        self.assertEqual((k["instruction"], k["examples"][0]["sql"]), ("ROLE", "SELECT 1"))


class KnowledgeTest(unittest.TestCase):
    def test_parse_definition(self):
        from library_agent import knowledge

        raw = {"name": "x", "data_analytics_agent": {"published_context": {
            "system_instruction": "ROLE retail", "example_queries": [{"natural_language_question": "Q1", "sql_query": "SELECT 1"}],
            "glossary_terms": [{"display_name": "HTD", "description": "Harga Tebus Distributor"}],
            "datasource_references": {"bq": {"table_references": [{"table_id": "SURVEY_PRODUCTS"}]}}}}}
        k = knowledge.parse_definition(raw)
        self.assertEqual(k["instruction"], "ROLE retail")
        self.assertEqual(k["examples"][0]["sql"], "SELECT 1")
        self.assertEqual(k["glossary"], ["HTD: Harga Tebus Distributor"])


def _ctx(tool_text, user_text="pertanyaan"):
    from google.genai import types

    fr = SimpleNamespace(name="analyze_data", response={"rows": [["Zona 1", -10000.0]], "answer": tool_text})
    ev = SimpleNamespace(author="file_agent", content=SimpleNamespace(parts=[SimpleNamespace(function_response=fr, text=None)]))
    inv = SimpleNamespace(invocation_id="inv1", session=SimpleNamespace(events=[ev]))
    return SimpleNamespace(state={}, _invocation_context=inv,
                           user_content=types.Content(role="user", parts=[types.Part(text=user_text)]))


class VerifyNumbersTest(unittest.TestCase):
    def _resp(self, text):
        from google.genai import types

        return SimpleNamespace(content=types.Content(role="model", parts=[types.Part(text=text)]))

    def test_grounded_answer_passes(self):
        from library_agent.callbacks import verify_numbers

        self.assertIsNone(verify_numbers(_ctx("gap Rp 57.202/L"), self._resp("Gap Zona 1 −Rp 10.000/L dan Rp 57.202/L.")))

    def test_ungrounded_answer_retry_then_note(self):
        from library_agent.callbacks import verify_numbers

        ctx = _ctx("gap Rp 57.202/L")
        first = verify_numbers(ctx, self._resp("Gap Zona 2 −Rp 12.345/L."))
        self.assertEqual(first.content.parts[0].function_call.name, "periksa_angka")
        second = verify_numbers(ctx, self._resp("Gap Zona 2 −Rp 12.345/L."))
        self.assertIn("tidak dapat diverifikasi", second.content.parts[0].text)


class UploadRoutingTest(unittest.TestCase):
    def test_data_file_detection(self):
        from library_agent.callbacks import _is_data_file

        self.assertTrue(_is_data_file("Data_Retail.csv", "text/plain"))
        self.assertTrue(_is_data_file("x", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
        self.assertFalse(_is_data_file("studi.pdf", "application/pdf"))


if __name__ == "__main__":
    unittest.main()


class TableDisplayTest(unittest.TestCase):
    def test_eighteen_rows_shown_in_full(self):
        from library_agent.data_agent import table_to_markdown

        rows = [[f"P{i}", "Zona 1", i] for i in range(18)]
        md = table_to_markdown({"columns": ["QNR", "ZONE", "HJ"], "rows": rows, "total_rows": 18})
        self.assertIn("P17", md)
        self.assertNotIn("menampilkan", md)
