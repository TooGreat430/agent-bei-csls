"""File sub-agent: analisis file CSV/Excel unggahan user (dihitung oleh kode, bukan oleh model).

Langkah pertama untuk setiap file: kenali jenis data dan serap pengetahuan resmi Data Agent domain tersebut.
"""
from google.adk.agents import LlmAgent

from ..callbacks import capture_uploads, sanitize_request, data_after_agent, verify_numbers
from ..config import settings
from ..llm import make_heavy_model, make_model
from ..usage import budget_guard, budget_notice, chain, chain_before, record_model_usage
from ..prompts import file_instruction_provider
from ..tools.data_tools import (ask_industry_intelligence, ask_planogram_intelligence, ask_retail_intelligence,
                                create_chart, save_data_insight)
from ..tools.code_tools import CODE_TOOLS
from ..tools.doc_tools import DOC_TOOLS
from ..tools.export_tools import EXPORT_TOOLS
from ..tools.report_tools import (approve_report, generate_battlefield_report, generate_custom_report,
                                  generate_industry_report, generate_planogram_report, generate_price_dashboard,
                                  konversi_laporan_custom, list_report_options, revise_custom_report)
from ..tools.file_tools import FILE_TOOLS
from ..tools.insight_tools import list_insights

file_agent = LlmAgent(
    name="file_agent",
    model=make_heavy_model(),
    description=(
        "Menangani SEMUA file unggahan: dokumen (PDF, Word, PowerPoint, teks, HTML, gambar) dicerna lalu diringkas "
        "beserta usulan langkah berikutnya; file data CSV/Excel (survei retail, industri, planogram, atau umum) "
        "dianalisis setelah menyerap pengetahuan Data Agent yang sesuai: profil, cross-tab, gabung file, grafik, insight."
    ),
    instruction=file_instruction_provider,
    tools=[*FILE_TOOLS, *DOC_TOOLS, *EXPORT_TOOLS, *CODE_TOOLS,
           # laporan langsung dari hasil analisis file (tanpa harus pindah agent): base template PTPL, ditulis Argon
           list_report_options, generate_custom_report, revise_custom_report, approve_report, konversi_laporan_custom,
           generate_price_dashboard, generate_industry_report, generate_planogram_report, generate_battlefield_report, create_chart, save_data_insight, ask_retail_intelligence, ask_industry_intelligence,
           ask_planogram_intelligence, list_insights],
    before_agent_callback=capture_uploads,
    before_model_callback=chain_before(budget_guard, sanitize_request),
    after_model_callback=chain(record_model_usage, verify_numbers, budget_notice),
    after_agent_callback=data_after_agent,
    disallow_transfer_to_parent=True,
)
