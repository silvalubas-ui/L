"""Configuração central, lida de variáveis de ambiente."""
import os
from zoneinfo import ZoneInfo

# Banco SQLite — em container fica num volume montado em /data
DB_PATH = os.getenv("LURI_DB_PATH", "/data/luri.db")

# Fuso da clínica
TZ = ZoneInfo(os.getenv("LURI_TZ", "America/Sao_Paulo"))

# --------------------------------------------------------------------------- #
# Provedor de IA (plugável)
#   - ollama   : local, grátis, sem chave (dev). API compatível com OpenAI.
#   - gemini   : Google, via endpoint compatível com OpenAI. Precisa GEMINI_API_KEY.
#   - openai   : OpenAI ou qualquer endpoint compatível.
#   - anthropic: Claude (SDK oficial). Precisa ANTHROPIC_API_KEY.
#   - (vazio)  : auto -> anthropic se houver ANTHROPIC_API_KEY, senão ollama.
# --------------------------------------------------------------------------- #
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-8")

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")

GEMINI_BASE_URL = os.getenv(
    "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"
)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def _detectar_provedor() -> str:
    p = os.getenv("LLM_PROVIDER", "").strip().lower()
    if p:
        return p
    return "anthropic" if ANTHROPIC_API_KEY else "ollama"


LLM_PROVIDER = _detectar_provedor()

# Provedores que falam o protocolo OpenAI (mesmo loop de tool-use)
_OPENAI_COMPAT = {"ollama", "gemini", "openai"}
USE_REAL_LLM = LLM_PROVIDER in ({"anthropic"} | _OPENAI_COMPAT)


def openai_compat_settings() -> dict:
    """base_url / api_key / model do provedor compatível com OpenAI ativo."""
    if LLM_PROVIDER == "gemini":
        return {"base_url": GEMINI_BASE_URL, "api_key": GEMINI_API_KEY or "missing",
                "model": GEMINI_MODEL}
    if LLM_PROVIDER == "openai":
        return {"base_url": OPENAI_BASE_URL, "api_key": OPENAI_API_KEY or "missing",
                "model": OPENAI_MODEL}
    # ollama (padrão): a chave é ignorada pelo servidor local
    return {"base_url": OLLAMA_BASE_URL, "api_key": "ollama", "model": OLLAMA_MODEL}


def modelo_ativo() -> str:
    if LLM_PROVIDER == "anthropic":
        return ANTHROPIC_MODEL
    if LLM_PROVIDER in _OPENAI_COMPAT:
        return openai_compat_settings()["model"]
    return "fallback"

# Identidade do agente
CLINIC_NAME = os.getenv("LURI_CLINIC_NAME", "Clínica Odontológica Sorriso")
AGENT_NAME = os.getenv("LURI_AGENT_NAME", "Lúri")

# Horário de funcionamento (segunda a sexta)
OPEN_HOUR = int(os.getenv("LURI_OPEN_HOUR", "9"))      # 09:00
LUNCH_START = int(os.getenv("LURI_LUNCH_START", "12"))  # fecha 12:00
LUNCH_END = int(os.getenv("LURI_LUNCH_END", "14"))      # reabre 14:00
CLOSE_HOUR = int(os.getenv("LURI_CLOSE_HOUR", "18"))    # 18:00
SLOT_MINUTES = 60                                       # consultas de 1h

# Regras dos agentes de notificação
REMINDER_LEAD_HOURS = int(os.getenv("LURI_REMINDER_LEAD_HOURS", "24"))
NOSHOW_GRACE_MINUTES = int(os.getenv("LURI_NOSHOW_GRACE_MINUTES", "30"))
SCHEDULER_INTERVAL_SECONDS = int(os.getenv("LURI_SCHEDULER_INTERVAL_SECONDS", "60"))
