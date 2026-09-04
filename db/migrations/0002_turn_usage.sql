-- 0002_turn_usage.sql — custo e uso de tokens por turno
--
-- Substitui o Langfuse (ver docs/DECISOES-FECHADAS.md §5). Sustenta duas coisas que
-- de outra forma seriam alegação em vez de evidência:
--
--   1. **O prompt caching funciona.** `cache_read` maior que zero a partir do segundo
--      turno é a prova. Sem número, "usamos prompt caching" é uma frase no README.
--   2. **Quanto custa uma conversa.** Custo por conversa, acumulado, taxa de acerto de
--      cache, Anthropic e Ollama lado a lado — no admin, para quem rodar a aplicação.
--
-- Granularidade: um turno = uma execução do agente = um `RunOutput` do Agno, cujo
-- `metrics` é um `RunMetrics`. Não é por chamada de API ao modelo (isso seria
-- `MessageMetrics`): um turno com tool call faz várias chamadas, e o que interessa
-- aqui é o custo do turno.
--
-- Por que `cost_usd` é calculado por nós e não lido do Agno: a tabela de
-- disponibilidade por provider da documentação do Agno mostra que a Anthropic **não
-- popula** o campo `cost` de `BaseMetrics`. Calcular do nosso lado não é preferência,
-- é a única opção — e traz o benefício de o preço ficar auditável.

BEGIN;

CREATE TABLE turn_usage (
    id              TEXT PRIMARY KEY,

    -- O turno é identificado pela mensagem do agente que ele produziu.
    message_id      TEXT NOT NULL REFERENCES messages (id) ON DELETE CASCADE,
    -- Desnormalizado: o painel agrega por conversa, e este é o join que ele evitaria
    -- fazer em toda linha.
    conversation_id TEXT NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,

    -- Model-string do Agno, como configurada: "anthropic:claude-sonnet-4-5-20250929",
    -- "ollama:qwen2.5:7b". Guardada inteira porque é ela que identifica o preço.
    model           TEXT NOT NULL,
    -- Derivado do prefixo, para o painel comparar providers sem parsear string em SQL.
    provider        TEXT NOT NULL,

    tokens_in       INTEGER NOT NULL DEFAULT 0,
    tokens_out      INTEGER NOT NULL DEFAULT 0,

    -- NULL, e não 0, quando o provider não reporta caching. O Ollama não popula estes
    -- campos, e um zero ali mentiria: diria "o cache não acertou" onde a verdade é
    -- "não existe cache neste caminho". A taxa de acerto do painel ignora os NULL.
    cache_read      INTEGER,
    cache_write     INTEGER,

    latency_ms      INTEGER NOT NULL,

    -- Calculado por nós a partir de config/model_pricing.yaml.
    cost_usd        NUMERIC(12,6),
    -- Data de vigência da entrada de preço usada. Sem isto, um custo histórico deixa
    -- de ser auditável assim que a tabela de preços muda — e ela muda.
    pricing_vigencia DATE,

    criado_em       TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Um turno por mensagem do agente.
    UNIQUE (message_id),
    CONSTRAINT turn_usage_tokens_nao_negativos CHECK (
        tokens_in >= 0 AND tokens_out >= 0
        AND (cache_read IS NULL OR cache_read >= 0)
        AND (cache_write IS NULL OR cache_write >= 0)
    ),
    -- Custo sem vigência é um número sem procedência.
    CONSTRAINT turn_usage_custo_tem_vigencia CHECK (
        (cost_usd IS NULL) = (pricing_vigencia IS NULL)
    )
);

CREATE INDEX turn_usage_conversation_idx ON turn_usage (conversation_id, criado_em);
CREATE INDEX turn_usage_provider_idx ON turn_usage (provider, criado_em DESC);

COMMIT;
