"""Uji analisis berbasis kode: saklar & allowlist, batas langkah, batas biaya, file masuk/keluar, meteran biaya."""
import dataclasses
import io
import json
import os
import sys
import unittest
from types import SimpleNamespace as NS
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import _stubs  # noqa: E402

_stubs.install()

import pandas as pd  # noqa: E402

from library_agent import code_exec, config, prompts, usage  # noqa: E402

ENGINE = "projects/1/locations/asia-southeast2/reasoningEngines/99"
USER = "jason.kusuma@mii.co.id"


class FakeBlob:
    def __init__(self, store, path):
        self.store, self.path, self.generation, self.content_disposition = store, path, None, None

    def reload(self):
        if self.path not in self.store:
            raise FileNotFoundError(self.path)
        self.generation = self.store[self.path][1]

    def download_as_bytes(self, if_generation_match=None):
        if self.path not in self.store:
            raise FileNotFoundError(self.path)
        return self.store[self.path][0]

    def upload_from_string(self, data, content_type=None, if_generation_match=None):
        cur = self.store.get(self.path, (None, 0))[1]
        if if_generation_match is not None and if_generation_match != cur:
            raise RuntimeError("412 Precondition Failed")
        self.store[self.path] = (data.encode() if isinstance(data, str) else data, cur + 1)


class FakeStorage:
    def __init__(self):
        self.store = {}

    def bucket(self, _name):
        return self

    def blob(self, path):
        return FakeBlob(self.store, path)


class FakeSandboxes:
    def __init__(self):
        self.created, self.calls, self.alive, self.reject_content = [], [], set(), False

    def create(self, spec, name, config):
        n = f"{name}/sandboxEnvironments/{len(self.created) + 1}"
        self.created.append((spec, config))
        self.alive.add(n)
        return NS(response=NS(name=n))

    def get(self, name):
        return NS(state="STATE_RUNNING" if name in self.alive else "STATE_STOPPED")

    def delete(self, name):
        self.alive.discard(name)

    def execute_code(self, name, input_data):
        files = input_data.get("files") or []
        if self.reject_content and files and "content" in files[0]:
            raise ValueError("Unknown field 'content' in files")
        self.calls.append(input_data)
        out = [NS(data=json.dumps({"msg_out": "TOTAL VOLUME 19448.89\n", "msg_err": "", "exit_status_int": 0}).encode(),
                  mime_type="application/json", metadata=None),
               NS(data=b"outlet,segment\n1,CHAMPIONS\n", mime_type="text/csv",
                  metadata=NS(attributes={"file_name": b"rfm_segments_2025.csv"}))]
        out += [NS(data=b"x", mime_type="text/csv", metadata=NS(attributes={"file_name": f["name"].encode()}))
                for f in files]                                            # file masukan ikut kembali -> harus disaring
        return NS(outputs=out)


def _xlsx() -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf) as w:
        pd.DataFrame({"Customer Code": [1, 2], "Grand Total": [1.5, 2.0]}).to_excel(w, sheet_name="Sheet1", index=False)
        pd.DataFrame({"x": [1]}).to_excel(w, sheet_name="Master", index=False)
    return buf.getvalue()


class Base(unittest.TestCase):
    runtime = {"code_execution_enabled": True, "code_execution_users": [USER], "code_execution_max_steps": 3,
               "code_execution_daily_budget_usd": 5}

    def setUp(self):
        self.storage, self.sb = FakeStorage(), FakeSandboxes()
        self.storage.store["data/f1_SORetail.xlsx"] = (_xlsx(), 1)
        s = dataclasses.replace(config.settings, bucket="bkt", report_bucket="bkt", code_execution_engine=ENGINE)
        self.patches = [mock.patch.object(code_exec, "settings", s), mock.patch.object(usage, "settings", s),
                        mock.patch("library_agent.clients.storage_client", return_value=self.storage),
                        mock.patch.object(code_exec, "_client", return_value=NS(agent_engines=NS(sandboxes=self.sb))),
                        mock.patch.object(config, "_read_runtime_file", return_value=dict(self.runtime))]
        for p in self.patches:
            p.start()
        config._runtime_cache["loaded_at"] = 0
        usage._BUFFER.update(ops=[], usd=0.0, last_flush=0.0)
        code_exec._FILES_FIELD["value"] = "content"
        self.ctx = NS(user_id=USER, state={"data_files": [{"file_id": "f1", "filename": "SORetail.xlsx",
                                                          "uri": "gs://bkt/data/f1_SORetail.xlsx"}]},
                      _invocation_context=NS(session=NS(id="sess-12345678"), user_id=USER))

    def tearDown(self):
        for p in self.patches:
            p.stop()
        config._runtime_cache["loaded_at"] = 0


