-- 0001_inicial.sql — modelo de dados da AutoSeguro
--
-- O critério declarado é literal: "dá pra rastrear o que aconteceu? (cada mensagem /
-- cotação, com id e status)". Este esquema é a resposta a ele, e é desenhado para
-- responder a quatro perguntas do operador sem consultar log nenhum:
--
--   1. o que foi dito nesta conversa, em que ordem, e o que saiu de fato?  → messages
--   2. quantas vezes tentamos cotar, com que status e em quanto tempo?     → quote_attempts
--   3. qual foi o número apresentado ao lead, e de onde ele veio?          → quotes
--   4. por que esta conversa foi para um humano, e por qual regra?         → handoffs
--
-- Invariante central: nenhuma mensagem com valor monetário existe sem uma linha em
-- `quotes` com status `ok`. É o guardrail "o preço nunca vem do modelo", auditável em SQL.
--
-- PII: nenhuma coluna aqui guarda texto cru do lead. `messages.conteudo` é a versão
-- mascarada, que é também a versão exibida na UI — a tela mostra o comportamento
-- correto, não uma versão especial para screenshot.

BEGIN;

-- ─────────────────────────────────────────────────────────────────────────────
-- Tipos
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TYPE conversation_state AS ENUM (
    'novo', 'qualificando', 'cotando', 'cotado', 'fechado', 'encaminhado'
);

CREATE TYPE message_autor AS ENUM ('lead', 'agente', 'sistema', 'operador');

CREATE TYPE message_status AS ENUM (
    'received', 'pending', 'sent', 'failed', 'discarded'
);

CREATE TYPE message_tipo AS ENUM ('text', 'image', 'audio', 'document');

-- Desfecho de UMA tentativa HTTP. Cinco valores porque cada um implica ação distinta
-- (docs/API-COTACAO.md §7): os dois primeiros retentam, os três últimos nunca.
CREATE TYPE quote_outcome AS ENUM (
    'transient',    -- 500/502/503 da instabilidade simulada
    'timeout',      -- nosso timeout de leitura, ou erro de conexão
    'ok',
    'refused',      -- 422 cotacao_recusada com motivo que é recusa de verdade
    'bad_request'   -- 400, 422 detail, ou 422 "recusa" que é dado nosso errado
);

CREATE TYPE quote_job_status AS ENUM ('pending', 'ok', 'refused', 'failed');

CREATE TYPE handoff_status AS ENUM ('pendente', 'assumido', 'resolvido');

-- ─────────────────────────────────────────────────────────────────────────────
-- conversations
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE conversations (
    id              TEXT PRIMARY KEY,
    channel         TEXT NOT NULL,          -- 'console' | 'web'
    -- Identificador do lead no canal. Nunca é telefone real: no console é o nome da
    -- sessão, no web o id do socket. Repositório público.
    external_ref    TEXT NOT NULL,
    state           conversation_state NOT NULL DEFAULT 'novo',

    -- Perfil de qualificação, desnormalizado de propósito: são cinco campos, sempre
    -- lidos juntos, e uma tabela à parte só adicionaria um join a toda leitura.
    idade           SMALLINT CHECK (idade BETWEEN 0 AND 200),
    veiculo_ano     SMALLINT CHECK (veiculo_ano BETWEEN 1950 AND 2100),
    cep             CHAR(8)  CHECK (cep ~ '^[0-9]{8}$'),  -- 8 dígitos: ver §5.3
    data_inicio     DATE,
    plano_id        TEXT     CHECK (plano_id IN ('essencial','completo','premium')),

    criado_em       TIMESTAMPTZ NOT NULL DEFAULT now(),
    atualizado_em   TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (channel, external_ref)
);

