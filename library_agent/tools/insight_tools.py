"""Tool insight: temuan yang disimpan di DALAM CHAT ini (bahan laporan di chat yang sama)."""
from __future__ import annotations

from typing import Any

from google.adk.tools import ToolContext

from .. import insights


def list_insights(tool_context: ToolContext) -> dict[str, Any]:
    """Menampilkan insight yang sudah disimpan di chat ini."""
    return {"status": "ok", "insights": insights.list_for(tool_context.state)}


def update_insight(insight_id: str, tool_context: ToolContext, title: str = "", content: str = "") -> dict[str, Any]:
    """Mengubah judul dan/atau isi insight di chat ini.

    Args:
        insight_id: ID insight.
        title: Judul baru (kosongkan jika tidak diubah).
        content: Isi baru (kosongkan jika tidak diubah).
    """
    return insights.update(tool_context.state, insight_id, title or None, content or None)


def delete_insight(insight_id: str, tool_context: ToolContext) -> dict[str, Any]:
    """Menghapus insight dari chat ini.

    Args:
        insight_id: ID insight.
    """
    return insights.delete(tool_context.state, insight_id)


INSIGHT_TOOLS = [list_insights, update_insight, delete_insight]
