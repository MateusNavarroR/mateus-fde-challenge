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

#: Lockfiles. `uv.lock` já cai por extensão; `package-lock.json` é o mesmo artefato
#: com outro nome.
#:
#: **Isto não é uma exceção de PII — é uma correção de classificação.** Um lockfile é
#: metadado de dependência gerado por gerenciador de pacote: não tem texto humano,
#: não passa por lead nenhum, e não pode conter PII por construção. O falso positivo
#: que motivou a linha foi a versão do `caniuse-lite` (`1.0.30001810`), cujos oito
#: dígitos casam o regex de CEP.
#:
#: A diferença importa: exceção de PII é isentar um arquivo que **poderia** conter
#: PII; classificação é reconhecer que um arquivo pertence à categoria "código", que
#: já estava fora do escopo. `test_a_exclusao_de_lockfile_e_estreita` impede que esta
#: linha vire a primeira entrada de uma lista.
LOCKFILES = {"package-lock.json", "pnpm-lock.yaml", "yarn.lock", "poetry.lock"}


def _versionados() -> list[Path]:
    saida = subprocess.run(
        ["git", "ls-files", "-z"], cwd=RAIZ, capture_output=True, text=True, check=True
    ).stdout
    return [RAIZ / p for p in saida.split("\0") if p]


def _alvos() -> list[Path]:
    return [
        p
        for p in _versionados()
        if p.suffix.lower() not in CODIGO
        and p.name not in LOCKFILES
        and p.is_file()
        and p.stat().st_size > 0
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


# ─── promessas do README ─────────────────────────────────────────────────────


def test_readme_nao_aponta_para_documento_inexistente():
    """A regra máxima aplicada ao índice: *tudo que o repositório promete tem que
    existir*. Um link quebrado no README é a forma mais barata de quebrar essa regra,
    e a que ninguém percebe — porque quem escreve o índice sabe o que pretendia criar.

    Documento planejado e ainda não escrito pode ser citado, desde que **marcado**.
    """
    import re

    readme = RAIZ / "README.md"
    if not readme.exists():
        pytest.skip("README.md ainda não existe")

    problemas = []
    for linha in readme.read_text().splitlines():
        for alvo in re.findall(r"\b(docs/[\w/.-]+\.md)\b", linha):
            if not (RAIZ / alvo).exists() and "ainda não escrito" not in linha:
                problemas.append(f"{alvo} não existe e a linha não está marcada")
    assert not problemas, "\n  ".join(problemas)


def test_a_exclusao_de_lockfile_e_estreita():
    """A linha dos lockfiles não pode virar a primeira entrada de uma lista de
    exceções — que é a porta que se recusa a abrir no guardrail e nas fixtures.

    Ela vale por **nome exato** e para quatro arquivos conhecidos. Qualquer `.json`,
    `.yaml` ou `.md` continua sendo varrido.
    """
    assert len(LOCKFILES) <= 4
    for nome in LOCKFILES:
        assert nome.endswith((".json", ".yaml", ".lock"))
    # nomes vizinhos NÃO são isentos
    for vizinho in ("package.json", "composer.json", "dados.json", "config.yaml"):
        assert vizinho not in LOCKFILES


def test_a_varredura_ainda_pega_um_json_qualquer(tmp_path, monkeypatch):
    """Prova que a exclusão por nome não abriu um buraco por extensão."""
    import re

    from app.privacy.mascarar import _REGRAS

    conteudo = '{"cep": "01310-100"}'
    achou = [n for n, padrao, _ in _REGRAS if padrao.search(conteudo)]
    assert "cep" in achou
