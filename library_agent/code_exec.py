"""Eksekusi kode Python di Vertex AI Agent Engine Code Execution (sandbox terisolasi, tanpa jaringan).

Dipakai agent analisis file untuk analisis BEBAS sesuai instruksi user (metodologi apa pun, output apa pun).
Fitur ini MATI secara default; dinyalakan lewat settings.json (code_execution_enabled + code_execution_users).

Pengaman biaya & keamanan:
- Saklar on/off + daftar user yang diizinkan (uji coba terbatas).
- Batas eksekusi per pesan user (code_execution_max_steps).
- Batas biaya harian dari meteran (usage.budget_status) — tercapai -> eksekusi ditolak sampai besok.
- Satu sandbox per chat dengan TTL pendek (diperpanjang tiap eksekusi), mesin tetap (4 vCPU / 4 GiB).
- Sandbox tidak punya akses jaringan/kredensial; hanya file yang dikirim agent yang bisa dibaca kode.
- File CSV/Excel chat dikirim sebagai CSV (Excel dikonversi di sisi agent, satu CSV per sheet).
- Semua file yang dihasilkan kode disimpan ke bucket laporan dan dibagikan sebagai link; kode setiap langkah
  disimpan sebagai jejak audit (script .py yang bisa dijalankan ulang).
"""
from __future__ import annotations

import io
import json
import logging
import mimetypes
import re
import time
from datetime import datetime, timezone
from typing import Any

from .config import live, settings

logger = logging.getLogger(__name__)
SANDBOX_KEY = "code_sandbox"
STEP_KEY = "temp:code_steps"
OUTPUT_KEY = "temp:code_outputs"
MAX_STDOUT = 12000
BATCH_BYTES = 60 * 1024 * 1024          # batas aman per request (sandbox menerima maks. 100 MB per request)
_FILES_FIELD = {"value": "content"}     # nama field isi file pada execute_code; diuji otomatis ("content"/"contents")


# ==========================================================================
# Akses & pengaman
# ==========================================================================
def allowed(user_id: str) -> tuple[bool, str]:
    hint = (" Jangan menyebut fitur ini ke user; lanjutkan dengan analyze_data dan ekspor_excel. "
            "Jika ada perhitungan yang tetap tidak bisa dilakukan, katakan bagian itu belum bisa dihitung.")
    if not live("code_execution_enabled"):
        return False, "Eksekusi kode tidak tersedia." + hint
    users = [u.lower() for u in (live("code_execution_users") or ())]
    if users and (user_id or "").lower() not in users:
        return False, f"Eksekusi kode tidak tersedia untuk user ini (ID: {user_id})." + hint
    return True, ""


def region() -> str:
    """Region sandbox = region resource agent induk (mis. asia-southeast2), agar data tidak keluar region agent."""
    m = re.search(r"/locations/([^/]+)/", _engine())
    if not m:
        raise RuntimeError(f"Resource agent tidak valid: {_engine()}")
    return m.group(1)


def _client():
    try:
        import agentplatform  # SDK baru (pengganti vertexai.Client)

        return agentplatform.Client(project=settings.project_id, location=region())
    except Exception:  # noqa: BLE001
        import vertexai

        return vertexai.Client(project=settings.project_id, location=region())


def _engine() -> str:
    eng = settings.code_execution_engine
    if not eng:
        raise RuntimeError("LIB_AGENT_RESOURCE / LIB_CODE_EXECUTION_ENGINE belum diisi di .env.")
    return eng


# ==========================================================================
# Sandbox
# ==========================================================================
def _create_sandbox(client) -> str:
    spec: dict[str, Any] = {"code_execution_environment": {}}
    if settings.code_execution_machine:
        spec["code_execution_environment"]["machine_config"] = settings.code_execution_machine
    cfg: Any = {"display_name": "mia-analisis", "ttl": f"{int(live('code_execution_ttl_seconds') or 1800)}s"}
    try:
        from vertexai import types

        cfg = types.CreateAgentEngineSandboxConfig(**cfg)
    except Exception:  # noqa: BLE001  (SDK menerima dict juga)
        pass
    op = client.agent_engines.sandboxes.create(spec=spec, name=_engine(), config=cfg)
    return op.response.name


