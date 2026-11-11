"""Data sub-agent: pertanyaan data BigQuery lewat Data Agent Retail, Industry, dan Planogram Marketing Intelligence."""
from google.adk.agents import LlmAgent

from ..callbacks import capture_uploads, sanitize_request, data_after_agent, verify_numbers
from ..config import settings
from ..llm import make_model
from ..usage import budget_guard, budget_notice, chain, chain_before, record_model_usage
from ..prompts import DATA_INSTRUCTION, with_agent_name
from ..tools.data_tools import DATA_TOOLS
from ..tools.file_tools import periksa_angka
from ..tools.chart_insight_tools import CHART_INSIGHT_TOOLS
from ..tools.doc_tools import lihat_gambar, list_documents
from ..tools.insight_tools import list_insights
from ..tools.report_tools import (approve_report, generate_battlefield_report, generate_custom_report,
                                  generate_industry_report, generate_planogram_report, generate_price_dashboard,
                                  konversi_laporan_custom, list_report_options, revise_custom_report)

data_agent = LlmAgent(
    name="data_agent",
    model=make_model(settings.model_fast),
    description=(
        "Menjawab pertanyaan data dari BigQuery lewat Data Agent PTPL: survei RETAIL (harga, gap, margin, Product Hero, "
        "KIMAP), survei INDUSTRI/B2B (channel, main stage, HTD, gap %), dan survei PLANOGRAM / rak outlet (outlet carry, "
        "ND, skor availability & visibility, PAIR_KIMAP, sebaran per SR, whitespace), serta ANALISIS SILANG Retail × "
        "Planogram per KIMAP (harga × rak, double jeopardy, white space); menyimpan jawabannya sebagai insight."
    ),
    instruction=with_agent_name(DATA_INSTRUCTION),
    tools=[*DATA_TOOLS, *CHART_INSIGHT_TOOLS, list_insights, periksa_angka, list_documents, lihat_gambar,
           # laporan langsung dari data BigQuery yang sudah ditarik (ditulis Gemini 4 Argon, template PTPL)
           list_report_options, generate_custom_report, revise_custom_report, approve_report, konversi_laporan_custom,
           generate_price_dashboard, generate_industry_report, generate_planogram_report, generate_battlefield_report],
    before_agent_callback=capture_uploads,
    before_model_callback=chain_before(budget_guard, sanitize_request),
    after_model_callback=chain(record_model_usage, verify_numbers, budget_notice),
    after_agent_callback=data_after_agent,
    disallow_transfer_to_parent=True,
)
