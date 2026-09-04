"""Mascaramento de PII na fronteira de escrita.

Chamado por `persistence.repo.gravar_mensagem` — o ponto de estrangulamento. Toda
mensagem, todo texto de origem de extração e todo `detalhe` de tentativa de cotação
passam por aqui **antes** de chegar ao banco.

A consequência de mascarar na gravação, e não na exibição: **não existe versão crua
para vazar depois.** A UI mostra o mascarado porque é a única coisa que existe, log e
trace idem, e o screenshot fica publicável sem tratamento.

O que **não** é mascarado: idade, ano do veículo, plano e data de início. São os dados
de qualificação — cotar depende deles, e mascará-los quebraria o produto para proteger
o que não precisa de proteção.

Medições que motivam cada classe (docs/API-COTACAO.md §8.3): CPF e CEP em 100% das
conversas do dataset, telefone e e-mail em 55%, placa em 34%.
"""

from __future__ import annotations

import re

MARCADORES = ("[CPF]", "[CEP]", "[EMAIL]", "[TELEFONE]", "[PLACA]")

#: Ordem importa. E-mail vem primeiro porque um endereço pode conter sequências que
#: o regex de CEP casaria; telefone antes de CPF pelo mesmo motivo com os dígitos.
#:
#: Cada padrão tem um limite de palavra dos dois lados para não comer o ano do veículo
#: nem a idade — é o que o teste `test_texto_sem_pii_passa_intacto` protege.
_REGRAS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "email",
        re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
        "[EMAIL]",
    ),
    (
        "telefone",
        # +55 DD 9XXXX-XXXX e variações sem o +55, sem espaço ou sem hífen.
        re.compile(r"(?:\+55\s?)?\b\d{2}\s?9\d{4}[-\s]?\d{4}\b"),
        "[TELEFONE]",
    ),
    (
        "cpf",
        # Pontuado ou 11 dígitos corridos. O `(?!\d)` impede engolir um número maior.
        re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b|\b\d{11}(?!\d)"),
        "[CPF]",
    ),
    (
        "cep",
        # 8 dígitos com ou sem hífen. Vem depois do CPF para não morder os 11 dígitos.
        re.compile(r"\b\d{5}-\d{3}\b|\b\d{8}(?!\d)"),
        "[CEP]",
    ),
    (
        "placa",
        # Mercosul (LLLNLNN) e o padrão antigo (LLL-NNNN / LLLNNNN).
        re.compile(r"\b[A-Z]{3}\d[A-Z]\d{2}\b|\b[A-Z]{3}-?\d{4}\b"),
        "[PLACA]",
    ),
)


def mascarar(texto: str | None) -> str | None:
    """Substitui PII por marcadores. Idempotente.

    Idempotência não sai de graça: ela depende de os marcadores não casarem com
    nenhum dos regexes acima. `test_e_idempotente` verifica isso em vez de presumir.
    """
    if not texto:
        return texto
    for _, padrao, marcador in _REGRAS:
        texto = padrao.sub(marcador, texto)
    return texto


def contem_pii(texto: str | None) -> bool:
    """Usado nas asserções de segurança: a resposta da API e o transcript passam por
    aqui, e qualquer casamento reprova."""
    if not texto:
        return False
    return any(padrao.search(texto) for _, padrao, _ in _REGRAS)
