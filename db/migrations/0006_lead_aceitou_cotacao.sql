-- 0006_lead_aceitou_cotacao.sql — o oitavo gatilho
--
-- **Por que ele existe.** O template da cotação convida o lead a seguir com a
-- contratação. Quando ele aceita, o handoff era gravado como `lead_pediu_atendente` —
-- e isso é falso em duas direções: o lead não pediu atendente, e a mensagem que ele
-- recebia ("já passei sua conversa pra um atendente") respondia a uma pergunta que ele
-- não fez. É o desfecho mais visível do fluxo feliz: a última coisa que o lead lê
-- quando tudo dá certo.
--
-- O CHECK de `0003` é um conjunto FECHADO, de propósito: um gatilho inventado não entra
-- nem pela coluna nem pelo array de secundários. Ampliar o conjunto é, portanto, uma
-- migração — que é exatamente o efeito desejado de ter fechado.

BEGIN;

ALTER TABLE handoffs DROP CONSTRAINT handoffs_trigger_conhecido;
ALTER TABLE handoffs
    ADD CONSTRAINT handoffs_trigger_conhecido CHECK (
        trigger IN (
            'assunto_sensivel',
            'guardrail',
            'lead_pediu_atendente',
            'cotacao_indisponivel',
            'lead_aceitou_cotacao',
            'extracao_falhou',
            'objecao_fora_da_alcada',
            'midia_sem_texto'
        )
    );

ALTER TABLE handoffs DROP CONSTRAINT handoffs_secundarios_conhecidos;
ALTER TABLE handoffs
    ADD CONSTRAINT handoffs_secundarios_conhecidos CHECK (
        gatilhos_secundarios <@ ARRAY[
            'assunto_sensivel', 'guardrail', 'lead_pediu_atendente',
            'cotacao_indisponivel', 'lead_aceitou_cotacao', 'extracao_falhou',
            'objecao_fora_da_alcada', 'midia_sem_texto'
        ]::TEXT[]
    );

COMMIT;
