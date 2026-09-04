"""Varredura de PII sobre tudo que é versionado e não é código.

**Por que este teste existe agora e não na fatia 10.** O mascaramento de
`app/privacy/mascarar.py` cobre mensagem persistida, log, trace, resposta de API e
tela. Ele **não** cobre o que chega ao repositório por outro caminho:

- `ai-logs/sessions/*.jsonl` — megabytes de texto cru das sessões de construção;
- artefatos derivados do dataset (camada silver);
- capturas do Playwright em `docs/evidencia-ui/`;
- transcripts em `artifacts/`.

Essa é a superfície de maior volume e a única sem teste. O scrub dela estava no
checklist da fatia 10 como **procedimento manual** — e procedimento manual às onze da
noite do dia da entrega é exatamente onde vaza.

Reusa os mesmos regexes do mascaramento, apontados para outro diretório. Não há
segunda definição de "o que é PII" para divergir, e **não há lista de exceções** — a
mesma porta que se recusa a abrir no guardrail e nas fixtures.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.privacy.mascarar import _REGRAS

RAIZ = Path(__file__).resolve().parents[2]

#: Extensões de código. Código é revisado linha a linha e tem os seus próprios testes
#: (as fixtures usam gerador semeado — CLAUDE.md 13b); o risco aqui é conteúdo que
#: chega em massa sem revisão.
CODIGO = {".py", ".ts", ".tsx", ".js", ".jsx", ".sql", ".toml", ".lock", ".cfg", ".ini"}


def _versionados() -> list[Path]:
    saida = subprocess.run(
        ["git", "ls-files", "-z"], cwd=RAIZ, capture_output=True, text=True, check=True
    ).stdout
    return [RAIZ / p for p in saida.split("\0") if p]


def _alvos() -> list[Path]:
    return [
        p
        for p in _versionados()
        if p.suffix.lower() not in CODIGO and p.is_file() and p.stat().st_size > 0
    ]


def _achados(caminho: Path) -> list[tuple[str, str]]:
    # errors="ignore" para que binários (parquet, png) também sejam varridos: uma
    # string de PII dentro de um parquet aparece em texto do mesmo jeito.
    try:
        texto = caminho.read_bytes().decode("utf-8", errors="ignore")
    except OSError:  # pragma: no cover
        return []
    return [
        (nome, m.group(0))
        for nome, padrao, _ in _REGRAS
        for m in padrao.finditer(texto)
    ]


def test_ha_o_que_varrer():
    """Se a listagem vier vazia, o teste abaixo passaria sem olhar nada."""
    assert len(_alvos()) > 5


def test_nenhum_arquivo_versionado_sem_ser_codigo_contem_pii():
    problemas: list[str] = []
    for alvo in _alvos():
        for classe, trecho in _achados(alvo):
            rel = alvo.relative_to(RAIZ)
            problemas.append(f"{rel}: {classe} → {trecho!r}")
    assert not problemas, (
        "PII em arquivo versionado que não é código:\n  " + "\n  ".join(problemas)
    )


@pytest.mark.parametrize(
    "diretorio",
    ["ai-logs", "artifacts", "docs/evidencia-ui", "data"],
)
def test_diretorios_de_alto_volume_varridos_quando_existirem(diretorio):
    """As quatro superfícies que nascem em massa. O teste não exige que existam —
    `artifacts/` só aparece na fatia 3 —, mas varre assim que aparecerem."""
    d = RAIZ / diretorio
    if not d.exists():
        pytest.skip(f"{diretorio}/ ainda não existe")
    problemas = [
        f"{p.relative_to(RAIZ)}: {classe} → {trecho!r}"
        for p in _alvos()
        if d in p.parents
        for classe, trecho in _achados(p)
    ]
    assert not problemas, "\n  ".join(problemas)
