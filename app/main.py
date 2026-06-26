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
    return {"status": "ok", "modo_ia": "claude" if config.USE_REAL_LLM else "fallback",
            "modelo": config.ANTHROPIC_MODEL if config.USE_REAL_LLM else None}


app.mount("/static", StaticFiles(directory=_STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(_STATIC / "index.html")
