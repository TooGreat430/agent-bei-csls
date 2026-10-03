"""Research sub-agent: perpustakaan, dokumen aktif, tanya-jawab bersitasi, insight."""
from google.adk.agents import LlmAgent

from ..callbacks import capture_uploads
from ..config import settings
from ..llm import make_model
from ..prompts import RESEARCH_INSTRUCTION
from ..tools.data_tools import ask_marketing_intelligence
from ..tools.library_tools import RESEARCH_TOOLS

research_agent = LlmAgent(
    name="research_agent",
    model=make_model(settings.model_pro),
    description=(
        "Mengelola perpustakaan dokumen (katalog yang selalu disamakan dengan folder ge-docs-datastore, unggah dokumen), memilih dokumen aktif, "
        "menjawab pertanyaan hanya dari dokumen aktif dengan sitasi, dan menyimpan insight."
    ),
    instruction=RESEARCH_INSTRUCTION,
    tools=[*RESEARCH_TOOLS, ask_marketing_intelligence],
    before_agent_callback=capture_uploads,
    disallow_transfer_to_parent=True,
)