CREATE INDEX conversations_state_idx ON conversations (state, atualizado_em DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- messages — "cada mensagem, com id e status"
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE messages (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,

    -- Ordem canônica. É por ela que se ordena e se pagina, NUNCA por timestamp:
    -- no dataset do desafio 99,8% das conversas têm timestamp fora de ordem, e a
    -- lição vale para o nosso lado — relógio não é ordem.
    index           INTEGER NOT NULL CHECK (index >= 0),

    autor           message_autor NOT NULL,
    tipo            message_tipo NOT NULL DEFAULT 'text',

    -- SEMPRE mascarado. É a coluna exibida na UI e no transcript entregue.
    conteudo        TEXT NOT NULL,

    status          message_status NOT NULL,

    -- Id atribuído pelo canal. Deduplicação de entrada: o mesmo external_id entregue
    -- duas vezes produz uma linha só.
    external_id     TEXT,

    -- O guardrail, materializado: uma mensagem que apresenta preço aponta para a
    -- cotação que o produziu. FK adiada porque `quotes` é criada depois.
    quote_id        TEXT,

    criado_em       TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (conversation_id, index)
);

CREATE UNIQUE INDEX messages_external_id_uidx
    ON messages (conversation_id, external_id)
    WHERE external_id IS NOT NULL;

CREATE INDEX messages_conversation_idx ON messages (conversation_id, index);

-- ─────────────────────────────────────────────────────────────────────────────
-- quotes — o job de cotação
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE quotes (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    status          quote_job_status NOT NULL DEFAULT 'pending',

    -- Requisição EXATA enviada, já normalizada. Guardada para que uma cotação seja
    -- reproduzível anos depois, mesmo que o perfil da conversa mude.
    req_plano_id    TEXT NOT NULL,
    req_idade       SMALLINT NOT NULL,
    req_veiculo_ano SMALLINT NOT NULL,
    req_cep         CHAR(8),
    req_data_inicio DATE,

    -- Resultado. Preenchidos se e somente se status = 'ok' (CHECK abaixo).
    premio_mensal   NUMERIC(10,2),
    franquia        INTEGER,
    carencia_dias   SMALLINT,
    -- NULL quando a data de início cai no dia 1 — ausência é informação, e a
    -- mensagem ao lead precisa dizer "o primeiro mês já é integral".
    pro_rata_valor  NUMERIC(10,2),
    pro_rata_dias   SMALLINT,
    -- Corpo 200 completo, para auditoria e para o renderer. Sem PII: a /quote não
    -- devolve nada do lead além dos multiplicadores.
    payload         JSONB,

    -- Preenchidos quando status <> 'ok'.
    motivo_recusa   TEXT,     -- normalizado: idade_acima_do_limite | ... | NULL
    erro_outcome    quote_outcome,
    circuito_aberto BOOLEAN NOT NULL DEFAULT FALSE,

    total_latency_ms INTEGER,
    criado_em       TIMESTAMPTZ NOT NULL DEFAULT now(),
    finalizado_em   TIMESTAMPTZ,

    -- O invariante do guardrail, imposto pelo banco e não pela boa vontade do código:
    -- só existe prêmio quando o job deu certo, e nunca existe job 'ok' sem prêmio.
    CONSTRAINT quotes_premio_sse_ok CHECK (
        (status = 'ok'  AND premio_mensal IS NOT NULL AND payload IS NOT NULL)
        OR
        (status <> 'ok' AND premio_mensal IS NULL)
    ),
    -- Recusa tem motivo; o que não é recusa não tem.
    CONSTRAINT quotes_motivo_sse_refused CHECK (
        (status = 'refused' AND motivo_recusa IS NOT NULL)
        OR
        (status <> 'refused' AND motivo_recusa IS NULL)
    )
);

CREATE INDEX quotes_conversation_idx ON quotes (conversation_id, criado_em DESC);
CREATE INDEX quotes_status_idx ON quotes (status, criado_em DESC);

ALTER TABLE messages
    ADD CONSTRAINT messages_quote_fk
    FOREIGN KEY (quote_id) REFERENCES quotes (id) ON DELETE SET NULL;

-- ─────────────────────────────────────────────────────────────────────────────
-- quote_attempts — uma linha por tentativa HTTP
-- ─────────────────────────────────────────────────────────────────────────────
--
-- Esta tabela é a evidência de C2. Ela é o que permite responder, sem log:
-- "tentamos 3 vezes, a 1ª deu 503 em 40ms, a 2ª estourou o timeout aos 12s, a 3ª
-- voltou 200 aos 8,01s" — e é a origem da linha do tempo em /admin/conversas e das
-- métricas de p50/p95 e do estado do breaker em /admin/status.

CREATE TABLE quote_attempts (
    id              TEXT PRIMARY KEY,
    quote_id        TEXT NOT NULL REFERENCES quotes (id) ON DELETE CASCADE,
    attempt         SMALLINT NOT NULL CHECK (attempt >= 1),

    -- NULL quando não houve resposta: timeout de leitura ou erro de conexão.
    http_status     SMALLINT,
    latency_ms      INTEGER NOT NULL,
    outcome         quote_outcome NOT NULL,

    -- Texto cru devolvido pela API, para diagnóstico. NUNCA é exibido ao lead.
    -- O corpo do 422 do Pydantic ecoa o payload enviado (idade, CEP), então este
    -- campo passa pelo mascaramento antes de gravar, como qualquer outro texto.
    detalhe         TEXT,

    criado_em       TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (quote_id, attempt),
    -- Sem resposta é timeout, e timeout não tem status. Impede a linha incoerente
    -- que faria a tela de status mentir.
    CONSTRAINT attempts_timeout_sem_status CHECK (
        (outcome = 'timeout' AND http_status IS NULL)
        OR
        (outcome <> 'timeout' AND http_status IS NOT NULL)
    )
);

CREATE INDEX quote_attempts_recentes_idx ON quote_attempts (criado_em DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- handoffs — a fila operável
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE handoffs (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,

    -- Qual REGRA disparou. É o que torna o critério "explícito e defensável":
    -- a fila mostra o gatilho, não uma frase gerada. O conjunto de valores é fechado
    -- pela decisão aberta nº1 e vira CHECK quando ela fechar.
    trigger         TEXT NOT NULL,
    -- Motivo legível para o operador. Nunca é o texto cru da API nem do lead.
    reason          TEXT NOT NULL,
    summary         TEXT,

    -- 'regra' | 'modelo' — um gatilho determinístico (breaker aberto, 422 de recusa)
    -- e uma decisão do modelo produzem o mesmo sinal, e a fila distingue os dois.
    disparado_por   TEXT NOT NULL DEFAULT 'regra'
                    CHECK (disparado_por IN ('regra','modelo')),

    -- Última cotação tentada. É o que o operador precisa ver primeiro ao assumir.
    quote_id        TEXT REFERENCES quotes (id) ON DELETE SET NULL,

    status          handoff_status NOT NULL DEFAULT 'pendente',
    criado_em       TIMESTAMPTZ NOT NULL DEFAULT now(),
    assumido_em     TIMESTAMPTZ,
    resolved_at     TIMESTAMPTZ,

    CONSTRAINT handoffs_resolvido_tem_data CHECK (
        (status = 'resolvido') = (resolved_at IS NOT NULL)
    )
);

-- Sustenta o badge de pendentes visível de qualquer tela.
CREATE INDEX handoffs_pendentes_idx ON handoffs (status, criado_em DESC);
CREATE INDEX handoffs_conversation_idx ON handoffs (conversation_id);

COMMIT;
