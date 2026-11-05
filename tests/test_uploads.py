"""Uji unggahan semua format: deteksi jenis, ekstraksi teks dokumen, penangkapan lampiran, dan pembersihan request."""
import asyncio
import io
import os
import sys
import unittest
import zipfile
from types import SimpleNamespace as NS
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import _stubs  # noqa: E402

_stubs.install()

from library_agent import callbacks, documents  # noqa: E402


def _docx(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f'<w:document><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p>'
                                        '<w:p><w:r><w:t>Langkah 2</w:t></w:r></w:p></w:body></w:document>')
    return buf.getvalue()


def _xlsx() -> bytes:
    import pandas as pd

    buf = io.BytesIO()
    pd.DataFrame({"OUTLET_ID": [1, 2], "SALES": [10, 20]}).to_excel(buf, index=False)
    return buf.getvalue()


def _pdf(text: str) -> bytes:
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 720, text)
    c.showPage()
    c.save()
    return buf.getvalue()


def _pptx(text: str) -> bytes:
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[6])
    s.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1)).text_frame.text = text
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


class SniffExtractTest(unittest.TestCase):
    def test_sniff(self):
        self.assertEqual(documents.sniff(_xlsx(), "", "")[0], "data")              # xlsx tanpa nama/mime
        self.assertEqual(documents.sniff(b"a;b;c\n1;2;3\n4;5;6\n", "", "")[0], "data")
        self.assertEqual(documents.sniff(b"Prompt RFM v1.3: hitung recency", "prompt.txt", "text/plain")[0], "dokumen")
        self.assertEqual(documents.sniff(_docx("x"), "", "")[1], "dokumen.docx")

    def test_extract_formats(self):
        self.assertIn("Prompt Paten RFM", documents.extract(b"Prompt Paten RFM v1.3", "p.txt", "text/plain")["text"])
        self.assertIn("Langkah 2", documents.extract(_docx("Analisa RFM"), "a.docx", "")["text"])
        self.assertIn("Slide 1", documents.extract(_pptx("Ringkasan Q3"), "a.pptx", "")["text"])
        pdf = documents.extract(_pdf("Laporan Battlefield Q3"), "a.pdf", "application/pdf")
        self.assertTrue(pdf["readable"])
        self.assertIn("Battlefield", pdf["text"])
        html = documents.extract(b"<html><style>x{}</style><body><h1>Judul</h1><p>Isi</p></body></html>", "r.html", "")
        self.assertIn("Judul", html["text"])
        self.assertNotIn("x{}", html["text"])
        img = documents.extract(b"\x89PNG....", "g.png", "image/png")
        self.assertEqual((img["jenis"], img["native_mime"]), ("Gambar", "image/png"))
        old = documents.extract(b"\xd0\xcf\x11\xe0", "lama.doc", "application/msword")
        self.assertFalse(old["readable"])
        self.assertIn("Simpan ulang", old["note"])


class FakeBucket:
    def __init__(self):
        self.store = {}

    def bucket(self, _name):
        return self

    def blob(self, path):
        outer = self

        class B:
            content_disposition = None

            def upload_from_string(self, data, content_type=None):
                outer.store[path] = data

            def download_as_text(self):
                v = outer.store[path]
                return v if isinstance(v, str) else v.decode()

            def download_as_bytes(self):
                v = outer.store[path]
                return v.encode() if isinstance(v, str) else v
        return B()


def _ctx(parts, state=None, inv="inv1"):
    return NS(user_content=NS(parts=parts), state=state if state is not None else {}, _invocation_context=None,
              invocation_id=inv)


def _inline(data, name, mime):
    return NS(text=None, file_data=None, inline_data=NS(data=data, mime_type=mime, display_name=name))


class CaptureTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeBucket()
        callbacks._doc_text.cache_clear()
        from library_agent import config

        self.p = mock.patch("library_agent.callbacks.storage_client", return_value=self.fake)
        import dataclasses

        self.b = mock.patch.object(config, "settings", dataclasses.replace(config.settings, bucket="bkt"))
        self.p.start()
        self.b.start()

    def tearDown(self):
        self.p.stop()
        self.b.stop()

    def test_txt_and_xlsx_in_one_message(self):
        ctx = _ctx([NS(text="analisa RFM", file_data=None, inline_data=None),
                    _inline(b"Prompt Paten RFM v1.3: Step 1 intake", "Prompt_RFM_v1.3.txt", "text/plain"),
                    _inline(_xlsx(), "SORetail_SR3.xlsx",
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")])
        self.assertIsNone(asyncio.run(callbacks.capture_uploads(ctx)))
        self.assertEqual(ctx.state["data_files"][0]["filename"], "SORetail_SR3.xlsx")
        self.assertEqual(ctx.state["documents"][0]["jenis"], "Teks")
        self.assertTrue(ctx.state["documents"][0]["readable"])

    def test_xlsx_without_name_or_mime(self):
        ctx = _ctx([_inline(_xlsx(), None, "")])
        asyncio.run(callbacks.capture_uploads(ctx))
        self.assertTrue(ctx.state["data_files"][0]["filename"].endswith(".xlsx"))

    def test_https_file_data_downloaded(self):
        part = NS(text=None, inline_data=None,
                  file_data=NS(file_uri="https://storage.googleapis.com/bkt/up/SORetail.xlsx", mime_type="",
                               display_name="SORetail.xlsx"))
        self.fake.store["up/SORetail.xlsx"] = _xlsx()
        ctx = _ctx([part])
        asyncio.run(callbacks.capture_uploads(ctx))
        self.assertEqual(ctx.state["data_files"][0]["filename"], "SORetail.xlsx")

    def test_artifact_upload(self):
        art = NS(inline_data=NS(data=_xlsx(), mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                display_name="SORetail.xlsx"))

        async def lister():
            return ["SORetail.xlsx"]

        async def loader(name, version=None):
            return art
        ctx = _ctx([NS(text='ini datanya [Uploaded Artifact: "SORetail.xlsx"]', file_data=None, inline_data=None)])
        ctx.list_artifacts, ctx.load_artifact = lister, loader
        asyncio.run(callbacks.capture_uploads(ctx))
        self.assertEqual(ctx.state["data_files"][0]["filename"], "SORetail.xlsx")
        asyncio.run(callbacks.capture_uploads(ctx))                     # giliran berikutnya: tidak dobel
        self.assertEqual(len(ctx.state["data_files"]), 1)

    def test_text_only_passes(self):
        self.assertIsNone(asyncio.run(callbacks.capture_uploads(_ctx([NS(text="halo", file_data=None, inline_data=None)]))))

    def test_sanitize_replaces_attachments(self):
        xlsx, txt = _xlsx(), b"Prompt Paten RFM v1.3: Step 1 intake"
        parts = [NS(text="analisa", file_data=None, inline_data=None), _inline(txt, "p.txt", "text/plain"),
                 _inline(xlsx, "d.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")]
        ctx = _ctx(parts)
        asyncio.run(callbacks.capture_uploads(ctx))
        from google.genai import types

        req = NS(contents=[types.Content(role="user", parts=[types.Part(text="analisa"),
                                                              types.Part(inline_data=types.Blob(data=txt, mime_type="text/plain")),
                                                              types.Part(inline_data=types.Blob(
                                                                  data=xlsx, mime_type="application/vnd.ms-excel"))])])
        callbacks.sanitize_request(ctx, req)
        texts = [p.text for p in req.contents[0].parts]
        self.assertTrue(all(p.inline_data is None for p in req.contents[0].parts))
        self.assertIn("Prompt Paten RFM", texts[1])
        self.assertIn("File data f1", texts[2])
        ctx.invocation_id = "inv2"                                      # giliran berikutnya: dokumen jadi rujukan
        req2 = NS(contents=[types.Content(role="user", parts=[types.Part(inline_data=types.Blob(data=txt, mime_type="text/plain"))])])
        callbacks.sanitize_request(ctx, req2)
        self.assertIn("read_document", req2.contents[0].parts[0].text)


if __name__ == "__main__":
    unittest.main()
