"""O agente Lúri: orquestra o Claude com ferramentas de agendamento.

Escopo fechado: só trata de agenda da clínica. Perguntas fora do domínio
(clima, data do dia, conhecimentos gerais) são educadamente redirecionadas.
"""
import json
from datetime import datetime

from . import config, db, faq

# --------------------------------------------------------------------------- #
# Ferramentas expostas ao modelo (function calling)
# --------------------------------------------------------------------------- #
TOOLS = [
    {
        "name": "listar_horarios_disponiveis",
        "description": "Lista os horários livres da clínica em uma data específica.",
        "input_schema": {
            "type": "object",
            "properties": {
                "data": {"type": "string", "description": "Data no formato AAAA-MM-DD."}
            },
            "required": ["data"],
        },
    },
    {
        "name": "agendar_consulta",
        "description": "Agenda uma nova consulta. Confirme nome, telefone, data/hora e procedimento antes de chamar.",
        "input_schema": {
            "type": "object",
            "properties": {
                "nome": {"type": "string", "description": "Nome do paciente."},
                "telefone": {"type": "string", "description": "Telefone com DDD."},
                "data_hora": {"type": "string", "description": "Data e hora 'AAAA-MM-DD HH:MM'."},
                "procedimento": {"type": "string", "description": "Ex.: limpeza, avaliação, canal."},
            },
            "required": ["nome", "telefone", "data_hora", "procedimento"],
        },
    },
    {
        "name": "remarcar_consulta",
        "description": "Remarca uma consulta existente para um novo horário.",
        "input_schema": {
            "type": "object",
            "properties": {
                "consulta_id": {"type": "integer", "description": "ID da consulta."},
                "nova_data_hora": {"type": "string", "description": "Novo horário 'AAAA-MM-DD HH:MM'."},
            },
            "required": ["consulta_id", "nova_data_hora"],
        },
    },
    {
        "name": "cancelar_consulta",
        "description": "Cancela uma consulta existente pelo seu ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "consulta_id": {"type": "integer", "description": "ID da consulta."}
            },
            "required": ["consulta_id"],
        },
    },
    {
        "name": "buscar_consultas",
        "description": "Busca as consultas de um paciente pelo telefone.",
        "input_schema": {
            "type": "object",
            "properties": {
                "telefone": {"type": "string", "description": "Telefone com DDD."}
            },
            "required": ["telefone"],
        },
    },
    {
        "name": "encaminhar_para_atendente",
        "description": (
            "Encaminha a conversa para um atendente humano. Use quando o paciente "
            "pedir explicitamente para falar com uma pessoa, OU quando você não "
            "conseguir resolver a solicitação (dúvida fora da FAQ, reclamação, "
            "caso de urgência, ou pedido que as ferramentas não cobrem)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "motivo": {"type": "string",
                           "description": "Resumo do que o paciente precisa, para a equipe."},
                "telefone": {"type": "string",
                             "description": "Telefone do paciente para retorno, se informado."},
            },
            "required": ["motivo"],
        },
    },
]

_DISPATCH = {
    "listar_horarios_disponiveis": lambda a, s: db.horarios_disponiveis(a["data"]),
    "agendar_consulta": lambda a, s: db.agendar(a["nome"], a["telefone"], a["data_hora"], a["procedimento"]),
    "remarcar_consulta": lambda a, s: db.remarcar(int(a["consulta_id"]), a["nova_data_hora"]),
    "cancelar_consulta": lambda a, s: db.cancelar(int(a["consulta_id"])),
    "buscar_consultas": lambda a, s: db.buscar_por_telefone(a["telefone"]),
    "encaminhar_para_atendente": lambda a, s: db.encaminhar_atendente(
        a.get("motivo", ""), a.get("telefone", ""), s
    ),
}