def _alive(client, name: str) -> bool:
    try:
        sb = client.agent_engines.sandboxes.get(name=name)
        return "RUNNING" in str(getattr(sb, "state", "")).upper()
    except Exception:  # noqa: BLE001
        return False


def ensure_sandbox(state, client) -> dict:
    info = dict(state.get(SANDBOX_KEY) or {})
    if info.get("name") and _alive(client, info["name"]):
        return info
    info = {"name": _create_sandbox(client), "uploaded": [], "created": time.time()}
    state[SANDBOX_KEY] = info
    logger.info("Sandbox dibuat: %s", info["name"])
    return info


def delete_sandbox(state) -> bool:
    info = state.get(SANDBOX_KEY) or {}
    if not info.get("name"):
        return False
    try:
        _client().agent_engines.sandboxes.delete(name=info["name"])
    except Exception:  # noqa: BLE001
        logger.warning("Sandbox gagal dihapus (akan kedaluwarsa sendiri oleh TTL)", exc_info=True)
    state[SANDBOX_KEY] = None
    return True


# ==========================================================================
# File masuk
# ==========================================================================
def csv_name(file_id: str, filename: str, sheet: str = "") -> str:
    base = re.sub(r"\.[A-Za-z0-9]+$", "", filename)
    base = re.sub(r"[^A-Za-z0-9_-]+", "_", base).strip("_")[:60] or "data"
    sh = ("__" + re.sub(r"[^A-Za-z0-9_-]+", "_", sheet).strip("_")[:30]) if sheet else ""
    return f"{file_id}_{base}{sh}.csv"


def input_files(data_files: list[dict]) -> list[dict]:
    """File data chat -> [{'name','content','file_id'}] sebagai CSV (Excel: satu CSV per sheet)."""
    import pandas as pd

    from .clients import parse_gcs_uri, storage_client

    out = []
    for f in data_files:
        bucket, path = parse_gcs_uri(f["uri"])
        raw = storage_client().bucket(bucket).blob(path).download_as_bytes()
        name = f["filename"].lower()
        if name.endswith((".xlsx", ".xlsm", ".xls")):
            sheets = pd.read_excel(io.BytesIO(raw), sheet_name=None)
            for sheet, df in sheets.items():
                label = sheet if len(sheets) > 1 else ""
                out.append({"name": csv_name(f["file_id"], f["filename"], label), "file_id": f["file_id"],
                            "content": df.to_csv(index=False).encode("utf-8")})
        else:
            out.append({"name": csv_name(f["file_id"], f["filename"]), "file_id": f["file_id"], "content": raw})
    return out


# ==========================================================================
# Eksekusi
# ==========================================================================
def _execute(client, sandbox: str, code: str, files: list[dict]):
    payload: dict[str, Any] = {"code": code}
    if files:
        payload["files"] = [{"name": f["name"], _FILES_FIELD["value"]: f["content"]} for f in files]
    try:
        return client.agent_engines.sandboxes.execute_code(name=sandbox, input_data=payload)
    except Exception as exc:  # noqa: BLE001
        if files and _FILES_FIELD["value"] == "content" and re.search(r"content|field|unknown|invalid", str(exc), re.I):
            _FILES_FIELD["value"] = "contents"
            payload["files"] = [{"name": f["name"], "contents": f["content"]} for f in files]
            return client.agent_engines.sandboxes.execute_code(name=sandbox, input_data=payload)
        raise


def _execute_batched(client, sandbox: str, code: str, files: list[dict]):
    """Kirim file dalam beberapa batch bila total ukurannya besar (mis. 7 file Excel), lalu jalankan kode."""
    big = [f["name"] for f in files if len(f["content"]) > BATCH_BYTES]
    if big:
        raise ValueError(f"File terlalu besar untuk sandbox (> {BATCH_BYTES // 1024 // 1024} MB setelah dikonversi ke CSV): "
                         + ", ".join(big) + ". Minta user memfilter/memecah file tersebut.")
    batches, cur, size = [], [], 0
    for f in files:
        if cur and size + len(f["content"]) > BATCH_BYTES:
            batches.append(cur)
            cur, size = [], 0
        cur.append(f)
        size += len(f["content"])
    if cur:
        batches.append(cur)
    if len(batches) <= 1:
        return _execute(client, sandbox, code, files)
    for b in batches[:-1]:
        _execute(client, sandbox, "print('file diterima')", b)
    return _execute(client, sandbox, code, batches[-1])


