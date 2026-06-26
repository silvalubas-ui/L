"""Configuração central, lida de variáveis de ambiente."""
import os
from zoneinfo import ZoneInfo

# Banco SQLite — em container fica num volume montado em /data
DB_PATH = os.getenv("LURI_DB_PATH", "/data/luri.db")

# Fuso da clínica
TZ = ZoneInfo(os.getenv("LURI_TZ", "America/Sao_Paulo"))

# Anthropic / Claude
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-8")
USE_REAL_LLM = bool(ANTHROPIC_API_KEY)

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
