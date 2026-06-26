#!/usr/bin/env bash
# ============================================================
#  Lúri — sobe o app + túnel Cloudflare e mostra TODOS os logs
#  Uso:   ./run.sh            (porta 8000)
#         PORT=8080 ./run.sh  (outra porta)
#  Pare com Ctrl+C — encerra app e túnel automaticamente.
# ============================================================

# vai para a pasta do projeto (onde está este script)
cd "$(dirname "$(readlink -f "$0")")" || exit 1

# cores
G='\033[0;32m'; Y='\033[1;33m'; R='\033[0;31m'; B='\033[0;36m'; N='\033[0m'
log()  { printf "${B}[luri]${N} %s\n" "$*"; }
warn() { printf "${Y}[luri]${N} %s\n" "$*"; }
err()  { printf "${R}[luri]${N} %s\n" "$*"; }

PORT="${PORT:-8000}"
LOGDIR="./logs"; mkdir -p "$LOGDIR"
APP_LOG="$LOGDIR/app.log"; TUN_LOG="$LOGDIR/tunnel.log"; OLLAMA_LOG="$LOGDIR/ollama.log"
APP_PID=""; TUN_PID=""

# ---------- encerramento limpo ----------
cleanup() {
  echo
  log "Encerrando…"
  [ -n "$TUN_PID" ] && kill "$TUN_PID" 2>/dev/null
  [ -n "$APP_PID" ] && kill "$APP_PID" 2>/dev/null
  pkill -f 'uvicorn app.main:app' 2>/dev/null
  pkill -x cloudflared 2>/dev/null
  log "Tudo parado. Até logo! 👋"
  exit 0
}
trap cleanup INT TERM

# ---------- 1. ambiente virtual + dependências ----------
if [ ! -x ".venv/bin/uvicorn" ]; then
  log "Primeira execução: criando .venv e instalando dependências…"
  python3 -m venv .venv || { err "Falha ao criar o venv (python3 instalado?)"; exit 1; }
  ./.venv/bin/pip install -q --upgrade pip
  ./.venv/bin/pip install -q -r requirements.txt || { err "Falha ao instalar dependências"; exit 1; }
fi
PY=".venv/bin"

# ---------- 2. carrega .env ----------
if [ -f .env ]; then set -a; . ./.env; set +a; fi
export LURI_DB_PATH="${LURI_DB_PATH:-$PWD/luri.db}"
PROVIDER="${LLM_PROVIDER:-}"
[ -z "$PROVIDER" ] && PROVIDER="$([ -n "${ANTHROPIC_API_KEY:-}" ] && echo anthropic || echo ollama)"
log "Provedor de IA: ${PROVIDER}"

# ---------- 3. Ollama (só se for o provedor) ----------
if [ "$PROVIDER" = "ollama" ]; then
  OLLAMA_BIN="$(command -v ollama 2>/dev/null || echo "$HOME/.local/bin/ollama")"
  if [ -x "$OLLAMA_BIN" ]; then
    if ! pgrep -x ollama >/dev/null 2>&1; then
      log "Iniciando Ollama…"
      nohup "$OLLAMA_BIN" serve > "$OLLAMA_LOG" 2>&1 &
      sleep 3
    fi
  else
    warn "Ollama não encontrado — o app cairá no modo demonstração."
  fi
fi

# ---------- 4. encerra instâncias antigas ----------
pkill -f 'uvicorn app.main:app' 2>/dev/null
pkill -x cloudflared 2>/dev/null
sleep 1

# ---------- 5. sobe o app ----------
log "Subindo o app na porta ${PORT}…"
"$PY/uvicorn" app.main:app --host 0.0.0.0 --port "$PORT" > "$APP_LOG" 2>&1 &
APP_PID=$!

for _ in $(seq 1 30); do
  curl -s "http://localhost:$PORT/api/health" >/dev/null 2>&1 && break
  sleep 1
done
HEALTH="$(curl -s "http://localhost:$PORT/api/health" 2>/dev/null)"
if [ -z "$HEALTH" ]; then
  err "O app não respondeu — veja $APP_LOG"; tail -n 15 "$APP_LOG"; cleanup
fi
log "App no ar: $HEALTH"

# ---------- 6. túnel Cloudflare ----------
if command -v cloudflared >/dev/null 2>&1; then
  log "Abrindo túnel Cloudflare…"
  cloudflared tunnel --url "http://localhost:$PORT" --no-autoupdate > "$TUN_LOG" 2>&1 &
  TUN_PID=$!
  URL=""
  for _ in $(seq 1 30); do
    URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$TUN_LOG" 2>/dev/null | head -1)"
    [ -n "$URL" ] && break
    sleep 1
  done
else
  warn "cloudflared não instalado — seguindo só com acesso local."
  URL=""
fi

# ---------- 7. resumo ----------
echo
printf "${G}===============================================================${N}\n"
printf "${G}  Lúri no ar!${N}\n"
printf "    Local:   ${B}http://localhost:%s${N}\n" "$PORT"
if [ -n "$URL" ]; then
  printf "    Público: ${B}%s${N}\n" "$URL"
else
  printf "    Público: ${Y}(túnel indisponível — veja %s)${N}\n" "$TUN_LOG"
fi
printf "${G}===============================================================${N}\n"
log "Logs ao vivo abaixo. Pressione ${Y}Ctrl+C${N}${B} para parar tudo.${N}"
echo

# ---------- 8. logs ao vivo (app + túnel) ----------
tail -n +1 -f "$APP_LOG" ${TUN_PID:+"$TUN_LOG"}
