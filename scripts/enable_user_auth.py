"""Aktifkan otorisasi user (OAuth) untuk data BigQuery di pendaftaran agent Gemini Enterprise.

Yang dilakukan script ini:
1. Membaca JSON OAuth client (hasil "Download JSON" di Konsol).
2. Membuat resource Authorization di Gemini Enterprise (ID default: mia-bigquery).
3. Mencari pendaftaran agent di semua app GE project ini yang memakai LIB_AGENT_RESOURCE.
4. Menambahkan Authorization tersebut ke pendaftaran yang sudah ada (tanpa daftar ulang).

Pemakaian (Cloud Shell, di folder repo, setelah `source .env`):
    python scripts/enable_user_auth.py ~/client_secret.json
    python scripts/enable_user_auth.py ~/client_secret.json --auth-id mia-bigquery
    python scripts/enable_user_auth.py ~/client_secret.json --register-new   # rencana cadangan
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse

import google.auth
from google.auth.transport.requests import AuthorizedSession

API = "https://global-discoveryengine.googleapis.com/v1alpha"
SCOPE = "https://www.googleapis.com/auth/cloud-platform"
REDIRECT = "https://vertexaisearch.cloud.google.com/static/oauth/oauth.html"


def fail(msg: str) -> None:
    print(f"\nGAGAL: {msg}")
    sys.exit(1)


def load_client(path: str) -> dict:
    with open(os.path.expanduser(path), encoding="utf-8") as fh:
        raw = json.load(fh)
    client = raw.get("web") or raw.get("installed") or raw
    for key in ("client_id", "client_secret", "token_uri"):
        if not client.get(key):
            fail(f"File JSON tidak berisi '{key}'. Pastikan tipe OAuth client = Web application.")
    return client


def auth_uri(client_id: str) -> str:
    query = urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": REDIRECT, "scope": SCOPE,
        "include_granted_scopes": "true", "response_type": "code",
        "access_type": "offline", "prompt": "consent",
    })
    return f"https://accounts.google.com/o/oauth2/v2/auth?{query}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("client_json")
    parser.add_argument("--auth-id", default=os.environ.get("LIB_DATA_AUTH_ID", "mia-bigquery"))
    parser.add_argument("--register-new", action="store_true",
                        help="Buat pendaftaran baru berisi Authorization (jika pendaftaran lama tidak bisa diubah)")
    args = parser.parse_args()

    project = os.environ.get("LIB_PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT")
    agent_resource = os.environ.get("LIB_AGENT_RESOURCE", "")
    if not project or not agent_resource:
        fail("LIB_PROJECT_ID dan LIB_AGENT_RESOURCE harus ada di .env (jalankan `set -a && source .env && set +a`).")
    project_number = agent_resource.split("/")[1]
    client = load_client(args.client_json)

    creds, _ = google.auth.default(scopes=[SCOPE])
    http = AuthorizedSession(creds)
    http.headers.update({"X-Goog-User-Project": project, "Content-Type": "application/json"})

    # 1) Authorization resource
    auth_name = f"projects/{project_number}/locations/global/authorizations/{args.auth_id}"
    body = {"name": auth_name, "serverSideOauth2": {
        "clientId": client["client_id"], "clientSecret": client["client_secret"],
        "authorizationUri": auth_uri(client["client_id"]), "tokenUri": client["token_uri"]}}
    r = http.post(f"{API}/projects/{project_number}/locations/global/authorizations",
                  params={"authorizationId": args.auth_id}, data=json.dumps(body))
    if r.status_code == 409:
        r = http.patch(f"{API}/{auth_name}", data=json.dumps(body))
        print(f"1/3 Authorization '{args.auth_id}' sudah ada, diperbarui ({r.status_code})")
    else:
        print(f"1/3 Membuat Authorization '{args.auth_id}' ({r.status_code})")
    if r.status_code >= 300:
        fail(r.text[:600])

    # 2) Cari pendaftaran agent
    r = http.get(f"{API}/projects/{project}/locations/global/collections/default_collection/engines")
    if r.status_code >= 300:
        fail("Tidak bisa membaca daftar app GE: " + r.text[:400])
    found, found_engine = None, None
    for engine in r.json().get("engines", []):
        rr = http.get(f"{API}/{engine['name']}/assistants/default_assistant/agents")
        if rr.status_code >= 300:
            continue
        for agent in rr.json().get("agents", []):
            engine_ref = ((agent.get("adkAgentDefinition") or {}).get("provisionedReasoningEngine") or {}) \
                .get("reasoningEngine", "")
            if engine_ref.split("/")[-1] == agent_resource.split("/")[-1]:
                found, found_engine = agent, engine["name"]
                print(f"2/3 Pendaftaran ditemukan: '{agent.get('displayName')}' di app {engine['name'].split('/')[-1]}")
                break
        if found:
            break
    if not found:
        fail("Pendaftaran agent dengan resource ini tidak ditemukan di app GE mana pun. Gunakan opsi daftar ulang.")

    if args.register_new:
        new = {
            "displayName": found.get("displayName"),
            "description": found.get("description"),
            "adkAgentDefinition": found.get("adkAgentDefinition"),
            "authorizationConfig": {"toolAuthorizations": [auth_name]},
        }
        r = http.post(f"{API}/{found_engine}/assistants/default_assistant/agents", data=json.dumps(new))
        if r.status_code >= 300:
            fail("Pendaftaran baru gagal dibuat: " + r.text[:600])
        print("3/3 Pendaftaran BARU dibuat dengan Authorization.\n"
              "\nLangkah lanjutan di Konsol (Gemini Enterprise → app → Agents):\n"
              f"  - Bagikan agent baru '{found.get('displayName')}' ke user yang memakai agent.\n"
              "  - Hapus pendaftaran LAMA (yang tanpa Authorization) agar tidak muncul dua kali.")
        return

    # 3) Tambahkan Authorization ke pendaftaran yang ada
    existing = (found.get("authorizationConfig") or {}).get("toolAuthorizations", [])
    patch = {
        "displayName": found.get("displayName"),
        "description": found.get("description"),
        "adkAgentDefinition": found.get("adkAgentDefinition"),
        "authorizationConfig": {"toolAuthorizations": sorted(set(existing + [auth_name]))},
    }
    r = http.patch(f"{API}/{found['name']}", data=json.dumps(patch))
    if r.status_code >= 300:
        fail("Pendaftaran tidak bisa diubah lewat API: " + r.text[:600] +
             "\nJalankan ulang dengan opsi --register-new (lihat PANDUAN_SETUP bagian 2.5, Rencana B).")
    check = http.get(f"{API}/{found['name']}").json()
    attached = (check.get("authorizationConfig") or {}).get("toolAuthorizations", [])
    if auth_name not in attached:
        fail("API menerima perubahan, tetapi Authorization tidak tersimpan. Jalankan ulang dengan opsi --register-new.")
    print(f"3/3 Authorization terpasang pada pendaftaran agent.\n\nSelesai. ID Authorization: {args.auth_id}")


if __name__ == "__main__":
    main()
