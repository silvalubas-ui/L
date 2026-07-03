# Lúri — Agente de Agendamento Odontológico

Contexto do projeto para orientar qualquer sessão de desenvolvimento (Claude, Vitor, ou outra pessoa da equipe).

## Contexto técnico

| Camada | Tecnologia |
|---|---|
| Backend | Python / FastAPI |
| Banco de dados | Supabase |
| Containerização | Docker / Docker Compose |
| Tunelamento | Cloudflare Tunnel (Zero Trust, conector Docker) |
| Versionamento | GitHub — `silvalubas-ui/L` |
| Repositório local | `C:\Users\Mr Robot\L` |
| Credenciais de infraestrutura | Google Drive |

## Colaboração

Trabalho com o **Vitor**, que administra um servidor de produção separado.

> Sempre que sugerir mudanças de infraestrutura, considerar se isso pode afetar o trabalho dele ou exigir alinhamento antes de aplicar.

## Como responder (diretrizes de comunicação)

- Sempre em **português brasileiro**.
- Explicações diretas e não-técnicas. Quando um termo técnico for necessário, explicar em uma frase simples o que ele significa.
- Preferir passo a passo claro em vez de só soltar comandos sem contexto.
- Ao sugerir comandos Docker/Git/etc., indicar exatamente **onde rodar** (qual pasta, qual terminal) e **o que esperar** como resultado.

## Padrões do projeto

- Comunicação entre containers usa `http://luri:8000`, **nunca** `localhost`.
- Autenticação do Git é feita com o Personal Access Token embutido na URL do remote. ⚠️ *Risco de segurança conhecido — rotacionar e migrar para um método mais seguro é um passo pendente.*
- Tunnels rápidos (`trycloudflare.com`) são temporários — não usar como solução definitiva; preferir tunnel nomeado/persistente.

---

*Este documento substitui a necessidade de um processo formal separado (SSD) — mantê-lo atualizado é o suficiente para dar contexto rápido em qualquer nova sessão.*
