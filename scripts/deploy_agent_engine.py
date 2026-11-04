"""Deploy agent ke Vertex AI Agent Engine.

Pemakaian:
    python scripts/deploy_agent_engine.py            # deploy baru (sekali saja)
    python scripts/deploy_agent_engine.py --update projects/.../reasoningEngines/123   # update di tempat

Semua environment variable berawalan LIB_ ikut dikirim ke Agent Engine.
Setelah deploy, daftarkan resource Agent Engine ke Gemini Enterprise (lihat README).
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

import vertexai  # noqa: E402
from vertexai import agent_engines  # noqa: E402

try:
    from vertexai.agent_engines import AdkApp  # SDK baru
except ImportError:  # pragma: no cover
    from vertexai.preview.reasoning_engines import AdkApp  # SDK lama


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", default="", help="Resource name Agent Engine yang akan diperbarui")
    parser.add_argument("--region", default=os.getenv("LIB_AGENT_ENGINE_REGION", "us-central1"))
    args = parser.parse_args()

    project = os.getenv("LIB_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")
    bucket = os.environ["LIB_BUCKET"]
    vertexai.init(project=project, location=args.region, staging_bucket=f"gs://{bucket}")

    from library_agent.agent import root_agent

    # report_assets (design system PTPL & prompt laporan custom) ikut terbawa karena berada di dalam paket.
    packages = ["./library_agent"]
    display_name = os.getenv("LIB_AGENT_DISPLAY_NAME", "marketing-insight-assistant")

    env_vars = {k: v for k, v in os.environ.items() if k.startswith("LIB_") and v}
    env_vars["GOOGLE_GENAI_USE_VERTEXAI"] = "TRUE"

    app = AdkApp(agent=root_agent, enable_tracing=True)
    with open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8") as fh:
        requirements = [line.strip() for line in fh if line.strip() and not line.startswith("#")]

    common = dict(requirements=requirements, extra_packages=packages, env_vars=env_vars, display_name=display_name)
    if args.update:
        remote = agent_engines.update(resource_name=args.update, agent_engine=app, **common)
    else:
        remote = agent_engines.create(agent_engine=app, **common)
    print("Resource name:", remote.resource_name)


if __name__ == "__main__":
    main()