class GuardTest(Base):
    def test_disabled_by_default(self):
        with mock.patch.object(config, "_read_runtime_file", return_value={}):
            config._runtime_cache["loaded_at"] = 0
            self.assertEqual(code_exec.run("print(1)", "uji", self.ctx)["status"], "disabled")
        self.assertEqual(self.sb.created, [])

    def test_allowlist(self):
        self.ctx.user_id = "orang.lain@ptpl.co.id"
        res = code_exec.run("print(1)", "uji", self.ctx)
        self.assertEqual(res["status"], "disabled")
        self.assertIn("orang.lain@ptpl.co.id", res["message"])
        self.assertIn("ekspor_excel", res["message"])

    def test_step_limit(self):
        self.ctx.state["temp:code_steps"] = 3
        self.assertEqual(code_exec.run("print(1)", "uji", self.ctx)["status"], "step_limit")
        self.assertEqual(self.sb.calls, [])

    def test_budget_limit(self):
        day = usage.today()
        self.storage.store[f"ge-docs-agent/usage/{day}.json"] = (json.dumps({**usage._empty(day), "total_usd": 5.2}).encode(), 1)
        res = code_exec.run("print(1)", "uji", self.ctx)
        self.assertEqual(res["status"], "budget_limit")
        self.assertEqual(self.sb.created, [])


class RunTest(Base):
    def test_prepare_converts_excel_and_uses_fixed_machine(self):
        res = code_exec.prepare(self.ctx)
        self.assertEqual(res["status"], "ok")
        spec, cfg = self.sb.created[0]
        self.assertEqual(spec["code_execution_environment"]["machine_config"], "MACHINE_CONFIG_VCPU4_RAM4GIB")
        names = sorted(f["name"] for f in self.sb.calls[0]["files"])
        self.assertEqual(names, ["f1_SORetail__Master.csv", "f1_SORetail__Sheet1.csv"])
        self.assertIn(b"Customer Code", next(f["content"] for f in self.sb.calls[0]["files"] if "Sheet1" in f["name"]))

    def test_run_saves_outputs_and_script(self):
        code_exec.prepare(self.ctx)
        res = code_exec.run("df.to_csv('rfm_segments_2025.csv')", "Simpan segmen", self.ctx)
        self.assertEqual(res["status"], "ok")
        self.assertEqual([f["file"] for f in res["file_output"]], ["rfm_segments_2025.csv"])   # file masukan disaring
        self.assertTrue(res["script_langkah_ini"].endswith("langkah_01.py"))
        self.assertIn("19448.89", self.ctx.state["temp:code_outputs"][-1])
        self.assertEqual(self.sb.calls[-1].get("files"), None)                                  # file tidak dikirim ulang
        self.assertEqual(res["sisa_langkah"], 2)
        self.assertTrue(any(p.endswith("rfm_segments_2025.csv") for p in self.storage.store))

    def test_contents_fallback(self):
        self.sb.reject_content = True
        res = code_exec.prepare(self.ctx)
        self.assertEqual(res["status"], "ok")
        self.assertIn("contents", self.sb.calls[0]["files"][0])

    def test_expired_sandbox_is_recreated_with_files(self):
        code_exec.prepare(self.ctx)
        self.sb.alive.clear()
        code_exec.run("print(1)", "uji", self.ctx)
        self.assertEqual(len(self.sb.created), 2)
        self.assertTrue(self.sb.calls[-1].get("files"))

    def test_sandbox_cost_recorded(self):
        code_exec.prepare(self.ctx)
        usage.flush()
        day = json.loads(self.storage.store[f"ge-docs-agent/usage/{usage.today()}.json"][0])
        self.assertEqual(day["sandbox"]["executions"], 1)
        self.assertIn(USER, day["by_user"])


