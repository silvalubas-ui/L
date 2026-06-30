"""API FastAPI: serve o chat, expõe os endpoints e sobe o agendador."""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import agent, config, db, scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

_STATIC = Path(__file__).parent / "static"
_sched = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    global _sched
    _sched = scheduler.iniciar()
    yield
    if _sched:
        _sched.shutdown(wait=False)


app = FastAPI(title="Lúri — Agente de Agendamento Odontológico", lifespan=lifespan)


class ChatRequest(BaseModel):
    sessao: str = Field(..., description="Identificador da conversa.")
    mensagem: str = Field(..., min_length=1)


class ChatResponse(BaseModel):
    resposta: str


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    return ChatResponse(resposta=agent.responder(req.sessao, req.mensagem))


@app.get("/api/mensagens")
def mensagens():
    return {"mensagens": db.listar_mensagens()}


@app.get("/api/atendimentos")
def atendimentos():
    return {"atendimentos": db.listar_atendimentos()}


@app.get("/api/consultas")
def consultas(telefone: str):
    return db.buscar_por_telefone(telefone)


@app.post("/api/demo/seed")
def seed():
    return db.seed_demo()


@app.get("/api/health")
def health():
    return {"status": "ok",
            "provedor": config.LLM_PROVIDER if config.USE_REAL_LLM else "fallback",
            "modelo": config.modelo_ativo() if config.USE_REAL_LLM else None}


app.mount("/static", StaticFiles(directory=_STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(_STATIC / "index.html")

@app.get("/dashboard")
def dashboard():
    return FileResponse(_STATIC / "dashboard.html")
@app.get("/api/agenda")
def agenda_do_dia(data: str = None):
    from datetime import date
    if not data:
        data = date.today().isoformat()
    try:
        inicio = f"{data}T00:00:00"
        fim = f"{data}T23:59:59"
        res = db._sb.table("consultas")\
            .select("*")\
            .gte("data_hora", inicio)\
            .lte("data_hora", fim)\
            .order("data_hora")\
            .execute()
        return {"data": data, "consultas": res.data}
    except Exception as e:
        return {"data": data, "consultas": [], "erro": str(e)}