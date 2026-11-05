"""File sub-agent: analisis file CSV/Excel unggahan user (dihitung oleh kode, bukan oleh model).

Langkah pertama untuk setiap file: kenali jenis data dan serap pengetahuan resmi Data Agent domain tersebut.
"""
from google.adk.agents import LlmAgent

from ..callbacks import capture_uploads, sanitize_request, data_after_agent, verify_numbers
from ..config import settings
from ..llm import make_model
from ..prompts import file_instruction_provider
from ..tools.data_tools import (ask_industry_intelligence, ask_planogram_intelligence, ask_retail_intelligence,
                                create_chart, save_data_insight)
from ..tools.doc_tools import DOC_TOOLS
from ..tools.file_tools import FILE_TOOLS
from ..tools.insight_tools import list_insights

file_agent = LlmAgent(
    name="file_agent",
    model=make_model(settings.model_pro),
    description=(
        "Menangani SEMUA file unggahan: dokumen (PDF, Word, PowerPoint, teks, HTML, gambar) dicerna lalu diringkas "
        "beserta usulan langkah berikutnya; file data CSV/Excel (survei retail, industri, planogram, atau umum) "
        "dianalisis setelah menyerap pengetahuan Data Agent yang sesuai: profil, cross-tab, gabung file, grafik, insight."
    ),
    instruction=file_instruction_provider,
    tools=[*FILE_TOOLS, *DOC_TOOLS, create_chart, save_data_insight, ask_retail_intelligence, ask_industry_intelligence,
           ask_planogram_intelligence, list_insights],
    before_agent_callback=capture_uploads,
    before_model_callback=sanitize_request,
    after_model_callback=verify_numbers,
    after_agent_callback=data_after_agent,
    disallow_transfer_to_parent=True,
)
