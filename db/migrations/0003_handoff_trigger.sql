-- 0003_handoff_trigger.sql — o conjunto fechado de gatilhos
--
-- A Fase 0 marcou `HandoffTrigger` como provisório e a coluna ficou `TEXT` livre.
-- A decisão 3 fechou sete gatilhos, e aqui o banco passa a recusar um que não exista.
--
-- `cotacao_recusada` **não** está na lista, e não é esquecimento: recusa não cria
-- handoff (docs/DECISOES-FECHADAS.md §2). Um humano releria a mesma regra fixa em
-- plans.json e daria o mesmo "não"; encaminhar 30% do tráfego para isso encheria a
-- fila com casos sem saída.

BEGIN;

-- Quando dois gatilhos casam no mesmo turno, o de maior precedência vence e os
-- demais ficam aqui. A fila mostra UM gatilho — o que mantém a regra testável, uma
-- linha por gatilho — sem que o operador perca o quadro ao assumir.
ALTER TABLE handoffs
    ADD COLUMN gatilhos_secundarios TEXT[] NOT NULL DEFAULT '{}';

ALTER TABLE handoffs
    ADD CONSTRAINT handoffs_trigger_conhecido CHECK (
        trigger IN (
            'assunto_sensivel',
            'guardrail',
            'lead_pediu_atendente',
            'cotacao_indisponivel',
            'extracao_falhou',
            'objecao_fora_da_alcada',
            'midia_sem_texto'
        )
    );

-- O mesmo conjunto vale para os secundários: um gatilho inventado não entra por
-- nenhuma das duas portas.
ALTER TABLE handoffs
    ADD CONSTRAINT handoffs_secundarios_conhecidos CHECK (
        gatilhos_secundarios <@ ARRAY[
            'assunto_sensivel', 'guardrail', 'lead_pediu_atendente',
            'cotacao_indisponivel', 'extracao_falhou',
            'objecao_fora_da_alcada', 'midia_sem_texto'
        ]::TEXT[]
    );

COMMIT;
