#!/usr/bin/env bash
# Update agent yang sudah ter-deploy dengan kode terbaru dari repo (update DI TEMPAT). Satu perintah:
#   bash scripts/update_agent.sh
# Aman dijalankan berulang kali. Pendaftaran agent di Gemini Enterprise tidak perlu diulang.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> 1/6 Ambil kode terbaru"
git pull --ff-only

echo "==> 2/6 Siapkan Python"
[ -d .venv ] || python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt

echo "==> 3/6 Rapikan .env"
[ -f .env ] || { echo "File .env tidak ditemukan. Salin .env.example menjadi .env lalu isi nilainya."; exit 1; }
add_if_missing() { grep -q "^$1=" .env || echo "$1=$2" >> .env; }
set_value() { if grep -q "^$1=" .env; then sed -i -E "s#^$1=.*#$1=$2#" .env; else echo "$1=$2" >> .env; fi; }
# Pengaturan perpustakaan dokumen (sudah dihapus dari agent) dibuang dari .env.
sed -i -E '/^LIB_(DATASTORE_ID|SERVING_CONFIG|SEARCH_RESULT_MODE|SEARCH_LOCATION|DOC_TYPES|DOC_TYPE_HINTS|MAX_ACTIVE_DOCS|SOURCE_FOLDER|FOLDER_BATCH_SIZE|TEMPLATE_SOURCE|LOCAL_TEMPLATE_DIR|STAGING_PREFIX|TEMPLATE_PREFIX|CATALOG_PATH|INSIGHT_PREFIX|LIBRARY_PREFIX)=/d' .env
add_if_missing LIB_INTERNAL_FOLDER "ge-docs-agent"
add_if_missing LIB_MAX_FILE_MB "100"
# Model utama Gemini 4 Argon. Nilai yang sudah ada di .env TIDAK ditimpa; untuk mengganti, jalankan dengan
# NEW_MODEL_PRO=... / NEW_GEMINI_LOCATION_PRO=global bash scripts/update_agent.sh
if [ -n "${NEW_MODEL_PRO:-}" ]; then set_value LIB_MODEL_PRO "$NEW_MODEL_PRO"; else add_if_missing LIB_MODEL_PRO "gemini-4-argon"; fi
if [ -n "${NEW_GEMINI_LOCATION_PRO:-}" ]; then set_value LIB_GEMINI_LOCATION_PRO "$NEW_GEMINI_LOCATION_PRO"
else add_if_missing LIB_GEMINI_LOCATION_PRO "asia-southeast1"; fi
echo "    Model utama: $(grep '^LIB_MODEL_PRO=' .env | cut -d= -f2) @ $(grep '^LIB_GEMINI_LOCATION_PRO=' .env | cut -d= -f2)"
# Claude untuk tugas berat (analisis file + skill, laporan). Nilai yang sudah ada tidak ditimpa.
if [ -n "${NEW_MODEL_CLAUDE:-}" ]; then set_value LIB_MODEL_CLAUDE "$NEW_MODEL_CLAUDE"; else add_if_missing LIB_MODEL_CLAUDE "claude-opus-5-5"; fi
if [ -n "${NEW_CLAUDE_REGION:-}" ]; then set_value LIB_CLAUDE_REGION "$NEW_CLAUDE_REGION"; else add_if_missing LIB_CLAUDE_REGION "global"; fi
echo "    Tugas berat: $(grep '^LIB_MODEL_CLAUDE=' .env | cut -d= -f2) @ $(grep '^LIB_CLAUDE_REGION=' .env | cut -d= -f2) (cadangan Argon)"
add_if_missing LIB_MODEL_FAST "gemini-3.5-flash"
add_if_missing LIB_GEMINI_LOCATION "global"
# Data Agent & tabel planogram
add_if_missing LIB_DATA_AGENT_PLANOGRAM "projects/ptpl-land-dev/locations/global/dataAgents/agent_5f69a707-a240-49ea-9c96-dd12493f659c"
add_if_missing LIB_PLANOGRAM_TABLE "ptpl-curated-prd.DATAMART.VM_PLANOGRAM"
add_if_missing LIB_PLANOGRAM_DEFAULT_PERIOD "2026-Q3"
set -a; source .env; set +a
gcloud config set project "$LIB_PROJECT_ID" >/dev/null 2>&1
B="gs://$LIB_BUCKET"
CFG="$B/$LIB_INTERNAL_FOLDER/config/settings.json"

echo "==> 4/6 Perbarui settings.json di bucket: $CFG"
# Kunci baru ditambahkan, kunci perpustakaan dokumen dibuang, nilai yang sudah Anda ubah TIDAK ditimpa.
python - "$CFG" <<'PY'
import json, subprocess, sys
cfg = sys.argv[1]
new = json.load(open("setup/settings.json", encoding="utf-8"))
try:
    cur = json.loads(subprocess.run(["gcloud", "storage", "cat", cfg], capture_output=True, text=True, check=True).stdout)
except Exception:
    cur = {}
old_keys = {"allowed_doc_types", "doc_type_hints", "max_active_docs", "source_folder", "folder_batch_size"}
removed = sorted(k for k in cur if k in old_keys)
added = sorted(k for k in new if k not in cur)
merged = {k: v for k, v in cur.items() if k not in old_keys}
for k in added:
    merged[k] = new[k]
open("/tmp/settings_merged.json", "w", encoding="utf-8").write(json.dumps(merged, ensure_ascii=False, indent=2))
print("    ditambahkan:", ", ".join(added) or "-")
print("    dibuang    :", ", ".join(removed) or "-")
PY
gcloud storage cp /tmp/settings_merged.json "$CFG" >/dev/null && echo "    settings.json diperbarui"

echo "==> 5/6 Uji unit"
python -m unittest discover tests >/dev/null 2>&1 || { python -m unittest discover tests; echo "Uji gagal, update dibatalkan."; exit 1; }
echo "    OK"
if [ -z "${LIB_AGENT_RESOURCE:-}" ]; then
  echo "    Mencari resource agent '${LIB_AGENT_DISPLAY_NAME:-marketing-insight-assistant}'..."
  RES=$(python - <<'PY'
import os, vertexai
from vertexai import agent_engines
vertexai.init(project=os.environ["LIB_PROJECT_ID"], location=os.environ["LIB_AGENT_ENGINE_REGION"])
name = os.environ.get("LIB_AGENT_DISPLAY_NAME", "marketing-insight-assistant")
found = [e.resource_name for e in agent_engines.list() if e.display_name in (name, "document-insight-agent", "asisten-perpustakaan")]
print(found[0] if len(found) == 1 else "")
PY
)
  if [ -z "$RES" ]; then
    echo "Resource agent tidak ditemukan otomatis (tidak ada, atau lebih dari satu)."
    echo "Tambahkan manual ke .env: LIB_AGENT_RESOURCE=projects/.../reasoningEngines/<ID>"
    exit 1
  fi
  echo "LIB_AGENT_RESOURCE=$RES" >> .env
  export LIB_AGENT_RESOURCE="$RES"
  echo "    Ditemukan dan disimpan ke .env: $RES"
fi

echo "==> 6/6 Update agent (5-10 menit)"
python scripts/deploy_agent_engine.py --update "$LIB_AGENT_RESOURCE"
echo "Selesai. Buka chat baru di Gemini Enterprise untuk mencoba."
