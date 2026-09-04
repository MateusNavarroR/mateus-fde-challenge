"""Carregamento de ambiente e validação de credencial — explícito e testável.

**O problema que isto resolve.** O `pydantic-settings` lê o `.env` para preencher os
campos de `Settings`, com o prefixo `APP_`, mas **não exporta nada para `os.environ`**.
O SDK da Anthropic, por outro lado, lê `ANTHROPIC_API_KEY` direto do ambiente do
processo. Resultado: rodando local, a chave existe no arquivo e **não chega ao SDK**.

O `docker compose` não tem esse problema — ele interpola `${ANTHROPIC_API_KEY}` do
`.env` do diretório sozinho. Então o caminho que quebra é justamente o do
desenvolvimento, e ele quebra tarde: uma exceção de autenticação no meio de outra
coisa, e quinze minutos procurando no lugar errado.

Duas funções, e as duas são chamadas em **todo** ponto de entrada:

- `carregar_env()` põe no `os.environ` as variáveis sem prefixo que o `.env` declara,
  sem nunca sobrescrever o que já veio do ambiente real;
- `exigir_credenciais()` **falha alto no boot** se o provider configurado precisa de
  credencial e ela não está lá, com uma mensagem que diz exatamente o que fazer.

Mesmo princípio do catálogo: falhar no boot com mensagem clara é melhor que falhar no
meio de uma conversa.
"""

from __future__ import annotations

import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

#: Variáveis que o SDK ou o legado leem direto do ambiente, sem passar por `Settings`.
SEM_PREFIXO = ("ANTHROPIC_API_KEY", "OLLAMA_API_KEY", "ADMIN_TOKEN")


class CredencialAusente(RuntimeError):
    """Erra no boot, não no meio da conversa."""


def carregar_env(caminho: Path | None = None) -> list[str]:
    """Exporta para `os.environ` o que o `.env` declara sem prefixo.

    **Nunca sobrescreve** o que já veio do ambiente real: quem exportou a variável no
    shell mandou mais que o arquivo. Devolve os nomes carregados — nunca os valores.
    """
    arquivo = caminho or (RAIZ / ".env")
    if not arquivo.exists():
        return []
    carregadas = []
    for linha in arquivo.read_text().splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        chave, valor = chave.strip(), valor.strip().strip('"').strip("'")
        if not valor or chave in os.environ:
            continue
        if chave in SEM_PREFIXO or chave.startswith("QUOTE_"):
            os.environ[chave] = valor
            carregadas.append(chave)
    return carregadas


def exigir_credenciais(llm_model: str | None = None) -> None:
    """Falha alto se o provider configurado precisa de credencial e ela não está lá."""
    from app.config import get_settings

    modelo = llm_model or get_settings().llm_model

    if modelo.startswith("anthropic:") and not os.getenv("ANTHROPIC_API_KEY"):
        raise CredencialAusente(
            "APP_LLM_MODEL está em '%s', que exige ANTHROPIC_API_KEY, e ela não está "
            "no ambiente do processo.\n"
            "\n"
            "  Como resolver:\n"
            "    1. crie um .env na raiz com  ANTHROPIC_API_KEY=...  (o .gitignore já "
            "o ignora), ou\n"
            "    2. exporte a variável antes de rodar:  export ANTHROPIC_API_KEY=...\n"
            "\n"
            "  Atenção: o pydantic-settings lê o .env para os campos APP_*, mas NÃO "
            "exporta nada para o os.environ — e o SDK da Anthropic lê a variável "
            "direto do ambiente. Por isso este processo chama carregar_env() no "
            "ponto de entrada. Se você está vendo esta mensagem, ou o .env não tem a "
            "chave, ou carregar_env() não foi chamado.\n"
            "\n"
            "  Sem chave, use o outro provider validado:  "
            "APP_LLM_MODEL=ollama:qwen2.5:7b" % modelo
        )


def bootstrap() -> None:
    """Chamado por todo ponto de entrada: API, console e scripts."""
    carregar_env()
    exigir_credenciais()
