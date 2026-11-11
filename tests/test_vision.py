"""Uji kemampuan melihat gambar: konversi, lampiran otomatis ke model, lihat_gambar, gambar referensi laporan."""
import io
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

from PIL import Image  # noqa: E402
from google.genai import types  # noqa: E402

from library_agent import callbacks, custom_report as cr, vision  # noqa: E402


def png(w=3000, h=2000, mode="RGBA"):
    buf = io.BytesIO()
    Image.new(mode, (w, h), (10, 30, 60, 255) if mode == "RGBA" else (10, 30, 60)).save(buf, format="PNG")
    return buf.getvalue()


STORE = {"img/wa.jpg": png(), "img/legend.png": png(400, 200)}
STORAGE = NS(bucket=lambda b: NS(blob=lambda p: NS(download_as_bytes=lambda: STORE[p])))
DOCS = [{"doc_id": "d1", "filename": "WhatsApp Image.jpeg", "jenis": "Gambar", "native_mime": "image/jpeg",
         "uri": "gs://b/img/wa.jpg", "invocation_id": "inv-now"},
        {"doc_id": "d2", "filename": "legend.png", "jenis": "Gambar", "native_mime": "image/png",
         "uri": "gs://b/img/legend.png", "invocation_id": "inv-old"},
        {"doc_id": "d3", "filename": "catatan.txt", "jenis": "Teks", "uri": "gs://b/x.txt", "invocation_id": "inv-now"}]


class VisionTest(unittest.TestCase):
    def setUp(self):
        vision._load.cache_clear()
        self.p = mock.patch("library_agent.clients.storage_client", return_value=STORAGE)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_load_resizes_to_jpeg(self):
        data, mime = vision.load(DOCS[0])
        self.assertEqual(mime, "image/jpeg")
        self.assertLessEqual(max(Image.open(io.BytesIO(data)).size), vision.MAX_SIDE)

    def test_fresh_images_attached_to_request(self):
        ctx = NS(state={"documents": DOCS}, invocation_id="inv-now")
        req = NS(contents=[types.Content(role="user", parts=[types.Part(text="buat laporan seperti gambar ini")])])
        callbacks.sanitize_request(ctx, req)
        parts = req.contents[-1].parts
        self.assertIn("d1 (WhatsApp Image.jpeg)", parts[1].text)
        blobs = [p.inline_data for p in parts if getattr(p, "inline_data", None)]
        self.assertEqual(len(blobs), 1)                                       # hanya gambar giliran ini
        self.assertEqual(blobs[0].mime_type, "image/jpeg")

    def test_requested_old_image(self):
        from library_agent.tools import doc_tools

        ctx = NS(state={"documents": DOCS}, invocation_id="inv-later")
        self.assertEqual(doc_tools.lihat_gambar(["d2"], ctx)["status"], "ok")
        req = NS(contents=[types.Content(role="user", parts=[types.Part(function_response=NS(name="lihat_gambar"))])])
        callbacks.sanitize_request(ctx, req)
        self.assertEqual(req.contents[-1].role, "user")
        self.assertTrue(any(getattr(p, "inline_data", None) for p in req.contents[-1].parts))
        self.assertEqual(doc_tools.lihat_gambar(["d3"], ctx)["status"], "error")    # bukan gambar

    def test_no_images_no_change(self):
        ctx = NS(state={"documents": DOCS[1:]}, invocation_id="inv-now")
        req = NS(contents=[types.Content(role="user", parts=[types.Part(text="halo")])])
        callbacks.sanitize_request(ctx, req)
        self.assertEqual(len(req.contents[0].parts), 1)

    def test_report_writer_gets_images(self):
        from library_agent.tools import report_tools as rt

        imgs, ids = rt._reference_images(NS(state={"documents": DOCS}), ["d1", "d2"])
        self.assertEqual(ids, ["d1", "d2"])
        body = ('<section class="page"><div class="hdr"><div class="hdr-r"><span class="draft">DRAFT - menunggu '
                'approval</span></div></div><p>ok</p><div class="footer"><span>Sumber: x</span></div></section>')
        with mock.patch("library_agent.report_engine.generate_text",
                        return_value="LAPORAN RETAIL ONLY — X · Q3\n```html\n" + body + "\n```") as gen:
            res = cr.generate("retail", "laporan per PTPL product", "| a |\n|---|\n| 1 |", images=imgs)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(len(gen.call_args.kwargs["images"]), 2)
        self.assertIn("GAMBAR REFERENSI DARI USER", gen.call_args[0][0])

    def test_claude_complete_sends_image_blocks(self):
        from library_agent import llm_claude

        sent = {}

        class Msgs:
            def create(self, **kw):
                sent.update(kw)
                return NS(content=[NS(type="text", text="ok")], usage=None)
        fake = NS(AnthropicVertex=lambda **kw: NS(messages=Msgs()))
        with mock.patch.dict(sys.modules, {"anthropic": fake}):
            llm_claude.complete("tulis", images=[(b"\xff\xd8jpg", "image/jpeg")])
        blocks = sent["messages"][0]["content"]
        self.assertEqual(blocks[0]["type"], "image")
        self.assertEqual(blocks[-1], {"type": "text", "text": "tulis"})


if __name__ == "__main__":
    unittest.main()
