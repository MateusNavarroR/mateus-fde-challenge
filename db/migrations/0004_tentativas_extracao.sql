-- 0004_tentativas_extracao.sql — o contador que o gatilho de extração lê
--
-- `EXTRACAO_FALHOU` é definido como "**2ª** falha de extração no MESMO campo"
-- (docs/DECISOES-FECHADAS.md §3, custo médio: tenta uma vez, encaminha na segunda).
-- Ele não fazia isso.
--
-- Duas causas, e as duas medidas gerando o transcript do cenário degradado:
--
-- 1. o contador do turno era incrementado DUAS vezes por rejeição — uma linha
--    duplicada —, então a primeira falha já marcava 2 e o gatilho disparava nela;
-- 2. `LeadProfile.tentativas_extracao` nunca era persistido: `_perfil_de()`
--    reconstrói o perfil das colunas da conversa, e o dicionário voltava vazio a
--    cada turno. Ou seja, mesmo sem a duplicação o contador nunca teria chegado a 2
--    por dois turnos — só por duas chamadas de tool dentro do MESMO turno, que é o
--    modelo se atrapalhando, e não o lead sendo ilegível.
--
-- O efeito somado é o pior possível para o critério nº 3: um lead cujo primeiro
-- campo o modelo mandou torto ia para a fila humana na hora, sem nunca ser
-- reperguntado. Encaminhar por bug nosso é o caso que CLAUDE.md 9 nomeia.
--
-- Persistir na conversa é o que torna a contagem derivável do banco, como
-- `midias_do_lead` e `violacoes_de_guardrail` — e, como elas, auditável a partir do
-- transcript em vez de depender de um número que o chamador passa.

BEGIN;

ALTER TABLE conversations
    ADD COLUMN tentativas_extracao JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN conversations.tentativas_extracao IS
    'Quantas vezes cada campo foi rejeitado na extração, acumulado na conversa. '
    'Insumo do gatilho extracao_falhou, que dispara a partir de 2 no mesmo campo.';

COMMIT;
