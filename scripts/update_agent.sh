#!/usr/bin/env bash
# Update agent yang sudah ter-deploy dengan kode terbaru dari repo. Satu perintah:
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
[ -f .env ] || { echo "File .env tidak ditemukan. Buat dulu sesuai PANDUAN_SETUP.md Tahap 2."; exit 1; }
add_if_missing() { grep -q "^$1=" .env || echo "$1=$2" >> .env; }
# Folder kerja lama (mis. agent-perpustakaan) dibaca dari .env sebelum barisnya dihapus.
OLD_ROOT=$( (grep '^LIB_CATALOG_PATH=' .env || true) | head -1 | cut -d= -f2- | tr -d '"' | cut -d/ -f1)
[ "$OLD_ROOT" = "catalog" ] && OLD_ROOT=""
sed -i -E '/^LIB_(STAGING_PREFIX|TEMPLATE_PREFIX|REPORT_PREFIX|CATALOG_PATH|INSIGHT_PREFIX|LIBRARY_PREFIX)=/d' .env
add_if_missing LIB_INTERNAL_FOLDER "ge-docs-agent"
add_if_missing LIB_SOURCE_FOLDER "gs://ptpl-ge-bucket/ge-docs-datastore/"
add_if_missing LIB_FOLDER_BATCH_SIZE "20"
add_if_missing LIB_MAX_FILE_MB "100"
unset LIB_STAGING_PREFIX LIB_TEMPLATE_PREFIX LIB_REPORT_PREFIX LIB_CATALOG_PATH LIB_INSIGHT_PREFIX LIB_LIBRARY_PREFIX
set -a; source .env; set +a
gcloud config set project "$LIB_PROJECT_ID" >/dev/null 2>&1
NEW_ROOT="$LIB_INTERNAL_FOLDER"
B="gs://$LIB_BUCKET"

echo "==> 4/6 Siapkan folder kerja agent: $B/$NEW_ROOT/"
if [ -n "$OLD_ROOT" ] && [ "$OLD_ROOT" != "$NEW_ROOT" ] && gcloud storage ls "$B/$OLD_ROOT/" >/dev/null 2>&1; then
  echo "    Memindahkan isi $OLD_ROOT/ -> $NEW_ROOT/"
  for SUB in templates insights config reports; do
    if gcloud storage ls "$B/$OLD_ROOT/$SUB/" >/dev/null 2>&1; then
      gcloud storage cp -r "$B/$OLD_ROOT/$SUB" "$B/$NEW_ROOT/" >/dev/null
      echo "      $SUB/ dipindahkan"
    fi
  done
  # Izin baca laporan (IAM condition) yang masih menunjuk folder lama ikut diperbarui.
  POLICY=$(mktemp)
  gcloud storage buckets get-iam-policy "$B" --format=json > "$POLICY"
  if grep -q "objects/$OLD_ROOT/" "$POLICY"; then
    sed -i "s#objects/$OLD_ROOT/#objects/$NEW_ROOT/#g" "$POLICY"
    gcloud storage buckets set-iam-policy "$B" "$POLICY" >/dev/null
    echo "      izin baca laporan diperbarui ke $NEW_ROOT/reports/"
  fi
  rm -f "$POLICY"
  gcloud storage rm -r "$B/$OLD_ROOT/" >/dev/null
  echo "      folder $OLD_ROOT/ dihapus (katalog dibangun ulang otomatis dari ge-docs-datastore)"
fi
# Template baru dari repo diunggah; template yang sudah ada di bucket tidak ditimpa.
python scripts/upload_templates.py --missing-only | sed 's/^/    /' || true
if ! gcloud storage ls "$B/$NEW_ROOT/config/settings.json" >/dev/null 2>&1; then
  gcloud storage cp setup/settings.json "$B/$NEW_ROOT/config/settings.json" >/dev/null && echo "    settings.json diunggah"
fi

echo "    Memeriksa data store perpustakaan..."
if ! python - <<'PY' >/dev/null 2>&1
import sys
sys.path.insert(0, ".")
from google.api_core.exceptions import NotFound
from google.cloud import discoveryengine_v1 as de
from library_agent.clients import _discovery_client_options, datastore_path
try:
    de.DataStoreServiceClient(client_options=_discovery_client_options()).get_data_store(name=datastore_path())
except NotFound:
    sys.exit(1)
PY
then
  echo "    Data store belum ada, membuat sekarang (beberapa menit)..."
  python scripts/setup_datastore.py
else
  echo "    Data store sudah ada"
fi

echo "==> 5/6 Uji unit"
python -m unittest discover tests >/dev/null 2>&1 || { python -m unittest discover tests; echo "Uji gagal, update dibatalkan."; exit 1; }
echo "    OK"
if [ -z "${LIB_AGENT_RESOURCE:-}" ]; then
  echo "    Mencari resource agent '${LIB_AGENT_DISPLAY_NAME:-document-insight-agent}'..."
  RES=$(python - <<'PY'
import os, vertexai
from vertexai import agent_engines
vertexai.init(project=os.environ["LIB_PROJECT_ID"], location=os.environ["LIB_AGENT_ENGINE_REGION"])
name = os.environ.get("LIB_AGENT_DISPLAY_NAME", "document-insight-agent")
found = [e.resource_name for e in agent_engines.list() if e.display_name in (name, "asisten-perpustakaan")]
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
