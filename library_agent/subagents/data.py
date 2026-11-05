"""Data sub-agent: pertanyaan data BigQuery lewat Data Agent Retail, Industry, dan Planogram Marketing Intelligence."""
from google.adk.agents import LlmAgent

from ..callbacks import capture_uploads, sanitize_request, data_after_agent, verify_numbers
from ..config import settings
from ..llm import make_model
from ..prompts import DATA_INSTRUCTION, with_agent_name
from ..tools.data_tools import DATA_TOOLS
from ..tools.file_tools import periksa_angka
from ..tools.insight_tools import list_insights

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
    tools=[*DATA_TOOLS, list_insights, periksa_angka],
    before_agent_callback=capture_uploads,
    before_model_callback=sanitize_request,
    after_model_callback=verify_numbers,
    after_agent_callback=data_after_agent,
    disallow_transfer_to_parent=True,
)
