"""Research sub-agent: perpustakaan, dokumen aktif, tanya-jawab bersitasi, insight."""
from google.adk.agents import LlmAgent

from ..callbacks import capture_uploads
from ..config import settings
from ..prompts import RESEARCH_INSTRUCTION
from ..tools.library_tools import RESEARCH_TOOLS

research_agent = LlmAgent(
    name="research_agent",
    model=settings.model_pro,
    description=(
        "Mengelola perpustakaan dokumen (katalog, unggah dokumen), memilih dokumen aktif, "
        "menjawab pertanyaan hanya dari dokumen aktif dengan sitasi, dan menyimpan insight."
    ),
    instruction=RESEARCH_INSTRUCTION,
    tools=RESEARCH_TOOLS,
    before_agent_callback=capture_uploads,
)
