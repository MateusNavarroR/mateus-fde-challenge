"""Ferramentas de dados e avaliação — fora do caminho de execução da aplicação.

Nada aqui é importado por `app/`. É o inverso: `qa/` reusa `app/` (o mascaramento, os
contratos) para que não exista uma segunda definição de PII nem de motivo de recusa
para divergir da primeira.
"""
