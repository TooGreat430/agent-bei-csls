"""Report sub-agent: membuat laporan dashboard daya saing harga (data BigQuery)."""
from google.adk.agents import LlmAgent

from ..callbacks import capture_uploads, ensure_reply
from ..config import settings
from ..llm import make_model
from ..prompts import REPORT_INSTRUCTION, with_agent_name
from ..tools.file_tools import list_data_files
from ..tools.library_tools import list_insights
from ..tools.report_tools import REPORT_TOOLS

report_agent = LlmAgent(
    name="report_agent",
    model=make_model(settings.model_fast),
    description=(
        "Membuat laporan dashboard daya saing harga retail (data BigQuery) dalam PDF, PowerPoint, atau HTML, "
        "termasuk contoh tampilannya."
    ),
    instruction=with_agent_name(REPORT_INSTRUCTION),
    tools=[*REPORT_TOOLS, list_insights, list_data_files],
    before_agent_callback=capture_uploads,
    after_agent_callback=ensure_reply,
    disallow_transfer_to_parent=True,
)
