"""Gera PII válida em formato, no momento do teste.

**Nenhum valor daqui é literal no repositório.** Eles nascem em memória e morrem no fim
da execução — é o que permite que a varredura do portão de segurança seja absoluta, sem
lista de exceções (CLAUDE.md 13b, docs/planos/00-fixtures-pii.md).

As duas alternativas que isto substitui:

- literal sintético mais lista de exceções na varredura → lista de exceções em varredura
  de segurança é a mesma porta que se recusa a abrir no guardrail;
- valores fora do formato real → enfraquece exatamente o teste que se quer fazer.

Ganho que não estava no problema: um literal exercita **um** formato de CPF; um gerador
semeado exercita cem, e é onde aparece o zero à esquerda e a variação que um exemplo
escolhido a dedo esconde.
"""

from __future__ import annotations

import random

_LETRAS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_DDDS = ("11", "21", "31", "41", "47", "48", "51", "61", "62", "71", "81", "85")
#: Domínios reservados pela RFC 2606 — não são registráveis por ninguém.
_DOMINIOS = ("example.com", "example.org", "example.net")


def _cpf(rng: random.Random) -> str:
    """Com dígitos verificadores corretos: formato perfeito, conteúdo inventado."""
    n = [rng.randint(0, 9) for _ in range(9)]
    for _ in range(2):
        s = sum((len(n) + 1 - i) * v for i, v in enumerate(n))
        d = (s * 10) % 11
        n.append(0 if d == 10 else d)
    return f"{n[0]}{n[1]}{n[2]}.{n[3]}{n[4]}{n[5]}.{n[6]}{n[7]}{n[8]}-{n[9]}{n[10]}"


def _cep(rng: random.Random) -> str:
    # Inclui prefixos com zero à esquerda de propósito: é a variação que quebra
    # implementações ingênuas e que o gerador expõe ao longo de vários seeds.
    return f"{rng.randint(1000, 99999):05d}-{rng.randint(0, 999):03d}"


def _telefone(rng: random.Random) -> str:
    return f"+55 {rng.choice(_DDDS)} 9{rng.randint(1000, 9999)}-{rng.randint(1000, 9999)}"


def _placa(rng: random.Random) -> str:
    """Padrão Mercosul: LLLNLNN."""
    letras = "".join(rng.choice(_LETRAS) for _ in range(3))
    return f"{letras}{rng.randint(0, 9)}{rng.choice(_LETRAS)}{rng.randint(0, 9)}{rng.randint(0, 9)}"


def _email(rng: random.Random) -> str:
    nome = "".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(rng.randint(4, 9)))
    sep = rng.choice([".", "_", ""])
    sobre = "".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(rng.randint(4, 9)))
    return f"{nome}{sep}{sobre}@{rng.choice(_DOMINIOS)}"


def gerar_pii(seed: int) -> dict[str, str]:
    """Semeado ⇒ determinístico. O mesmo seed dá o mesmo conjunto, sempre.

    O seed é sempre explícito no teste, nunca `random.seed()` global — senão a ordem
    de execução muda o valor e a falha deixa de ser reproduzível.
    """
    rng = random.Random(seed)
    return {
        "cpf": _cpf(rng),
        "cep": _cep(rng),
        "email": _email(rng),
        "telefone": _telefone(rng),
        "placa": _placa(rng),
    }


def frase_do_lead(seed: int) -> tuple[str, dict[str, str]]:
    """A fala e os valores, para o teste assertar sobre os dois.

    O formato imita o do dataset do desafio: PII solta no meio de texto livre, em
    ordem variada, misturada com o dado de qualificação (a idade) que **não** é PII e
    não pode ser mascarado — cotar depende dele.
    """
    p = gerar_pii(seed)
    return (
        f"Tenho 35 anos, CPF {p['cpf']}, CEP {p['cep']}, "
        f"meu email é {p['email']} e o whats é {p['telefone']}, "
        f"placa {p['placa']}"
    ), p
