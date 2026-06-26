"""Camada de persistência (SQLite) e regras de agenda da clínica."""
import json
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

from . import config

_STATUS_ATIVOS = ("agendada", "remarcada")


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(config.DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS consultas (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                nome            TEXT NOT NULL,
                telefone        TEXT NOT NULL,
                data_hora       TEXT NOT NULL,         -- ISO 8601 (com fuso)
                procedimento    TEXT NOT NULL,
                status          TEXT NOT NULL DEFAULT 'agendada',
                lembrete_enviado INTEGER NOT NULL DEFAULT 0,
                followup_enviado INTEGER NOT NULL DEFAULT 0,
                criado_em       TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS mensagens_enviadas (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                telefone    TEXT NOT NULL,
                tipo        TEXT NOT NULL,             -- lembrete | no_show
                texto       TEXT NOT NULL,
                consulta_id INTEGER,
                criado_em   TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS conversas (
                sessao    TEXT PRIMARY KEY,
                historico TEXT NOT NULL,               -- JSON: lista de mensagens da API
                criado_em TEXT NOT NULL,
                atualizado_em TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS atendimentos_humanos (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                sessao    TEXT,
                telefone  TEXT,
                motivo    TEXT NOT NULL,
                status    TEXT NOT NULL DEFAULT 'pendente',
                criado_em TEXT NOT NULL
            );
            """
        )


def _agora() -> datetime:
    return datetime.now(config.TZ)


# --------------------------------------------------------------------------- #
# Agenda / horários
# --------------------------------------------------------------------------- #
def _slots_do_dia(dia: datetime) -> list[datetime]:
    """Todos os horários teóricos de um dia útil (sem considerar ocupação)."""
    if dia.weekday() >= 5:  # sábado/domingo
        return []
    slots: list[datetime] = []
    for hora in range(config.OPEN_HOUR, config.CLOSE_HOUR):
        if config.LUNCH_START <= hora < config.LUNCH_END:
            continue
        slots.append(dia.replace(hour=hora, minute=0, second=0, microsecond=0))
    return slots


def horarios_disponiveis(data_iso: str) -> dict:
    """Retorna os horários livres para uma data (YYYY-MM-DD)."""
    try:
        dia = datetime.fromisoformat(data_iso).replace(tzinfo=config.TZ)
    except ValueError:
        return {"erro": "Data inválida. Use o formato AAAA-MM-DD."}

    todos = _slots_do_dia(dia)
    if not todos:
        return {
            "data": data_iso,
            "disponiveis": [],
            "mensagem": "A clínica não atende nesse dia (fim de semana).",
        }

    ocupados = _horarios_ocupados(dia)
    agora = _agora()
    livres = [
        s.strftime("%H:%M")
        for s in todos
        if s.isoformat() not in ocupados and s > agora
    ]
    return {"data": data_iso, "disponiveis": livres}


def _horarios_ocupados(dia: datetime) -> set[str]:
    inicio = dia.replace(hour=0, minute=0, second=0, microsecond=0)
    fim = inicio + timedelta(days=1)
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT data_hora FROM consultas
            WHERE status IN ('agendada', 'remarcada')
              AND data_hora >= ? AND data_hora < ?
            """,
            (inicio.isoformat(), fim.isoformat()),
        ).fetchall()
    return {r["data_hora"] for r in rows}


def _parse_data_hora(valor: str) -> Optional[datetime]:
    """Aceita 'AAAA-MM-DD HH:MM' ou ISO; devolve datetime com fuso da clínica."""
    valor = valor.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(valor, fmt).replace(tzinfo=config.TZ)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(valor)
        return dt if dt.tzinfo else dt.replace(tzinfo=config.TZ)
    except ValueError:
        return None


def _slot_valido(dt: datetime) -> Optional[str]:
    """Valida se o horário cai dentro do expediente. Retorna msg de erro ou None."""
    if dt <= _agora():
        return "Esse horário já passou. Escolha uma data futura."
    if dt.weekday() >= 5:
        return "A clínica não atende aos fins de semana."
    if dt.minute != 0:
        return "As consultas começam sempre na hora cheia (ex.: 09:00, 14:00)."
    hora = dt.hour
    aberto = config.OPEN_HOUR <= hora < config.CLOSE_HOUR
    almoco = config.LUNCH_START <= hora < config.LUNCH_END
    if not aberto or almoco:
        return (
            f"Fora do horário de atendimento "
            f"({config.OPEN_HOUR:02d}h–{config.LUNCH_START:02d}h e "
            f"{config.LUNCH_END:02d}h–{config.CLOSE_HOUR:02d}h, dias úteis)."
        )
    return None


# --------------------------------------------------------------------------- #
# CRUD de consultas (usado pelas ferramentas do agente)
# --------------------------------------------------------------------------- #
def agendar(nome: str, telefone: str, data_hora: str, procedimento: str) -> dict:
    dt = _parse_data_hora(data_hora)
    if dt is None:
        return {"ok": False, "erro": "Não entendi a data/hora. Use 'AAAA-MM-DD HH:MM'."}
    if (erro := _slot_valido(dt)) is not None:
        return {"ok": False, "erro": erro}

    with _connect() as conn:
        ja_ocupado = conn.execute(
            "SELECT id FROM consultas WHERE data_hora = ? AND status IN ('agendada','remarcada')",
            (dt.isoformat(),),
        ).fetchone()
        if ja_ocupado:
            return {"ok": False, "erro": "Esse horário acabou de ser ocupado. Escolha outro."}

        cur = conn.execute(
            """
            INSERT INTO consultas (nome, telefone, data_hora, procedimento, status, criado_em)
            VALUES (?, ?, ?, ?, 'agendada', ?)
            """,
            (nome.strip(), telefone.strip(), dt.isoformat(), procedimento.strip(),
             _agora().isoformat()),
        )
        cid = cur.lastrowid
    return {
        "ok": True,
        "consulta": {
            "id": cid,
            "nome": nome.strip(),
            "data_hora": dt.strftime("%d/%m/%Y às %H:%M"),
            "procedimento": procedimento.strip(),
        },
    }


def remarcar(consulta_id: int, nova_data_hora: str) -> dict:
    dt = _parse_data_hora(nova_data_hora)
    if dt is None:
        return {"ok": False, "erro": "Não entendi a nova data/hora."}
    if (erro := _slot_valido(dt)) is not None:
        return {"ok": False, "erro": erro}

    with _connect() as conn:
        consulta = conn.execute(
            "SELECT * FROM consultas WHERE id = ?", (consulta_id,)
        ).fetchone()
        if consulta is None:
            return {"ok": False, "erro": f"Consulta #{consulta_id} não encontrada."}
        if consulta["status"] not in _STATUS_ATIVOS:
            return {"ok": False, "erro": "Essa consulta não está ativa (já cancelada ou concluída)."}

        ocupado = conn.execute(
            """SELECT id FROM consultas
               WHERE data_hora = ? AND status IN ('agendada','remarcada') AND id != ?""",
            (dt.isoformat(), consulta_id),
        ).fetchone()
        if ocupado:
            return {"ok": False, "erro": "O novo horário já está ocupado."}

        conn.execute(
            """UPDATE consultas
               SET data_hora = ?, status = 'remarcada', lembrete_enviado = 0, followup_enviado = 0
               WHERE id = ?""",
            (dt.isoformat(), consulta_id),
        )
    return {
        "ok": True,
        "consulta": {"id": consulta_id, "data_hora": dt.strftime("%d/%m/%Y às %H:%M")},
    }


def cancelar(consulta_id: int) -> dict:
    with _connect() as conn:
        consulta = conn.execute(
            "SELECT * FROM consultas WHERE id = ?", (consulta_id,)
        ).fetchone()
        if consulta is None:
            return {"ok": False, "erro": f"Consulta #{consulta_id} não encontrada."}
        if consulta["status"] not in _STATUS_ATIVOS:
            return {"ok": False, "erro": "Essa consulta já não está ativa."}
        conn.execute(
            "UPDATE consultas SET status = 'cancelada' WHERE id = ?", (consulta_id,)
        )
    return {"ok": True, "consulta_id": consulta_id}


def buscar_por_telefone(telefone: str) -> dict:
    with _connect() as conn:
        rows = conn.execute(
            """SELECT id, nome, data_hora, procedimento, status FROM consultas
               WHERE telefone = ? ORDER BY data_hora""",
            (telefone.strip(),),
        ).fetchall()
    consultas = [
        {
            "id": r["id"],
            "nome": r["nome"],
            "data_hora": datetime.fromisoformat(r["data_hora"]).strftime("%d/%m/%Y às %H:%M"),
            "procedimento": r["procedimento"],
            "status": r["status"],
        }
        for r in rows
    ]
    return {"telefone": telefone.strip(), "consultas": consultas}


# --------------------------------------------------------------------------- #
# Mensagens enviadas (simulação de WhatsApp/SMS) + uso pelo agendador
# --------------------------------------------------------------------------- #
def registrar_mensagem(telefone: str, tipo: str, texto: str, consulta_id: int) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO mensagens_enviadas (telefone, tipo, texto, consulta_id, criado_em)
               VALUES (?, ?, ?, ?, ?)""",
            (telefone, tipo, texto, consulta_id, _agora().isoformat()),
        )


def listar_mensagens(limite: int = 50) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM mensagens_enviadas ORDER BY id DESC LIMIT ?", (limite,)
        ).fetchall()
    return [
        {
            "id": r["id"],
            "telefone": r["telefone"],
            "tipo": r["tipo"],
            "texto": r["texto"],
            "criado_em": datetime.fromisoformat(r["criado_em"]).strftime("%d/%m %H:%M"),
        }
        for r in rows
    ]


def consultas_para_lembrete() -> list[sqlite3.Row]:
    agora = _agora()
    limite = agora + timedelta(hours=config.REMINDER_LEAD_HOURS)
    with _connect() as conn:
        return conn.execute(
            """SELECT * FROM consultas
               WHERE status IN ('agendada','remarcada')
                 AND lembrete_enviado = 0
                 AND data_hora > ? AND data_hora <= ?""",
            (agora.isoformat(), limite.isoformat()),
        ).fetchall()


def consultas_para_followup() -> list[sqlite3.Row]:
    corte = _agora() - timedelta(minutes=config.NOSHOW_GRACE_MINUTES)
    with _connect() as conn:
        return conn.execute(
            """SELECT * FROM consultas
               WHERE status IN ('agendada','remarcada')
                 AND followup_enviado = 0
                 AND data_hora < ?""",
            (corte.isoformat(),),
        ).fetchall()


def marcar_lembrete_enviado(consulta_id: int) -> None:
    with _connect() as conn:
        conn.execute("UPDATE consultas SET lembrete_enviado = 1 WHERE id = ?", (consulta_id,))


def marcar_falta_e_followup(consulta_id: int) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE consultas SET status = 'falta', followup_enviado = 1 WHERE id = ?",
            (consulta_id,),
        )


# --------------------------------------------------------------------------- #
# Encaminhamento para atendente humano (handoff)
# --------------------------------------------------------------------------- #
def encaminhar_atendente(motivo: str, telefone: str = "", sessao: str = "") -> dict:
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO atendimentos_humanos (sessao, telefone, motivo, status, criado_em)
               VALUES (?, ?, ?, 'pendente', ?)""",
            (sessao or None, (telefone or "").strip() or None, motivo.strip(), _agora().isoformat()),
        )
    return {"ok": True, "protocolo": cur.lastrowid}


def listar_atendimentos(limite: int = 50) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM atendimentos_humanos ORDER BY id DESC LIMIT ?", (limite,)
        ).fetchall()
    return [
        {
            "id": r["id"],
            "telefone": r["telefone"] or "—",
            "motivo": r["motivo"],
            "status": r["status"],
            "criado_em": datetime.fromisoformat(r["criado_em"]).strftime("%d/%m %H:%M"),
        }
        for r in rows
    ]


# --------------------------------------------------------------------------- #
# Histórico de conversa (para o agente Claude manter contexto)
# --------------------------------------------------------------------------- #
def carregar_historico(sessao: str) -> list:
    with _connect() as conn:
        row = conn.execute(
            "SELECT historico FROM conversas WHERE sessao = ?", (sessao,)
        ).fetchone()
    return json.loads(row["historico"]) if row else []


def salvar_historico(sessao: str, historico: list) -> None:
    agora = _agora().isoformat()
    with _connect() as conn:
        conn.execute(
            """INSERT INTO conversas (sessao, historico, criado_em, atualizado_em)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(sessao) DO UPDATE SET historico = excluded.historico,
                                                 atualizado_em = excluded.atualizado_em""",
            (sessao, json.dumps(historico, ensure_ascii=False), agora, agora),
        )


# --------------------------------------------------------------------------- #
# Seed de demonstração
# --------------------------------------------------------------------------- #
def seed_demo() -> dict:
    """Cria consultas para exercitar lembrete (24h) e no-show (passado)."""
    agora = _agora()

    # Consulta dentro da janela de 24h -> dispara o agente de lembrete no próximo ciclo
    lembrete_dt = (agora + timedelta(hours=23)).replace(minute=0, second=0, microsecond=0)
    # Consulta no passado, sem comparecimento -> dispara o agente de no-show
    noshow_dt = (agora - timedelta(hours=2)).replace(minute=0, second=0, microsecond=0)

    criadas = []
    with _connect() as conn:
        for nome, tel, dt, proc in [
            ("Ana Paula", "+5511990001111", lembrete_dt, "Limpeza"),
            ("Carlos Mendes", "+5511990002222", noshow_dt, "Avaliação"),
        ]:
            cur = conn.execute(
                """INSERT INTO consultas (nome, telefone, data_hora, procedimento, status, criado_em)
                   VALUES (?, ?, ?, ?, 'agendada', ?)""",
                (nome, tel, dt.isoformat(), proc, agora.isoformat()),
            )
            criadas.append({"id": cur.lastrowid, "nome": nome,
                            "data_hora": dt.strftime("%d/%m %H:%M"), "procedimento": proc})
    return {"ok": True, "criadas": criadas}
