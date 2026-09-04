# A aplicação: backend FastAPI + agente Agno, servindo também o frontend construído.
#
# Duas etapas, e a primeira existe por um motivo de produto, não de tamanho de imagem:
# o `docker compose up` precisa subir **o produto inteiro** com um comando. Um
# frontend que exige `npm install` à parte transformaria "um comando" em três, e o
# critério nº 1 do desafio é justamente que funcione.

# ── etapa 1: o frontend ─────────────────────────────────────────────────────
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
# Os testes não entram na imagem: o build de produção é do produto, não da suíte.
RUN npm run build

# ── etapa 2: a aplicação ────────────────────────────────────────────────────
FROM python:3.13-slim
WORKDIR /srv

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app/ ./app/
COPY config/ ./config/
COPY db/ ./db/
COPY qa/ ./qa/
COPY --from=web /web/dist ./web/dist

ENV PATH="/srv/.venv/bin:$PATH" \
    APP_ENV=prod \
    PYTHONUNBUFFERED=1

EXPOSE 8080

# `--host 0.0.0.0` DENTRO do contêiner é o correto: quem restringe a exposição é o
# `docker-compose.yml`, publicando em 127.0.0.1. Ligar em loopback aqui tornaria o
# serviço inalcançável até pela rede interna do compose.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