def parse_response(response, input_names: set[str]) -> dict[str, Any]:
    stdout, stderr, exit_code, files = "", "", None, []
    for ch in getattr(response, "outputs", None) or []:
        meta = getattr(getattr(ch, "metadata", None), "attributes", None) or {}
        fname = meta.get("file_name") if isinstance(meta, dict) else None
        if isinstance(fname, bytes):
            fname = fname.decode("utf-8", "ignore")
        data = getattr(ch, "data", b"") or b""
        mime = getattr(ch, "mime_type", "") or ""
        if not fname and mime == "application/json":
            try:
                j = json.loads(data.decode("utf-8"))
                stdout += j.get("msg_out", "") or ""
                stderr += j.get("msg_err", "") or ""
                exit_code = j.get("exit_status_int", exit_code)
                continue
            except (ValueError, UnicodeDecodeError):
                pass
        fname = fname or f"output_{len(files) + 1}{mimetypes.guess_extension(mime) or ''}"
        if fname.split("/")[-1] in input_names:
            continue
        files.append({"name": fname.split("/")[-1], "content": data, "mime_type": mime or mimetypes.guess_type(fname)[0] or
                      "application/octet-stream"})
    return {"stdout": stdout, "stderr": stderr, "exit_code": exit_code, "files": files}


def save_outputs(user_id: str, session_id: str, step: int, code: str, files: list[dict]) -> tuple[str, list[dict]]:
    from .clients import gcs_console_url, storage_client

    user_slug = re.sub(r"[^A-Za-z0-9._@-]+", "_", user_id)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    base = f"{settings.report_prefix}/{user_slug}/analisis-{stamp}-{session_id[-8:]}"
    bucket = storage_client().bucket(settings.report_bucket)
    script = f"{base}/langkah_{step:02d}.py"
    bucket.blob(script).upload_from_string(code, content_type="text/x-python; charset=utf-8")
    links = []
    for f in files:
        path = f"{base}/{f['name']}"
        blob = bucket.blob(path)
        if not f["name"].lower().endswith((".html", ".htm", ".png", ".jpg", ".svg")):
            blob.content_disposition = f'attachment; filename="{f["name"]}"'
        blob.upload_from_string(f["content"], content_type=f["mime_type"])
        links.append({"file": f["name"], "url": gcs_console_url(settings.report_bucket, path), "bytes": len(f["content"])})
    return gcs_console_url(settings.report_bucket, script), links


def run(code: str, purpose: str, tool_context) -> dict[str, Any]:
    """Jalankan satu langkah kode dengan semua pengaman. Hasil: stdout/stderr/file/link + sisa langkah & biaya."""
    from . import usage
    from .clients import get_session_id, get_user_id

    user = get_user_id(tool_context)
    ok, why = allowed(user)
    if not ok:
        return {"status": "disabled", "message": why}
    steps = int(tool_context.state.get(STEP_KEY, 0) or 0)
    max_steps = int(live("code_execution_max_steps") or 25)
    if steps >= max_steps:
        return {"status": "step_limit", "message": f"Batas {max_steps} eksekusi kode untuk satu pesan sudah tercapai. "
                                                   "Laporkan progres ke user dan tanyakan apakah analisis dilanjutkan."}
    budget = usage.budget_status()
    if budget["exceeded"]:
        return {"status": "budget_limit", "message": f"Batas biaya harian analisis (USD {budget['budget_usd']:g}) sudah "
                                                     f"tercapai (tercatat USD {budget['spent_usd']:g}). Fitur aktif lagi besok."}
    if not code.strip():
        return {"status": "invalid", "message": "Kode kosong."}
    client = _client()
    info = ensure_sandbox(tool_context.state, client)
    data_files = tool_context.state.get("data_files", []) or []
    files = _pending(info, data_files)
    t0 = time.time()
    try:
        resp = _execute_batched(client, info["name"], code, files)
    except ValueError as exc:
        return {"status": "file_too_large", "message": str(exc)}
    except Exception as exc:  # noqa: BLE001
        if not re.search(r"RUNNING|NOT_FOUND|404|FAILED_PRECONDITION", str(exc), re.I):
            raise
        tool_context.state[SANDBOX_KEY] = None              # sandbox kedaluwarsa -> buat ulang & kirim ulang file
        info = ensure_sandbox(tool_context.state, client)
        files = _pending(info, data_files)
        resp = _execute_batched(client, info["name"], code, files)
    seconds = time.time() - t0
    usd = usage.record_sandbox(user, seconds)
    _mark_uploaded(tool_context.state, info, files)
    out = parse_response(resp, {f["name"] for f in info.get("files", [])})
    if "FileNotFoundError" in out["stderr"] and data_files:
        info["uploaded"] = []                                # file hilang di sandbox -> dikirim ulang di langkah berikut
        tool_context.state[SANDBOX_KEY] = info
    tool_context.state[STEP_KEY] = steps + 1
    script, links = save_outputs(user, get_session_id(tool_context), steps + 1, code, out["files"])
    stdout = out["stdout"]
    outputs = list(tool_context.state.get(OUTPUT_KEY, []) or [])
    outputs.append(stdout[:200000])
    tool_context.state[OUTPUT_KEY] = outputs[-30:]
    return {"status": "ok" if not out["exit_code"] else "error", "langkah": steps + 1, "sisa_langkah": max_steps - steps - 1,
            "tujuan": purpose, "stdout": stdout[:MAX_STDOUT] + ("\n...[stdout terpotong]" if len(stdout) > MAX_STDOUT else ""),
            "stderr": out["stderr"][-4000:], "file_output": links, "script_langkah_ini": script,
            "biaya_sandbox_langkah_usd": round(usd, 5)}