def _executar_ferramenta(nome: str, args: dict, sessao: str) -> dict:
    try:
        return _DISPATCH[nome](args, sessao)
    except KeyError:
        return {"erro": f"Ferramenta desconhecida: {nome}"}
    except Exception as exc:  # noqa: BLE001 — devolve o erro ao modelo, não derruba o app
        return {"erro": f"Falha ao executar {nome}: {exc}"}


def _system_prompt() -> str:
    agora = datetime.now(config.TZ)
    return f"""Você é {config.AGENT_NAME}, a recepcionista virtual da {config.CLINIC_NAME}.

Data e hora atuais: {agora.strftime('%A, %d/%m/%Y %H:%M')} (fuso da clínica).

SUAS FUNÇÕES são:
1. Cuidar da agenda de consultas: agendar, remarcar, cancelar e informar horários disponíveis, além de consultar as consultas de um paciente.
2. Responder PERGUNTAS FREQUENTES sobre a clínica (abaixo).
3. Encaminhar para um atendente humano quando necessário.

Regras de comportamento:
- Fale português do Brasil, de forma cordial, breve e objetiva.
- Para agendar, você precisa de: nome, telefone (com DDD), data/hora e procedimento. Pergunte o que faltar, um pouco de cada vez.
- Use as ferramentas para qualquer leitura ou alteração da agenda — nunca invente IDs, horários ou confirmações.
- Antes de confirmar uma ação, repita os dados para o paciente conferir.
- Converta datas relativas ("amanhã", "sexta") para AAAA-MM-DD usando a data atual acima.
- A clínica atende de segunda a sexta, das {config.OPEN_HOUR:02d}h às {config.LUNCH_START:02d}h e das {config.LUNCH_END:02d}h às {config.CLOSE_HOUR:02d}h.

PERGUNTAS FREQUENTES (responda diretamente a partir destas informações):
{faq.render_para_prompt()}

ENCAMINHAR PARA ATENDENTE HUMANO — use a ferramenta encaminhar_para_atendente quando:
- o paciente pedir explicitamente para falar com uma pessoa/atendente;
- for uma reclamação, ou um caso de urgência/dor que precise de organização imediata;
- você não souber responder (dúvida que não está na FAQ) ou a solicitação fugir das suas ferramentas.
Antes de encaminhar, peça o telefone para retorno (se ainda não tiver) e um resumo do que a pessoa precisa. Ao encaminhar, avise que um atendente entrará em contato em breve e informe o número de protocolo retornado.

FORA DO ESCOPO: se perguntarem sobre clima, notícias, que dia é hoje, conhecimentos gerais ou qualquer assunto que não seja a clínica, responda gentilmente que você só pode ajudar com a agenda e dúvidas da clínica. Não responda à pergunta fora do escopo."""


# --------------------------------------------------------------------------- #
# Loop com o Claude (modo real)
# --------------------------------------------------------------------------- #
def _responder_claude(sessao: str, mensagem: str) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    historico = db.carregar_historico(sessao)
    historico.append({"role": "user", "content": mensagem})

    resposta_final = ""
    for _ in range(8):  # trava de segurança contra loop infinito de ferramentas
        resp = client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=1024,
            system=_system_prompt(),
            tools=TOOLS,
            messages=historico,
        )
        historico.append({"role": "assistant", "content": [b.model_dump() for b in resp.content]})

        if resp.stop_reason != "tool_use":
            resposta_final = "".join(b.text for b in resp.content if b.type == "text")
            break

        resultados = []
        for bloco in resp.content:
            if bloco.type == "tool_use":
                saida = _executar_ferramenta(bloco.name, bloco.input, sessao)
                resultados.append({
                    "type": "tool_result",
                    "tool_use_id": bloco.id,
                    "content": json.dumps(saida, ensure_ascii=False),
                })
        historico.append({"role": "user", "content": resultados})

    db.salvar_historico(sessao, historico)
    return resposta_final or "Desculpe, não consegui concluir agora. Pode tentar de novo?"


