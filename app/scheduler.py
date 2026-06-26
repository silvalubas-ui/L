"""Agentes de notificação: lembrete 24h antes e follow-up de no-show.

Rodam periodicamente (APScheduler). As mensagens são "enviadas" para a tabela
mensagens_enviadas — simulando uma integração com WhatsApp/SMS.
"""
import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from . import config, db

logger = logging.getLogger("luri.scheduler")


def _fmt(data_hora_iso: str) -> str:
    return datetime.fromisoformat(data_hora_iso).strftime("%d/%m/%Y às %H:%M")


def enviar_lembretes() -> None:
    for c in db.consultas_para_lembrete():
        texto = (
            f"Olá, {c['nome']}! Lembrete da {config.CLINIC_NAME}: você tem "
            f"{c['procedimento']} marcada para {_fmt(c['data_hora'])}. "
            "Responda CONFIRMO para confirmar ou REMARCAR se precisar mudar."
        )
        db.registrar_mensagem(c["telefone"], "lembrete", texto, c["id"])
        db.marcar_lembrete_enviado(c["id"])
        logger.info("Lembrete enviado para consulta #%s (%s)", c["id"], c["nome"])


def enviar_followup_noshow() -> None:
    for c in db.consultas_para_followup():
        texto = (
            f"Olá, {c['nome']}. Sentimos sua falta na consulta de "
            f"{_fmt(c['data_hora'])} ({c['procedimento']}). "
            "Quer remarcar? É só responder esta mensagem que encontramos um novo horário."
        )
        db.registrar_mensagem(c["telefone"], "no_show", texto, c["id"])
        db.marcar_falta_e_followup(c["id"])
        logger.info("Follow-up de no-show enviado para consulta #%s (%s)", c["id"], c["nome"])


def _ciclo() -> None:
    try:
        enviar_lembretes()
        enviar_followup_noshow()
    except Exception:  # noqa: BLE001 — agendador nunca pode morrer por um erro de ciclo
        logger.exception("Erro no ciclo do agendador")


def iniciar() -> BackgroundScheduler:
    sched = BackgroundScheduler(timezone=str(config.TZ))
    sched.add_job(
        _ciclo,
        "interval",
        seconds=config.SCHEDULER_INTERVAL_SECONDS,
        id="ciclo_notificacoes",
        next_run_time=datetime.now(config.TZ),  # roda uma vez logo no start
    )
    sched.start()
    logger.info("Agendador iniciado (intervalo: %ss)", config.SCHEDULER_INTERVAL_SECONDS)
    return sched
