"""Cek model Gemini bisa dipanggil dari project ini sebelum redeploy.

    python scripts/check_models.py

Memanggil LIB_MODEL_FAST di LIB_GEMINI_LOCATION dan LIB_MODEL_PRO (Gemini 4 Argon) di LIB_GEMINI_LOCATION_PRO
dengan akun yang sedang login di Cloud Shell. Jika gagal (404/403), jangan redeploy dulu — lihat PANDUAN_REDEPLOY.md.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv  # noqa: E402

load_dotenv()
from google import genai  # noqa: E402

project = os.getenv("LIB_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")
checks = [(os.getenv("LIB_MODEL_FAST", "gemini-3.5-flash"), os.getenv("LIB_GEMINI_LOCATION", "global")),
          (os.getenv("LIB_MODEL_PRO", "gemini-4-argon"), os.getenv("LIB_GEMINI_LOCATION_PRO", "asia-southeast1"))]
ok = True
for model, location in checks:
    try:
        client = genai.Client(vertexai=True, project=project, location=location)
        text = client.models.generate_content(model=model, contents="Jawab satu kata: siap").text or ""
        print(f"OK    {model} @ {location}: {text.strip()[:40]}")
    except Exception as exc:  # noqa: BLE001
        ok = False
        print(f"GAGAL {model} @ {location}: {str(exc)[:300]}")
print("\nHASIL:", "OK — kedua model bisa dipanggil." if ok else "BELUM OK — perbaiki dulu sebelum redeploy.")
sys.exit(0 if ok else 1)
