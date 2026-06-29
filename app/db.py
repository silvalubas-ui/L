"""Camada de persistência — Supabase (primário) ou SQLite (fallback).

Se SUPABASE_URL e SUPABASE_SERVICE_KEY estiverem no .env, usa Supabase.
Caso contrário, cai no SQLite original — nenhuma outra parte do código muda.
"""
import json
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

from . import config

_STATUS_ATIVOS = ("agendada", "remarcada")


# --------------------------------------------------------------------------- #
# Inicialização do cliente Supabase (só se configurado)
# --------------------------------------------------------------------------- #
if config.USE_SUPABASE:
    from supabase import create_client, Client as SupabaseClient
    _sb: SupabaseClient = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)
else:
    _sb = None  # type: ignore


# --------------------------------------------------------------------------- #
# Helpers SQLite (fallback)
# --------------------------------------------------------------------------- #
def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(config.DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _agora() -> datetime:
    return datetime.now(config.TZ)


# --------------------------------------------------------------------------- #
# init_db — cria tabelas SQLite se necessário; no Supabase já existem
# --------------------------------------------------------------------------- #
def init_db() -> None:
    if config.USE_SUPABASE:
        # Tabelas já foram criadas no painel do Supabase — só verifica conexão
        try:
            _sb.table("consultas").select("id").limit(1).execute()
        except Exception as e:
            raise RuntimeError(f"Falha ao conectar ao Supabase: {e}") from e
        return

    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS consultas (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                nome            TEXT NOT NULL,
                telefone        TEXT NOT NULL,
                data_hora       TEXT NOT NULL,
                procedimento    TEXT NOT NULL,
                status          TEXT NOT NULL DEFAULT 'agendada',
                lembrete_enviado INTEGER NOT NULL DEFAULT 0,
                followup_enviado INTEGER NOT NULL DEFAULT 0,
                criado_em       TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS mensagens_enviadas (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                telefone    TEXT NOT NULL,
                tipo        TEXT NOT NULL,
                texto       TEXT NOT NULL,
                consulta_id INTEGER,
                criado_em   TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS conversas (
                sessao    TEXT PRIMARY KEY,
                historico TEXT NOT NULL,
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


# --------------------------------------------------------------------------- #
# Slots de horário (lógica pura — igual nos dois modos)
# --------------------------------------------------------------------------- #
def _slots_do_dia(dia: datetime) -> list[datetime]:
    if dia.weekday() >= 5:
        return []
    slots: list[datetime] = []
    for hora in range(config.OPEN_HOUR, config.CLOSE_HOUR):
        if config.LUNCH_START <= hora < config.LUNCH_END:
            continue
        slots.append(dia.replace(hour=hora, minute=0, second=0, microsecond=0))
    return slots


def _parse_data_hora(valor: str) -> Optional[datetime]:
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
# Horários disponíveis
# --------------------------------------------------------------------------- #
def horarios_disponiveis(data_iso: str) -> dict:
    try:
        dia = datetime.fromisoformat(data_iso).replace(tzinfo=config.TZ)
    except ValueError:
        return {"erro": "Data inválida. Use o formato AAAA-MM-DD."}

    todos = _slots_do_dia(dia)
    if not todos:
        return {"data": data_iso, "disponiveis": [], "mensagem": "A clínica não atende nesse dia (fim de semana)."}

    ocupados = _horarios_ocupados(dia)
    agora = _agora()
    livres = [s.strftime("%H:%M") for s in todos if s.isoformat() not in ocupados and s > agora]
    return {"data": data_iso, "disponiveis": livres}


def _horarios_ocupados(dia: datetime) -> set[str]:
    inicio = dia.replace(hour=0, minute=0, second=0, microsecond=0)
    fim = inicio + timedelta(days=1)

    if config.USE_SUPABASE:
        res = (
            _sb.table("consultas")
            .select("data_hora")
            .in_("status", list(_STATUS_ATIVOS))
            .gte("data_hora", inicio.isoformat())
            .lt("data_hora", fim.isoformat())
            .execute()
        )
        return {r["data_hora"] for r in res.data}

    with _connect() as conn:
        rows = conn.execute(
            """SELECT data_hora FROM consultas
               WHERE status IN ('agendada','remarcada')
                 AND data_hora >= ? AND data_hora < ?""",
            (inicio.isoformat(), fim.isoformat()),
        ).fetchall()
    return {r["data_hora"] for r in rows}


# --------------------------------------------------------------------------- #
# CRUD de consultas
# --------------------------------------------------------------------------- #
def agendar(nome: str, telefone: str, data_hora: str, procedimento: str) -> dict:
    dt = _parse_data_hora(data_hora)
    if dt is None:
        return {"ok": False, "erro": "Não entendi a data/hora. Use 'AAAA-MM-DD HH:MM'."}
    if (erro := _slot_valido(dt)) is not None:
        return {"ok": False, "erro": erro}

    if config.USE_SUPABASE:
        # Verificar idempotência
        existing = (
            _sb.table("consultas")
            .select("id, telefone, procedimento")
            .eq("data_hora", dt.isoformat())
            .in_("status", list(_STATUS_ATIVOS))
            .execute()
        )
        if existing.data:
            ja = existing.data[0]
            if ja["telefone"] == telefone.strip():
                return {"ok": True, "ja_existia": True, "consulta": {"id": ja["id"], "nome": nome.strip(), "data_hora": dt.strftime("%d/%m/%Y às %H:%M"), "procedimento": ja["procedimento"]}}
            return {"ok": False, "erro": "Esse horário acabou de ser ocupado. Escolha outro."}

        res = _sb.table("consultas").insert({
            "nome": nome.strip(),
            "telefone": telefone.strip(),
            "data_hora": dt.isoformat(),
            "procedimento": procedimento.strip(),
            "status": "agendada",
            "criado_em": _agora().isoformat(),
        }).execute()
        cid = res.data[0]["id"]
        return {"ok": True, "consulta": {"id": cid, "nome": nome.strip(), "data_hora": dt.strftime("%d/%m/%Y às %H:%M"), "procedimento": procedimento.strip()}}

    # SQLite
    with _connect() as conn:
        ja_ocupado = conn.execute(
            "SELECT id, telefone, procedimento FROM consultas WHERE data_hora = ? AND status IN ('agendada','remarcada')",
            (dt.isoformat(),),
        ).fetchone()
        if ja_ocupado:
            if ja_ocupado["telefone"] == telefone.strip():
                return {"ok": True, "ja_existia": True, "consulta": {"id": ja_ocupado["id"], "nome": nome.strip(), "data_hora": dt.strftime("%d/%m/%Y às %H:%M"), "procedimento": ja_ocupado["procedimento"]}}
            return {"ok": False, "erro": "Esse horário acabou de ser ocupado. Escolha outro."}
        cur = conn.execute(
            "INSERT INTO consultas (nome, telefone, data_hora, procedimento, status, criado_em) VALUES (?, ?, ?, ?, 'agendada', ?)",
            (nome.strip(), telefone.strip(), dt.isoformat(), procedimento.strip(), _agora().isoformat()),
        )
        cid = cur.lastrowid
    return {"ok": True, "consulta": {"id": cid, "nome": nome.strip(), "data_hora": dt.strftime("%d/%m/%Y às %H:%M"), "procedimento": procedimento.strip()}}


def remarcar(consulta_id: int, nova_data_hora: str) -> dict:
    dt = _parse_data_hora(nova_data_hora)
    if dt is None:
        return {"ok": False, "erro": "Não entendi a nova data/hora."}
    if (erro := _slot_valido(dt)) is not None:
        return {"ok": False, "erro": erro}

    if config.USE_SUPABASE:
        consulta = _sb.table("consultas").select("*").eq("id", consulta_id).execute()
        if not consulta.data:
            return {"ok": False, "erro": f"Consulta #{consulta_id} não encontrada."}
        if consulta.data[0]["status"] not in _STATUS_ATIVOS:
            return {"ok": False, "erro": "Essa consulta não está ativa."}
        ocupado = _sb.table("consultas").select("id").eq("data_hora", dt.isoformat()).in_("status", list(_STATUS_ATIVOS)).neq("id", consulta_id).execute()
        if ocupado.data:
            return {"ok": False, "erro": "O novo horário já está ocupado."}
        _sb.table("consultas").update({"data_hora": dt.isoformat(), "status": "remarcada", "lembrete_enviado": False, "followup_enviado": False}).eq("id", consulta_id).execute()
        return {"ok": True, "consulta": {"id": consulta_id, "data_hora": dt.strftime("%d/%m/%Y às %H:%M")}}

    with _connect() as conn:
        consulta = conn.execute("SELECT * FROM consultas WHERE id = ?", (consulta_id,)).fetchone()
        if consulta is None:
            return {"ok": False, "erro": f"Consulta #{consulta_id} não encontrada."}
        if consulta["status"] not in _STATUS_ATIVOS:
            return {"ok": False, "erro": "Essa consulta não está ativa (já cancelada ou concluída)."}
        ocupado = conn.execute("SELECT id FROM consultas WHERE data_hora = ? AND status IN ('agendada','remarcada') AND id != ?", (dt.isoformat(), consulta_id)).fetchone()
        if ocupado:
            return {"ok": False, "erro": "O novo horário já está ocupado."}
        conn.execute("UPDATE consultas SET data_hora = ?, status = 'remarcada', lembrete_enviado = 0, followup_enviado = 0 WHERE id = ?", (dt.isoformat(), consulta_id))
    return {"ok": True, "consulta": {"id": consulta_id, "data_hora": dt.strftime("%d/%m/%Y às %H:%M")}}


def cancelar(consulta_id: int) -> dict:
    if config.USE_SUPABASE:
        consulta = _sb.table("consultas").select("*").eq("id", consulta_id).execute()
        if not consulta.data:
            return {"ok": False, "erro": f"Consulta #{consulta_id} não encontrada."}
        if consulta.data[0]["status"] not in _STATUS_ATIVOS:
            return {"ok": False, "erro": "Essa consulta já não está ativa."}
        _sb.table("consultas").update({"status": "cancelada"}).eq("id", consulta_id).execute()
        return {"ok": True, "consulta_id": consulta_id}

    with _connect() as conn:
        consulta = conn.execute("SELECT * FROM consultas WHERE id = ?", (consulta_id,)).fetchone()
        if consulta is None:
            return {"ok": False, "erro": f"Consulta #{consulta_id} não encontrada."}
        if consulta["status"] not in _STATUS_ATIVOS:
            return {"ok": False, "erro": "Essa consulta já não está ativa."}
        conn.execute("UPDATE consultas SET status = 'cancelada' WHERE id = ?", (consulta_id,))
    return {"ok": True, "consulta_id": consulta_id}


def buscar_por_telefone(telefone: str) -> dict:
    if config.USE_SUPABASE:
        res = _sb.table("consultas").select("id, nome, data_hora, procedimento, status").eq("telefone", telefone.strip()).order("data_hora").execute()
        consultas = [{"id": r["id"], "nome": r["nome"], "data_hora": datetime.fromisoformat(r["data_hora"]).strftime("%d/%m/%Y às %H:%M"), "procedimento": r["procedimento"], "status": r["status"]} for r in res.data]
        return {"telefone": telefone.strip(), "consultas": consultas}

    with _connect() as conn:
        rows = conn.execute("SELECT id, nome, data_hora, procedimento, status FROM consultas WHERE telefone = ? ORDER BY data_hora", (telefone.strip(),)).fetchall()
    consultas = [{"id": r["id"], "nome": r["nome"], "data_hora": datetime.fromisoformat(r["data_hora"]).strftime("%d/%m/%Y às %H:%M"), "procedimento": r["procedimento"], "status": r["status"]} for r in rows]
    return {"telefone": telefone.strip(), "consultas": consultas}


# --------------------------------------------------------------------------- #
# Mensagens enviadas
# --------------------------------------------------------------------------- #
def registrar_mensagem(telefone: str, tipo: str, texto: str, consulta_id: int) -> None:
    if config.USE_SUPABASE:
        _sb.table("mensagens_enviadas").insert({"telefone": telefone, "tipo": tipo, "texto": texto, "consulta_id": consulta_id, "criado_em": _agora().isoformat()}).execute()
        return
    with _connect() as conn:
        conn.execute("INSERT INTO mensagens_enviadas (telefone, tipo, texto, consulta_id, criado_em) VALUES (?, ?, ?, ?, ?)", (telefone, tipo, texto, consulta_id, _agora().isoformat()))


def listar_mensagens(limite: int = 50) -> list[dict]:
    if config.USE_SUPABASE:
        res = _sb.table("mensagens_enviadas").select("*").order("id", desc=True).limit(limite).execute()
        return [{"id": r["id"], "telefone": r["telefone"], "tipo": r["tipo"], "texto": r["texto"], "criado_em": datetime.fromisoformat(r["criado_em"]).strftime("%d/%m %H:%M")} for r in res.data]

    with _connect() as conn:
        rows = conn.execute("SELECT * FROM mensagens_enviadas ORDER BY id DESC LIMIT ?", (limite,)).fetchall()
    return [{"id": r["id"], "telefone": r["telefone"], "tipo": r["tipo"], "texto": r["texto"], "criado_em": datetime.fromisoformat(r["criado_em"]).strftime("%d/%m %H:%M")} for r in rows]


# --------------------------------------------------------------------------- #
# Lembretes e follow-ups (usados pelo scheduler)
# --------------------------------------------------------------------------- #
def consultas_para_lembrete() -> list:
    agora = _agora()
    limite = agora + timedelta(hours=config.REMINDER_LEAD_HOURS)

    if config.USE_SUPABASE:
        res = (
            _sb.table("consultas")
            .select("*")
            .in_("status", list(_STATUS_ATIVOS))
            .eq("lembrete_enviado", False)
            .gt("data_hora", agora.isoformat())
            .lte("data_hora", limite.isoformat())
            .execute()
        )
        return res.data

    with _connect() as conn:
        return conn.execute(
            "SELECT * FROM consultas WHERE status IN ('agendada','remarcada') AND lembrete_enviado = 0 AND data_hora > ? AND data_hora <= ?",
            (agora.isoformat(), limite.isoformat()),
        ).fetchall()


def consultas_para_followup() -> list:
    corte = _agora() - timedelta(minutes=config.NOSHOW_GRACE_MINUTES)

    if config.USE_SUPABASE:
        res = (
            _sb.table("consultas")
            .select("*")
            .in_("status", list(_STATUS_ATIVOS))
            .eq("followup_enviado", False)
            .lt("data_hora", corte.isoformat())
            .execute()
        )
        return res.data

    with _connect() as conn:
        return conn.execute(
            "SELECT * FROM consultas WHERE status IN ('agendada','remarcada') AND followup_enviado = 0 AND data_hora < ?",
            (corte.isoformat(),),
        ).fetchall()


def marcar_lembrete_enviado(consulta_id: int) -> None:
    if config.USE_SUPABASE:
        _sb.table("consultas").update({"lembrete_enviado": True}).eq("id", consulta_id).execute()
        return
    with _connect() as conn:
        conn.execute("UPDATE consultas SET lembrete_enviado = 1 WHERE id = ?", (consulta_id,))


def marcar_falta_e_followup(consulta_id: int) -> None:
    if config.USE_SUPABASE:
        _sb.table("consultas").update({"status": "falta", "followup_enviado": True}).eq("id", consulta_id).execute()
        return
    with _connect() as conn:
        conn.execute("UPDATE consultas SET status = 'falta', followup_enviado = 1 WHERE id = ?", (consulta_id,))


# --------------------------------------------------------------------------- #
# Encaminhamento para atendente humano
# --------------------------------------------------------------------------- #
def encaminhar_atendente(motivo: str, telefone: str = "", sessao: str = "") -> dict:
    if config.USE_SUPABASE:
        res = _sb.table("atendimentos_humanos").insert({
            "sessao": sessao or None,
            "telefone": (telefone or "").strip() or None,
            "motivo": motivo.strip(),
            "status": "pendente",
            "criado_em": _agora().isoformat(),
        }).execute()
        return {"ok": True, "protocolo": res.data[0]["id"]}

    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO atendimentos_humanos (sessao, telefone, motivo, status, criado_em) VALUES (?, ?, ?, 'pendente', ?)",
            (sessao or None, (telefone or "").strip() or None, motivo.strip(), _agora().isoformat()),
        )
    return {"ok": True, "protocolo": cur.lastrowid}


def listar_atendimentos(limite: int = 50) -> list[dict]:
    if config.USE_SUPABASE:
        res = _sb.table("atendimentos_humanos").select("*").order("id", desc=True).limit(limite).execute()
        return [{"id": r["id"], "telefone": r["telefone"] or "—", "motivo": r["motivo"], "status": r["status"], "criado_em": datetime.fromisoformat(r["criado_em"]).strftime("%d/%m %H:%M")} for r in res.data]

    with _connect() as conn:
        rows = conn.execute("SELECT * FROM atendimentos_humanos ORDER BY id DESC LIMIT ?", (limite,)).fetchall()
    return [{"id": r["id"], "telefone": r["telefone"] or "—", "motivo": r["motivo"], "status": r["status"], "criado_em": datetime.fromisoformat(r["criado_em"]).strftime("%d/%m %H:%M")} for r in rows]


# --------------------------------------------------------------------------- #
# Histórico de conversa
# --------------------------------------------------------------------------- #
def carregar_historico(sessao: str) -> list:
    if config.USE_SUPABASE:
        res = _sb.table("conversas").select("historico").eq("sessao", sessao).execute()
        if res.data:
            h = res.data[0]["historico"]
            return h if isinstance(h, list) else json.loads(h)
        return []

    with _connect() as conn:
        row = conn.execute("SELECT historico FROM conversas WHERE sessao = ?", (sessao,)).fetchone()
    return json.loads(row["historico"]) if row else []


def salvar_historico(sessao: str, historico: list) -> None:
    agora = _agora().isoformat()

    if config.USE_SUPABASE:
        existing = _sb.table("conversas").select("sessao").eq("sessao", sessao).execute()
        if existing.data:
            _sb.table("conversas").update({"historico": historico, "atualizado_em": agora}).eq("sessao", sessao).execute()
        else:
            _sb.table("conversas").insert({"sessao": sessao, "historico": historico, "criado_em": agora, "atualizado_em": agora}).execute()
        return

    with _connect() as conn:
        conn.execute(
            "INSERT INTO conversas (sessao, historico, criado_em, atualizado_em) VALUES (?, ?, ?, ?) ON CONFLICT(sessao) DO UPDATE SET historico = excluded.historico, atualizado_em = excluded.atualizado_em",
            (sessao, json.dumps(historico, ensure_ascii=False), agora, agora),
        )


# --------------------------------------------------------------------------- #
# Seed de demonstração
# --------------------------------------------------------------------------- #
def seed_demo() -> dict:
    agora = _agora()
    lembrete_dt = (agora + timedelta(hours=23)).replace(minute=0, second=0, microsecond=0)
    noshow_dt = (agora - timedelta(hours=2)).replace(minute=0, second=0, microsecond=0)

    criadas = []
    dados = [
        ("Ana Paula", "+5511990001111", lembrete_dt, "Limpeza"),
        ("Carlos Mendes", "+5511990002222", noshow_dt, "Avaliação"),
    ]

    if config.USE_SUPABASE:
        for nome, tel, dt, proc in dados:
            res = _sb.table("consultas").insert({
                "nome": nome, "telefone": tel,
                "data_hora": dt.isoformat(), "procedimento": proc,
                "status": "agendada", "criado_em": agora.isoformat(),
            }).execute()
            criadas.append({"id": res.data[0]["id"], "nome": nome, "data_hora": dt.strftime("%d/%m %H:%M"), "procedimento": proc})
        return {"ok": True, "criadas": criadas}

    with _connect() as conn:
        for nome, tel, dt, proc in dados:
            cur = conn.execute(
                "INSERT INTO consultas (nome, telefone, data_hora, procedimento, status, criado_em) VALUES (?, ?, ?, ?, 'agendada', ?)",
                (nome, tel, dt.isoformat(), proc, agora.isoformat()),
            )
            criadas.append({"id": cur.lastrowid, "nome": nome, "data_hora": dt.strftime("%d/%m %H:%M"), "procedimento": proc})
    return {"ok": True, "criadas": criadas}