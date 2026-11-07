"""Root agent yang didaftarkan ke Gemini Enterprise ("Marketing Insight Assistant").

User hanya melihat satu agent (satu chat). Root agent meneruskan permintaan ke data_agent (BigQuery lewat
Data Agent Retail/Industry/Planogram), file_agent (analisis CSV/Excel), atau report_agent (laporan template
dan custom) di balik layar.
"""
import logging

from google.adk.agents import LlmAgent

from .callbacks import capture_uploads, sanitize_request, ensure_reply
from .config import settings
from .llm import make_model
from .usage import budget_guard, budget_notice, chain, chain_before, record_model_usage
from .prompts import ROOT_INSTRUCTION, with_agent_name
from .subagents.data import data_agent
from .subagents.files import file_agent
from .subagents.report import report_agent

logging.basicConfig(level=logging.INFO)

root_agent = LlmAgent(
    name="marketing_insight_assistant",
    model=make_model(settings.model_fast),
    description=("Marketing Insight Assistant: data pasar BigQuery (Retail, Industry, Planogram Marketing Intelligence, "
                 "analisis silang Retail × Planogram), membaca file unggahan (data & dokumen), insight, dan laporan "
                 "template/custom PDF/PPT/HTML."),
    instruction=with_agent_name(ROOT_INSTRUCTION),
    sub_agents=[data_agent, file_agent, report_agent],
    before_agent_callback=capture_uploads,
    before_model_callback=chain_before(budget_guard, sanitize_request),
    after_model_callback=chain(record_model_usage, budget_notice),
    after_agent_callback=ensure_reply,
)
