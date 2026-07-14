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
        "name": "consultar_clinica",
        "description": "Busca a lista de procedimentos, preços, durações e profissionais da clínica. Use SEMPRE que o paciente perguntar por valores, preços, quais procedimentos existem, quem trabalha lá ou antes de fechar um agendamento.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
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
        "description": "Agenda uma nova consulta. Confirme nome, telefone, data/hora e exige os IDs numéricos obtidos em consultar_clinica.",
        "input_schema": {
            "type": "object",
            "properties": {
                "nome": {"type": "string", "description": "Nome do paciente."},
                "telefone": {"type": "string", "description": "Telefone com DDD."},
                "data_hora": {"type": "string", "description": "Data e hora 'AAAA-MM-DD HH:MM'."},
                "profissional_id": {"type": "integer", "description": "ID numérico do profissional escolhido."},
                "procedimento_id": {"type": "integer", "description": "ID numérico do procedimento escolhido."},
            },
            "required": ["nome", "telefone", "data_hora", "profissional_id", "procedimento_id"],
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
        "description": "Encaminha a conversa para um atendente humano.",
        "input_schema": {
            "type": "object",
            "properties": {
                "motivo": {"type": "string", "description": "Resumo do que o paciente precisa, para a equipe."},
                "telefone": {"type": "string", "description": "Telefone do paciente para retorno, se informado."},
            },
            "required": ["motivo"],
        },
    },
]

_DISPATCH = {
    "consultar_clinica": lambda a, s: {
        "profissionais_disponiveis": db.listar_profissionais(),
        "procedimentos_disponiveis": db.listar_procedimentos()
    },
    "listar_horarios_disponiveis": lambda a, s: db.horarios_disponiveis(a["data"]) if hasattr(db, 'horarios_disponiveis') else {"erro": "Função em desenvolvimento."},
    "agendar_consulta": lambda a, s: db.agendar_estruturado(a["nome"], a["telefone"], a["profissional_id"], a["procedimento_id"], a["data_hora"]),
    "remarcar_consulta": lambda a, s: db.remarcar(int(a["consulta_id"]), a["nova_data_hora"]) if hasattr(db, 'remarcar') else {"erro": "Função em desenvolvimento."},
    "cancelar_consulta": lambda a, s: db.cancelar(int(a["consulta_id"])) if hasattr(db, 'cancelar') else {"erro": "Função em desenvolvimento."},
    "buscar_consultas": lambda a, s: db.buscar_por_telefone(a["telefone"]),
    "encaminhar_para_atendente": lambda a, s: db.encaminhar_atendente(a.get("motivo", ""), a.get("telefone", ""), s) if hasattr(db, 'encaminhar_atendente') else {"erro": "Função em development."},
}


def _executar_ferramenta(nome: str, args: dict, sessao: str) -> dict:
    try:
        return _DISPATCH[nome](args, sessao)
    except KeyError:
        return {"erro": f"Ferramenta desconhecida: {nome}"}
    except Exception as exc:  # noqa: BLE001
        return {"erro": f"Falha ao executar {nome}: {exc}"}


def _system_prompt() -> str:
    agora = datetime.now(config.TZ)
    return f"""Você é {config.AGENT_NAME}, a recepcionista virtual da {config.CLINIC_NAME}.

Data e hora atuais: {agora.strftime('%A, %d/%m/%Y %H:%M')} (fuso da clínica).

SUAS FUNÇÕES são:
1. Cuidar da agenda de consultas: agendar, remarcar, cancelar e informar horários disponíveis.
2. Responder sobre valores, preços, tratamentos e profissionais da clínica usando dados REAIS do banco.
3. Responder PERGUNTAS FREQUENTES sobre a clínica (abaixo).
4. Encaminhar para um atendente humano quando necessário.

Regras de comportamento fundamentais:
- Fale português do Brasil, de forma cordial, breve e objetiva.
- Responda SEMPRE em texto simples e natural. Nunca use HTML, markdown, tags ou asteriscos de formatação.
- SE O PACIENTE PERGUNTAR POR PREÇOS, VALORES, TRATAMENTOS OU PROFISSIONAIS: Você NÃO sabe essas informações de cabeça. Acione IMEDIATAMENTE a ferramenta 'consultar_clinica' para obter a lista real do banco de dados e responder com precisão.
- ANTES de confirmar e salvar um agendamento, você também DEVE acionar a ferramenta 'consultar_clinica' para descobrir os IDs corretos.
- Para agendar, você precisa de: nome, telefone (com DDD), data/hora, profissional_id e procedimento_id. Pergunte o que faltar, um pouco de cada vez.
- Use as ferramentas para qualquer leitura ou alteração da agenda — nunca invente IDs, horários ou confirmações.

PERGUNTAS FREQUENTES:
{faq.render_para_prompt()}

ENCAMINHAR PARA ATENDENTE HUMANO — use a ferramenta encaminhar_para_atendente quando a solicitação fugir das suas ferramentas."""
# --------------------------------------------------------------------------- #
# Loop com o Claude (modo real)

