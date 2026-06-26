"""Base de perguntas frequentes (FAQ) da clínica.

Editar/expandir aqui é o suficiente — tanto o agente Claude (que recebe estas
perguntas no system prompt) quanto o modo de demonstração (busca por palavras-chave)
usam a mesma fonte.
"""
from . import config

FAQS: list[dict] = [
    {
        "pergunta": "Onde fica a clínica / qual o endereço?",
        "resposta": "Estamos na Av. das Acácias, 1234, sala 5 — Centro. "
                    "Há estacionamento conveniado no prédio ao lado.",
        "palavras_chave": ["endereço", "endereco", "onde fica", "localização", "localizacao",
                           "como chego", "estacionamento", "mapa"],
    },
    {
        "pergunta": "Quais os horários de atendimento?",
        "resposta": (f"Atendemos de segunda a sexta, das {config.OPEN_HOUR:02d}h às "
                     f"{config.LUNCH_START:02d}h e das {config.LUNCH_END:02d}h às "
                     f"{config.CLOSE_HOUR:02d}h. Não abrimos aos fins de semana."),
        "palavras_chave": ["horário", "horario", "funcionamento", "que horas", "abre", "fecha",
                           "atendimento", "expediente"],
    },
    {
        "pergunta": "Quais convênios/planos vocês aceitam?",
        "resposta": "Aceitamos Amil Dental, Bradesco Dental, SulAmérica e Odontoprev. "
                    "Também atendemos particular. Se não vir o seu plano aqui, posso te "
                    "encaminhar para um atendente confirmar.",
        "palavras_chave": ["convênio", "convenio", "plano", "amil", "bradesco", "sulamérica",
                           "sulamerica", "odontoprev", "aceita meu plano"],
    },
    {
        "pergunta": "Quais as formas de pagamento?",
        "resposta": "No particular aceitamos Pix, dinheiro, cartão de débito e crédito "
                    "(parcelamos em até 6x sem juros, conforme o procedimento).",
        "palavras_chave": ["pagamento", "pagar", "pix", "cartão", "cartao", "parcela",
                           "parcelar", "dinheiro", "débito", "credito", "crédito"],
    },
    {
        "pergunta": "A primeira consulta/avaliação é gratuita?",
        "resposta": "Sim! A primeira avaliação é gratuita e sem compromisso. Nela o "
                    "dentista examina e monta um plano de tratamento com orçamento.",
        "palavras_chave": ["primeira consulta", "avaliação", "avaliacao", "gratuita", "gratis",
                           "grátis", "orçamento", "orcamento", "primeira vez"],
    },
    {
        "pergunta": "Quais procedimentos vocês fazem?",
        "resposta": "Oferecemos limpeza, restauração, tratamento de canal, extração, "
                    "clareamento, próteses, implantes e odontopediatria (atendimento infantil).",
        "palavras_chave": ["procedimento", "fazem", "tratamento", "limpeza", "canal",
                           "clareamento", "implante", "prótese", "protese", "extração",
                           "extracao", "aparelho", "ortodontia", "criança", "infantil"],
    },
    {
        "pergunta": "Estou com dor / é uma emergência. O que faço?",
        "resposta": "Sentimos muito! Casos de dor têm prioridade. Posso encaixar você no "
                    "próximo horário disponível, ou te encaminhar agora para um atendente "
                    "que organiza um atendimento de urgência.",
        "palavras_chave": ["dor", "doendo", "urgência", "urgencia", "emergência", "emergencia",
                           "quebrou", "inchado", "sangrando"],
    },
]


def _normalizar(texto: str) -> str:
    return texto.lower().strip()


def buscar(texto: str) -> dict:
    """Retorna a melhor FAQ correspondente (por palavras-chave) ou indicação de não encontrado."""
    t = _normalizar(texto)
    melhor, pontuacao = None, 0
    for faq in FAQS:
        score = sum(1 for kw in faq["palavras_chave"] if kw in t)
        if score > pontuacao:
            melhor, pontuacao = faq, score
    if melhor is None:
        return {"encontrado": False}
    return {"encontrado": True, "pergunta": melhor["pergunta"], "resposta": melhor["resposta"]}


def render_para_prompt() -> str:
    """FAQ formatada para injetar no system prompt do agente."""
    linhas = [f"- P: {f['pergunta']}\n  R: {f['resposta']}" for f in FAQS]
    return "\n".join(linhas)
