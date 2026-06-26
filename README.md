# Lúri — Agente de Agendamento para Clínicas de Odontologia

Recepcionista virtual que **agenda, remarca e cancela consultas**, envia **lembrete 24h antes**
e faz **follow-up automático de no-show** (falta). Também **responde a perguntas frequentes**
(convênios, endereço, pagamento, etc.) e **encaminha para um atendente humano** quando o paciente
pede ou quando não consegue resolver. Tem **escopo fechado**: assuntos fora da clínica (clima,
data, conhecimentos gerais) são educadamente redirecionados.

Reimplementação em código (Python) de um fluxo originalmente montado no n8n — pensada para
portfólio: roda 100% localmente via Docker e pode ser exposta com Cloudflare Tunnel.

## Arquitetura

```
Navegador (chat HTML)
        │  POST /api/chat
        ▼
FastAPI ── agent.py ──► Claude (tool use)  ──►  ferramentas de agenda
   │                                              (agendar / remarcar /
   │                                               cancelar / horários / buscar)
   │                                                        │
   ├─ scheduler.py (APScheduler)                            ▼
   │     • agente de lembrete  (24h antes)            SQLite (/data/luri.db)
   │     • agente de no-show   (falta)                       ▲
   │            └─ "envia" mensagens ──────────────────────►─┘
   └─ static/index.html (chat + painel de mensagens automáticas)
```

- **Backend:** FastAPI + Uvicorn
- **Cérebro (provedor plugável):** o agente fala *function calling* com qualquer um destes —
  selecionado por `LLM_PROVIDER`:
  - **ollama** (local, grátis, para desenvolvimento) — protocolo compatível com OpenAI
  - **gemini** (Google) — endpoint compatível com OpenAI
  - **openai** (ou qualquer endpoint compatível)
  - **anthropic** (Claude, via SDK oficial)
  - sem provedor configurado → modo demonstração por palavras-chave
  > Ollama, Gemini e OpenAI compartilham o **mesmo loop de tool-use** (protocolo OpenAI);
  > trocar entre eles é só mudar `base_url`/modelo/chave. Trocar para Gemini depois é uma
  > linha no `.env`.
- **Agendador:** APScheduler — dois agentes rodando em ciclo (lembrete e no-show)
- **Dados:** SQLite (volume Docker, sem serviço externo)
- **Frontend:** uma página HTML, sem build
- **FAQ:** base editável em [`app/faq.py`](app/faq.py) (injetada no prompt do Claude e usada no modo demo)
- **Atendente humano:** ferramenta `encaminhar_para_atendente` registra um "ticket" para a equipe

> As mensagens de lembrete/no-show são gravadas numa tabela e exibidas no painel lateral,
> simulando uma integração com WhatsApp/SMS. Trocar essa camada por um provedor real
> (Twilio, Z-API, etc.) é só implementar `db.registrar_mensagem`.

## Como rodar

### Com Docker (recomendado)

```bash
# modo demonstração (sem IA — funciona sem chave)
docker compose up --build

# com o agente Claude real
export ANTHROPIC_API_KEY=sk-ant-...
docker compose up --build
```

Acesse **http://localhost:8000**.

### Sem Docker (desenvolvimento)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export LURI_DB_PATH=./luri.db          # evita escrever em /data
export ANTHROPIC_API_KEY=sk-ant-...    # opcional
uvicorn app.main:app --reload
```

## Demonstração rápida

1. Abra a página e clique em **“popular demo”** (canto do painel lateral).
   Isso cria duas consultas: uma daqui a ~24h e uma no passado sem comparecimento.
2. Em até ~1 minuto, o **agente de lembrete** e o **agente de no-show** disparam e as
   mensagens aparecem no painel à direita.
3. No chat, experimente: *“horários disponíveis em 2026-06-29”*, *“quero marcar uma
   avaliação”*, *“minhas consultas, telefone +5511990001111”*.
4. Teste o escopo fechado: pergunte *“vai chover amanhã?”* — a Lúri redireciona.

> No **modo demonstração** (sem `ANTHROPIC_API_KEY`) o chat usa um interpretador simples por
> palavras-chave: entende pedidos de horário por data e consulta por telefone. Para a conversa
> natural completa (entender “sexta de manhã”, conduzir o agendamento passo a passo), defina a
> chave da API.

## Endpoints

| Método | Rota | Descrição |
|-------|------|-----------|
| `POST` | `/api/chat` | Conversa com o agente (`{sessao, mensagem}`) |
| `GET`  | `/api/mensagens` | Mensagens automáticas enviadas (lembrete/no-show) |
| `GET`  | `/api/atendimentos` | Pedidos de encaminhamento para atendente humano |
| `GET`  | `/api/consultas?telefone=` | Consultas de um paciente |
| `POST` | `/api/demo/seed` | Cria consultas de demonstração |
| `GET`  | `/api/health` | Status e modo de IA |

## Expor com Cloudflare Tunnel

```bash
docker compose up -d
cloudflared tunnel --url http://localhost:8000
```

O Cloudflare devolve uma URL pública `https://...trycloudflare.com` para mostrar o agente
funcionando ao vivo.

## Configuração (variáveis de ambiente)

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `LLM_PROVIDER` | *(auto)* | `ollama` \| `gemini` \| `openai` \| `anthropic`. Vazio = anthropic se houver chave, senão ollama |
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` | Endpoint do Ollama |
| `OLLAMA_MODEL` | `qwen2.5:3b` | Modelo do Ollama (precisa `ollama pull`) |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | *(vazio)* / `gemini-2.5-flash-lite` | Para usar o Gemini |
| `ANTHROPIC_API_KEY` | *(vazio)* | Chave da API da Anthropic |
| `ANTHROPIC_MODEL` | `claude-opus-4-8` | Modelo Claude |
| `LURI_TZ` | `America/Sao_Paulo` | Fuso da clínica |
| `LURI_REMINDER_LEAD_HOURS` | `24` | Antecedência do lembrete |
| `LURI_NOSHOW_GRACE_MINUTES` | `30` | Tolerância antes de marcar falta |
| `LURI_SCHEDULER_INTERVAL_SECONDS` | `60` | Intervalo do ciclo dos agentes |
| `LURI_OPEN_HOUR` / `LURI_CLOSE_HOUR` | `9` / `18` | Expediente |
