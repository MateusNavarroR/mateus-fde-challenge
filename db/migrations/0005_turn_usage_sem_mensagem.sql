-- 0005_turn_usage_sem_mensagem.sql — um turno pode custar sem produzir mensagem
--
-- `turn_usage` nasceu com `message_id NOT NULL UNIQUE`, ancorando o custo do turno na
-- mensagem que ele gerou. A premissa está errada: **existe turno que não gera
-- mensagem nenhuma**, e ele custa tokens igual.
--
-- O caso concreto, medido no replay do dataset: depois da cotação sair pela tool, o
-- texto do modelo é descartado (`ja_enviou`), e se o lead ainda escrever, o turno roda,
-- consome contexto e não escreve linha em `messages`. `gravar_turn_usage` então
-- ancorava na ÚLTIMA mensagem — a mesma do turno anterior — e batia no UNIQUE.
--
-- Isso não aparecia antes porque o caminho `ja_enviou → return` saía sem commit e o
-- `flush` voltava atrás no rollback (ver a correção ② da vistoria). Ou seja: o UNIQUE
-- vinha sendo violado o tempo todo, em silêncio, e o custo daqueles turnos sumia. O
-- commit apenas tornou o defeito visível — e derrubou o replay, que é onde ele
-- finalmente apareceu.
--
-- Duas mudanças, e as duas são sobre a mesma premissa:
--
-- 1. `message_id` passa a ser anulável: o turno sem mensagem grava custo com âncora
--    nula, em vez de mentir apontando para a mensagem de outro turno;
-- 2. o UNIQUE sai: ele codificava "uma mensagem, um turno", que só vale para os
--    turnos que produzem mensagem. O índice parcial abaixo preserva a garantia ONDE
--    ela é verdadeira, e é o que impede a gravação em duplicata de um mesmo turno.

BEGIN;

ALTER TABLE turn_usage ALTER COLUMN message_id DROP NOT NULL;
ALTER TABLE turn_usage DROP CONSTRAINT IF EXISTS turn_usage_message_id_key;

CREATE UNIQUE INDEX IF NOT EXISTS turn_usage_message_id_uniq
    ON turn_usage (message_id)
    WHERE message_id IS NOT NULL;

COMMENT ON COLUMN turn_usage.message_id IS
    'A mensagem que este turno produziu, quando produziu alguma. NULL num turno que '
    'rodou e não escreveu — o custo existiu igual, e omiti-lo subestimaria a conta.';

COMMIT;