class MeterTest(Base):
    def test_model_cost_pro_with_cache(self):
        _, usd = usage.model_cost("file_agent", 100_000, 50_000, 10_000)
        self.assertAlmostEqual(usd, (50_000 * 4 + 50_000 * 0.2 + 10_000 * 20) / 1e6)

    def test_record_and_flush(self):
        resp = NS(usage_metadata=NS(prompt_token_count=20_000, cached_content_token_count=0, candidates_token_count=1000,
                                    thoughts_token_count=500))
        usage.record_model_usage(NS(agent_name="file_agent", user_id=USER, _invocation_context=None), resp)
        usage.flush()
        day = json.loads(self.storage.store[f"ge-docs-agent/usage/{usage.today()}.json"][0])
        self.assertEqual((day["model"]["calls"], day["model"]["input"], day["model"]["output"]), (1, 20000, 1500))
        self.assertAlmostEqual(day["total_usd"], (20_000 * 4 + 1_500 * 20) / 1e6, places=6)

    def test_chain_keeps_verifier_result(self):
        chained = usage.chain(lambda c, r: None, lambda c, r: "ganti")
        self.assertEqual(chained(None, None), "ganti")


class PromptTest(Base):
    def test_code_mode_only_for_allowed_user(self):
        self.assertIn("MODE ANALIS", prompts.code_mode_note(self.ctx))
        self.assertEqual(prompts.code_mode_note(NS(user_id="lain@x.com", _invocation_context=None)), "")


if __name__ == "__main__":
    unittest.main()


class GenericFileFixTest(unittest.TestCase):
    """Regresi dari file RFM nyata: tanggal tetap tanggal pada max/min; baris Grand Total tidak ikut terhitung."""

    def setUp(self):
        from library_agent import data_engine as de

        self.de = de
        self.df = pd.DataFrame({"date (Year)": ["2025", "2025", "2026", "Grand Total"],
                                "date": pd.to_datetime(["2025-01-31", "2025-02-28", "2026-09-30", None]),
                                "Customer Code": [1.0, 1.0, 2.0, None],
                                "PERTAMINA BRAKE FLUID SERIES": [0.1, None, 0.2, 0.3],
                                "Grand Total": [1.5, 2.0, 0.7, 4.2]})

    def test_total_row_excluded(self):
        prep, notes = self.de.prepare(self.df, "lainnya")
        self.assertEqual(notes["rows_used"], 3)
        res = self.de.run_plan({"f": prep}, {"file": "f", "metrics": [{"column": "Grand Total", "agg": "sum", "name": "V"}]})
        self.assertAlmostEqual(res["rows"][0][0], 4.2)

    def test_blank_key_non_total_kept(self):
        df = pd.DataFrame({"Outlet ID": ["A", "B", None], "Sales": [1.0, 2.0, 9.0]})
        self.assertEqual(self.de.total_rows(df).tolist(), [False, False, False])

    def test_date_max_stays_date(self):
        prep, _ = self.de.prepare(self.df, "lainnya")
        res = self.de.run_plan({"f": prep}, {"file": "f", "group_by": ["Customer Code"],
                                             "metrics": [{"column": "date", "agg": "max", "name": "LAST"}]})
        self.assertIn("2025-02-28", str(res["rows"][0][1]))


class BatchTest(Base):
    def test_many_files_sent_in_batches(self):
        with mock.patch.object(code_exec, "BATCH_BYTES", 5000):
            files = [{"name": f"f{i}.csv", "file_id": f"f{i}", "content": b"x" * 3000} for i in range(7)]
            client = NS(agent_engines=NS(sandboxes=self.sb))
            code_exec._execute_batched(client, "sb", "print(1)", files)
        self.assertEqual(len(self.sb.calls), 7)                         # 3.000 B per file, batas 5.000 B -> 1 file/batch
        self.assertEqual(self.sb.calls[-1]["code"], "print(1)")
        self.assertEqual(sum(len(c.get("files") or []) for c in self.sb.calls), 7)

    def test_single_file_too_large(self):
        with mock.patch.object(code_exec, "BATCH_BYTES", 10):
            self.assertEqual(code_exec.prepare(self.ctx)["status"], "file_too_large")
