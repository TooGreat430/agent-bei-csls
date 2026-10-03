"""Data sub-agent: pertanyaan data BigQuery lewat Data Agent Marketing Intelligence."""
from google.adk.agents import LlmAgent

from ..callbacks import capture_uploads
from ..config import settings
from ..llm import make_model
from ..prompts import DATA_INSTRUCTION
from ..tools.data_tools import DATA_TOOLS
from ..tools.library_tools import (get_active_documents, list_insights, save_insight, search_active_documents,
                                   set_workspace)

data_agent = LlmAgent(
    name="data_agent",
    model=make_model(settings.model_fast),
    description=(
        "Menjawab pertanyaan data pasar dari BigQuery (survei retail: harga jual/tebus, HET, HTO, gap harga, margin, "
        "TOV, Product Hero, kompetitor, zona/region, segmen, tren) lewat Data Agent Marketing Intelligence, "
        "dan menyimpan jawabannya sebagai insight."
    ),
    instruction=DATA_INSTRUCTION,
    tools=[*DATA_TOOLS, set_workspace, list_insights, save_insight, get_active_documents, search_active_documents],
    before_agent_callback=capture_uploads,
    disallow_transfer_to_parent=True,
)
