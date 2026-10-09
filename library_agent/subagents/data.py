"""Data sub-agent: pertanyaan data BigQuery lewat Data Agent Marketing Intelligence."""
from google.adk.agents import LlmAgent

from ..callbacks import capture_uploads, data_after_agent, verify_numbers
from ..config import settings
from ..llm import make_model
from ..prompts import DATA_INSTRUCTION, with_agent_name
from ..tools.data_tools import DATA_TOOLS
from ..tools.file_tools import periksa_angka
from ..tools.library_tools import get_active_documents, list_insights, search_active_documents

data_agent = LlmAgent(
    name="data_agent",
    model=make_model(settings.model_fast),
    description=(
        "Menjawab pertanyaan data pasar dari BigQuery (survei retail: harga jual/tebus, HET, HTO, gap harga, margin, "
        "TOV, Product Hero, kompetitor, zona/region, segmen, tren) lewat Data Agent Marketing Intelligence, "
        "dan menyimpan jawabannya sebagai insight."
    ),
    instruction=with_agent_name(DATA_INSTRUCTION),
    tools=[*DATA_TOOLS, list_insights, get_active_documents, search_active_documents, periksa_angka],
    before_agent_callback=capture_uploads,
    after_model_callback=verify_numbers,
    after_agent_callback=data_after_agent,
    disallow_transfer_to_parent=True,
)
