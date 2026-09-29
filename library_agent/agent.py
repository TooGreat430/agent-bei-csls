"""Root agent yang didaftarkan ke Gemini Enterprise.

User hanya melihat satu agent (satu chat). Root agent meneruskan permintaan ke
research_agent atau report_agent di balik layar.
"""
import logging

from google.adk.agents import LlmAgent

from .callbacks import capture_uploads
from .config import settings
from .prompts import ROOT_INSTRUCTION
from .subagents.report import report_agent
from .subagents.research import research_agent

logging.basicConfig(level=logging.INFO)

root_agent = LlmAgent(
    name="asisten_perpustakaan",
    model=settings.model_fast,
    description="Perpustakaan dokumen BEI/CSLS: unggah, pilih dokumen, diskusi bersitasi, insight, dan laporan dari template.",
    instruction=ROOT_INSTRUCTION,
    sub_agents=[research_agent, report_agent],
    before_agent_callback=capture_uploads,
)
