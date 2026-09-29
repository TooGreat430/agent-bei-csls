"""Report sub-agent: membuat laporan dari template resmi berdasarkan insight tersimpan."""
from google.adk.agents import LlmAgent

from ..callbacks import capture_uploads
from ..config import settings
from ..prompts import REPORT_INSTRUCTION
from ..tools.library_tools import get_active_documents, list_insights, set_workspace
from ..tools.report_tools import REPORT_TOOLS

report_agent = LlmAgent(
    name="report_agent",
    model=settings.model_fast,
    description=(
        "Membuat laporan resmi dari template perusahaan berdasarkan insight tersimpan, "
        "lalu mengirim link laporan HTML/PDF."
    ),
    instruction=REPORT_INSTRUCTION,
    tools=[*REPORT_TOOLS, list_insights, set_workspace, get_active_documents],
    before_agent_callback=capture_uploads,
)
