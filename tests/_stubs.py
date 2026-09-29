"""Stub minimal untuk menjalankan uji unit tanpa google-adk / google-genai terpasang.

Jika library aslinya terpasang, stub tidak dipakai.
"""
import sys
import types as _t


def _install_api_core() -> None:
    try:
        import google.api_core.exceptions  # noqa: F401
        return
    except ImportError:
        pass
    import google

    class GoogleAPICallError(Exception):
        pass

    class NotFound(GoogleAPICallError):
        pass

    class PreconditionFailed(GoogleAPICallError):
        pass

    for name in ("google.api_core", "google.api_core.exceptions"):
        sys.modules.setdefault(name, _t.ModuleType(name))
    exc = sys.modules["google.api_core.exceptions"]
    exc.GoogleAPICallError, exc.NotFound, exc.PreconditionFailed = GoogleAPICallError, NotFound, PreconditionFailed
    sys.modules["google.api_core"].exceptions = exc
    google.api_core = sys.modules["google.api_core"]


def install() -> None:
    _install_api_core()
    try:
        import google.adk  # noqa: F401
        import google.genai  # noqa: F401
        return
    except ImportError:
        pass

    class _Any:
        def __init__(self, *args, **kwargs):
            self.__dict__.update(kwargs)

    def mod(name, **attrs):
        m = sys.modules.get(name) or _t.ModuleType(name)
        m.__dict__.update(attrs)
        sys.modules[name] = m
        return m

    import google  # namespace package dari google-cloud-* / protobuf

    mod("google.adk")
    mod("google.adk.agents", LlmAgent=_Any)
    mod("google.adk.agents.callback_context", CallbackContext=_Any)
    mod("google.adk.tools", ToolContext=_Any)
    genai = mod("google.genai")
    genai.types = mod("google.genai.types", Content=_Any, Part=_Any, GenerateContentConfig=_Any)
    google.adk = sys.modules["google.adk"]
    google.genai = genai