def _pending(info: dict, data_files: list[dict]) -> list[dict]:
    pending = [f for f in data_files if f["file_id"] not in info.get("uploaded", [])]
    return input_files(pending) if pending else []


def _mark_uploaded(state, info: dict, files: list[dict]) -> None:
    if not files:
        return
    known = {f["name"]: f for f in info.get("files", [])}
    for f in files:
        known[f["name"]] = {"name": f["name"], "file_id": f["file_id"]}
    info["files"] = sorted(known.values(), key=lambda x: x["name"])
    info["uploaded"] = sorted(set(info.get("uploaded", [])) | {f["file_id"] for f in files})
    state[SANDBOX_KEY] = info


def prepare(tool_context) -> dict[str, Any]:
    """Siapkan sandbox & kirim semua file data chat; kembalikan nama file di sandbox beserta ukurannya."""
    from . import usage
    from .clients import get_user_id

    user = get_user_id(tool_context)
    ok, why = allowed(user)
    if not ok:
        return {"status": "disabled", "message": why}
    budget = usage.budget_status()
    if budget["exceeded"]:
        return {"status": "budget_limit", "message": f"Batas biaya harian (USD {budget['budget_usd']:g}) sudah tercapai."}
    data_files = tool_context.state.get("data_files", []) or []
    if not data_files:
        return {"status": "no_files", "message": "Belum ada file CSV/Excel di chat ini."}
    client = _client()
    info = ensure_sandbox(tool_context.state, client)
    files = _pending(info, data_files)
    probe = ("import os, pandas as pd\n"
             "for n in sorted(f for f in os.listdir('.') if f.endswith('.csv')):\n"
             "    df = pd.read_csv(n, nrows=5, low_memory=False)\n"
             "    print(n, '|', sum(1 for _ in open(n, encoding='utf-8', errors='ignore')) - 1, 'baris |', ', '.join(map(str, df.columns))[:1500])")
    t0 = time.time()
    try:
        resp = _execute_batched(client, info["name"], probe, files)
    except ValueError as exc:
        return {"status": "file_too_large", "message": str(exc)}
    usage.record_sandbox(user, time.time() - t0)
    _mark_uploaded(tool_context.state, info, files)
    out = parse_response(resp, {f["name"] for f in info.get("files", [])})
    return {"status": "ok", "sandbox_siap": True, "file_di_sandbox": out["stdout"][:6000] or "(tidak ada file CSV)",
            "stderr": out["stderr"][-2000:], "catatan": "Baca file dengan pd.read_csv('<nama file>') di direktori kerja. "
                                                     "Excel sudah dikonversi: satu CSV per sheet."}
