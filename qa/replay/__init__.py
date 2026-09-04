"""Replay do dataset do desafio contra o agente — o harness de avaliação.

Três decisões definem tudo o que está aqui, e as três vêm de `docs/DECISOES-FECHADAS.md`
§9:

1. **Replay literal, com script em dois buracos.** As falas do lead saem cruas do
   parquet, em ordem de `message_index`. Determinístico, grátis, e exercita a linguagem
   bagunçada de verdade. Só `data_inicio` e `plano_id` — os dois campos que o lead do
   dataset **nunca** informa e que a nossa qualificação exige — recebem respondedor
   roteirizado (`respondedor.py`), com um contador de "não entendi a pergunta" que
   reprova a suíte acima de um limiar. Fragilidade visível em vez de silenciosa.

2. **A asserção do lead incotável é `quote_plan`, não `escalate_to_human`.** O agente
   não tem como saber que o lead é incotável: o catálogo no system prompt tem nomes e
   coberturas e nenhuma regra. Quem decide elegibilidade é a `/quote`, do mesmo jeito
   que quem decide preço. E recusa não cria handoff (§2). Ver `assercoes.py`.

3. **Preço se confere por cálculo, nunca por juiz de modelo.** O conjunto fechado de
   72 prêmios possíveis (`precos.py`) é o gabarito. `AgentAsJudgeEval` fica restrito a
   tom e clareza da recusa, que é julgamento e não conta.

E uma restrição de operação: o volume completo são **16.470 mensagens do lead em 2.500
conversas**, uma inferência por mensagem, ~14 h de parede. O default é uma amostra
estratificada de **30 conversas** (~10 min); o volume completo fica atrás de
`--tudo` (`__main__.py`).

**Este pacote lê o bronze cru, não o silver.** É a única parte de `qa/` que faz isso, e
o motivo é que o silver mascara `message_body` — injetar `[CEP]` no agente mediria o
mascaramento, não a extração. O texto cru vive em memória durante a execução e **nunca**
é escrito: tudo que sai para o relatório passa por `app.privacy.mascarar` primeiro
(`relatorio.py`).
"""
