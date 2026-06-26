# syntax=docker/dockerfile:1

# ---------- Estágio 1: build (compila wheels das dependências) ----------
FROM python:3.12-slim AS build

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
COPY requirements.txt .

# Gera wheels para todas as dependências — instalação rápida e sem toolchain no runtime
RUN pip wheel --wheel-dir /wheels -r requirements.txt


# ---------- Estágio 2: runtime (imagem enxuta, só o necessário) ----------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LURI_DB_PATH=/data/luri.db

# Usuário sem privilégios
RUN useradd --create-home --uid 10001 luri \
    && mkdir -p /data && chown luri:luri /data

WORKDIR /app

# Instala a partir dos wheels pré-compilados do estágio de build
COPY --from=build /wheels /wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

COPY app ./app

USER luri
EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=4s --start-period=8s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health').status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
