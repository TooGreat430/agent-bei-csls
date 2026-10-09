"""File sub-agent: analisis file CSV/Excel unggahan user (dihitung oleh kode, bukan oleh model)."""
from google.adk.agents import LlmAgent

from ..callbacks import capture_uploads, data_after_agent, verify_numbers
from ..config import settings
from ..llm import make_model
from ..prompts import file_instruction_provider
from ..tools.data_tools import ask_marketing_intelligence, create_chart, save_data_insight
from ..tools.file_tools import FILE_TOOLS
from ..tools.library_tools import list_insights

file_agent = LlmAgent(
    name="file_agent",
    model=make_model(settings.model_pro),
    description=(
        "Menganalisis file data CSV/Excel yang diunggah user (format survei retail, survei industri, atau umum): "
        "profil data, cross-tab, gabung beberapa file, perbandingan dengan data BigQuery jika diminta, grafik, "
        "dan menyimpan hasil sebagai insight."
    ),
    instruction=file_instruction_provider,
    tools=[*FILE_TOOLS, create_chart, save_data_insight, ask_marketing_intelligence, list_insights],
    before_agent_callback=capture_uploads,
    after_model_callback=verify_numbers,
    after_agent_callback=data_after_agent,
    disallow_transfer_to_parent=True,
)