# --------------------------------------------------------------------------- #
def _responder_claude(sessao: str, mensagem: str) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    historico = db.carregar_historico(sessao)
    tamanho_original = len(historico)  # <-- Guardamos o tamanho original aqui!
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

    # <-- Salvamos apenas o que foi gerado nesta execução (fatiando a lista)
    db.salvar_historico(sessao, historico[tamanho_original:])
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


# --------------------------------------------------------------------------- #
# Loop com provedores compatíveis com OpenAI (Ollama, Gemini, OpenAI)
# --------------------------------------------------------------------------- #
def _tools_openai() -> list:
    return [
        {"type": "function",
         "function": {"name": t["name"], "description": t["description"],
                      "parameters": t["input_schema"]}}
        for t in TOOLS
    ]


def _responder_openai_compat(sessao: str, mensagem: str) -> str:
    from openai import OpenAI

cfg = config.openai_compat_settings()
client = OpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"] or "x", timeout=120)

historico = db.carregar_historico(sessao)  # sem a mensagem de system
tamanho_original = len(historico)
historico.append({"role": "user", "content": mensagem})

resposta_final = ""
MAX_ITER = 4
try:
        for i in range(MAX_ITER):
            mensagens = [{"role": "system", "content": _system_prompt()}] + historico
            # Na última iteração, tira as ferramentas para forçar uma resposta em texto.
            # Modelos pequenos (ex.: qwen2.5:3b) tendem a chamar ferramenta em loop;
            # sem ferramentas, o modelo é obrigado a concluir com o que já coletou.
            usar_tools = i < MAX_ITER - 1
            resp = client.chat.completions.create(
                model=cfg["model"], messages=mensagens,
                tools=_tools_openai() if usar_tools else None,
                temperature=0, max_tokens=700,
            )
            msg = resp.choices[0].message

            assistant = {"role": "assistant", "content": msg.content or ""}
            if msg.tool_calls:
                assistant["tool_calls"] = [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in msg.tool_calls
                ]
            historico.append(assistant)

            if not msg.tool_calls:
                resposta_final = msg.content or ""
                break

            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except (json.JSONDecodeError, TypeError):
                    args = {}
                saida = _executar_ferramenta(tc.function.name, args, sessao)
                historico.append({
                    "role": "tool", "tool_call_id": tc.id,
                    "content": json.dumps(saida, ensure_ascii=False),
                })
    except Exception as exc:  # noqa: BLE001 — provedor indisponível não pode derrubar o app
        prov = config.LLM_PROVIDER
        texto_exc = str(exc)
        if "429" in texto_exc or "RESOURCE_EXHAUSTED" in texto_exc or "quota" in texto_exc.lower():
            return ("Estou um pouco sobrecarregada no momento (limite de uso do provedor "
                    "de IA atingido). Tente novamente em alguns instantes, por favor. "
                    "Se preferir, posso te encaminhar para um atendente humano.")
        if prov == "ollama":
            return ("Não consegui falar com o Ollama em "
                    f"{config.OLLAMA_BASE_URL}. Verifique se ele está rodando "
                    f"('ollama serve') e se o modelo '{config.OLLAMA_MODEL}' foi baixado "
                    f"('ollama pull {config.OLLAMA_MODEL}').\n\nDetalhe: {exc}")
        return f"Falha ao falar com o provedor de IA ({prov}): {exc}"

    db.salvar_historico(sessao, historico[tamanho_original:])
    return resposta_final or "Desculpe, não consegui concluir agora. Pode tentar de novo?"

def responder(sessao: str, mensagem: str) -> str:
    prov = config.LLM_PROVIDER
    if prov == "anthropic" and config.ANTHROPIC_API_KEY:
        return _responder_claude(sessao, mensagem)
    if prov in config._OPENAI_COMPAT:
        return _responder_openai_compat(sessao, mensagem)
    return _responder_fallback(sessao, mensagem)
