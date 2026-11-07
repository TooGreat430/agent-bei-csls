"""Report sub-agent: laporan TEMPLATE (retail, industri, planogram) dan CUSTOM (prompt MIR + model utama)."""
from google.adk.agents import LlmAgent

from ..callbacks import capture_uploads, sanitize_request, ensure_reply
from ..config import settings
from ..llm import make_model
from ..usage import budget_guard, budget_notice, chain, chain_before, record_model_usage
from ..prompts import REPORT_INSTRUCTION, with_agent_name
from ..tools.doc_tools import DOC_TOOLS
from ..tools.export_tools import EXPORT_TOOLS
from ..tools.file_tools import list_data_files
from ..tools.insight_tools import list_insights
from ..tools.report_tools import REPORT_TOOLS

report_agent = LlmAgent(
    name="report_agent",
    model=make_model(settings.model_pro),
    description=(
        "Membuat laporan: TEMPLATE (Daya Saing Harga Retail, Daya Saing Harga Industri B2B, Kinerja Planogram PTPL vs "
        "Kompetitor, Competitive Battlefield Retail × Planogram) dalam PDF/PowerPoint/HTML, atau CUSTOM (sesuai permintaan, "
        "termasuk gabungan Retail × Planogram dan mengikuti dokumen prompt/template unggahan, HTML, DRAFT sampai "
        "disetujui); termasuk contoh tampilan, revisi, dan approval laporan."
    ),
    instruction=with_agent_name(REPORT_INSTRUCTION, uploads=True),
    tools=[*REPORT_TOOLS, list_insights, list_data_files, *DOC_TOOLS, *EXPORT_TOOLS],
    before_agent_callback=capture_uploads,
    before_model_callback=chain_before(budget_guard, sanitize_request),
    after_model_callback=chain(record_model_usage, budget_notice),
    after_agent_callback=ensure_reply,
    disallow_transfer_to_parent=True,
)
