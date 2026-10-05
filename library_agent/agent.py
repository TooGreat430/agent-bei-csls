"""Root agent yang didaftarkan ke Gemini Enterprise.

User hanya melihat satu agent (satu chat). Root agent meneruskan permintaan ke
research_agent atau report_agent di balik layar.
"""
import logging

from google.adk.agents import LlmAgent

from .callbacks import capture_uploads
from .config import settings
from .llm import make_model
from .prompts import ROOT_INSTRUCTION, with_agent_name
from .subagents.data import data_agent
from .subagents.report import report_agent
from .subagents.research import research_agent

logging.basicConfig(level=logging.INFO)

root_agent = LlmAgent(
    name="marketing_insight_assistant",
    model=make_model(settings.model_fast),
    description="Marketing Insight Assistant, agent serba bisa: perpustakaan dokumen BEI/CSLS, data pasar BigQuery (Marketing Intelligence), insight, dan laporan PDF/PPT/HTML dari template.",
    instruction=with_agent_name(ROOT_INSTRUCTION),
    sub_agents=[research_agent, data_agent, report_agent],
    before_agent_callback=capture_uploads,
)
