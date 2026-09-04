"""Pipeline do dataset do desafio: bronze → silver.

**Bronze** é o parquet original do desafio, intocado e não versionado aqui: lê-se do
caminho dele. Copiar 26.470 mensagens com CPF e CEP em texto livre para dentro de um
repositório público seria criar exatamente o vazamento que o resto do projeto gasta
energia evitando (CLAUDE.md 13).

**Silver** é uma linha por mensagem, com PII mascarada por `app.privacy.mascarar`,
ordenada por `conversation_id` e `message_index` (nunca por `timestamp`), com a
elegibilidade da conversa calculada a partir das regras de `plans.json`.

**Gold foi cortada do escopo.** O que ela faria — agregado por conversa — cabe em
memória no replay, e o replay depende do agente, que é outra frente.

O dataset **nunca** é few-shot de cotação (CLAUDE.md 5): 100% das cotações dele são
matematicamente impossíveis. Silver existe para tom, objeções, testes de extração e
corpus de replay — nunca para preço, plano, cobertura ou regra.
"""