# --------------------------------------------------------------------------- #
# Fallback determinístico (sem ANTHROPIC_API_KEY) — mantém a demo funcionando
# --------------------------------------------------------------------------- #
def _responder_fallback(sessao: str, mensagem: str) -> str:
    import re

    texto = mensagem.lower().strip()
    saud = (f"Olá! Sou a {config.AGENT_NAME}, da {config.CLINIC_NAME}. "
            "Posso agendar, remarcar ou cancelar consultas e mostrar horários livres.")

    if any(p in texto for p in ("oi", "olá", "ola", "bom dia", "boa tarde", "boa noite")) and len(texto) < 25:
        return saud + " Como posso ajudar?"

    # Pedido explícito de atendente humano
    if any(p in texto for p in ("atendente", "humano", "falar com alguém", "falar com alguem",
                                "pessoa", "recepção", "recepcao", "reclamação", "reclamacao")):
        tel = ""
        m = re.search(r"(\+?\d[\d\s-]{8,})", texto)
        if m:
            tel = re.sub(r"[\s-]", "", m.group(1))
        r = db.encaminhar_atendente(motivo=mensagem.strip(), telefone=tel, sessao=sessao)
        return (f"Claro! Vou te encaminhar para um atendente humano. "
                f"Protocolo #{r['protocolo']} — em breve alguém entra em contato. "
                + ("" if tel else "Se quiser, me deixe um telefone para retorno."))

    # Fora do escopo
    if any(p in texto for p in ("clima", "chuva", "chover", "tempo", "notícia", "noticia", "que dia é hoje")):
        return ("Eu só consigo ajudar com a agenda e as dúvidas da clínica (agendar, remarcar, "
                "cancelar, horários ou informações sobre a clínica). Quer marcar um horário?")

    # Perguntas frequentes (FAQ)
    faq_hit = faq.buscar(texto)
    if faq_hit["encontrado"]:
        return faq_hit["resposta"]

    # Horários disponíveis para uma data AAAA-MM-DD citada
    if "horár" in texto or "horar" in texto or "disponí" in texto or "disponi" in texto or "vaga" in texto:
        m = re.search(r"(\d{4}-\d{2}-\d{2})", texto)
        if m:
            r = db.horarios_disponiveis(m.group(1))
            livres = r.get("disponiveis") or []
            if livres:
                return f"Horários livres em {m.group(1)}: " + ", ".join(livres) + "."
            return r.get("mensagem", "Não há horários livres nessa data.")
        return "Claro! Para qual data? Me envie no formato AAAA-MM-DD (ex.: 2026-06-29)."

    # Consultar por telefone
    m_tel = re.search(r"(\+?\d[\d\s-]{8,})", texto)
    if "minhas consultas" in texto or "meus agendamentos" in texto or ("consulta" in texto and m_tel):
        if m_tel:
            tel = re.sub(r"[\s-]", "", m_tel.group(1))
            r = db.buscar_por_telefone(tel)
            if r["consultas"]:
                linhas = [f"#{c['id']} — {c['data_hora']} — {c['procedimento']} ({c['status']})"
                          for c in r["consultas"]]
                return "Encontrei estas consultas:\n" + "\n".join(linhas)
            return "Não encontrei consultas para esse telefone."
        return "Me informe o telefone (com DDD) para eu localizar suas consultas."

    return ("Não tenho certeza se entendi. Posso ajudar com agendamentos, horários e dúvidas "
            "da clínica — ou, se preferir, posso te encaminhar para um atendente humano "
            "(é só dizer \"falar com atendente\").\n\n"
            "(Modo demonstração sem IA: defina ANTHROPIC_API_KEY para a conversa natural "
            "completa.)")


def responder(sessao: str, mensagem: str) -> str:
    if config.USE_REAL_LLM:
        return _responder_claude(sessao, mensagem)
    return _responder_fallback(sessao, mensagem)
