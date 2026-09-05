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

import re
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


#: Sequências de ASCII imprimível com 4+ caracteres — é o que o `strings(1)` extrai,
#: e é assim que se procura segredo dentro de binário.
_IMPRIMIVEL = re.compile(rb"[\x20-\x7e]{4,}")


def _achados(caminho: Path) -> list[tuple[str, str]]:
    """Binário também é varrido: uma string de PII dentro de um parquet aparece em
    texto do mesmo jeito, e não varrê-los deixaria de fora justamente o formato em
    que o dataset viaja.

    **Mas não bytes crus.** Decodificar um PNG inteiro com `errors="ignore"` e jogar
    regex em cima produz ruído: a varredura acusou `ɩ_o@z.a` como e-mail dentro de
    uma captura de tela — dados comprimidos que por acaso casam com o padrão. Um
    falso positivo aqui é pior que inofensivo: ele treina quem lê o relatório a
    ignorar a varredura, que é exatamente o que ela não pode virar.

    Em binário, então, procura-se onde segredo de fato mora: nas sequências de ASCII
    imprimível, como o `strings(1)`. PII real deste domínio — CPF, CEP, e-mail,
    telefone, placa — é ASCII por construção, então nada de verdadeiro se perde.
    """
    try:
        bruto = caminho.read_bytes()
    except OSError:  # pragma: no cover
        return []

    if b"\x00" in bruto[:8192]:
        texto = b"\n".join(_IMPRIMIVEL.findall(bruto)).decode("ascii")
    else:
        texto = bruto.decode("utf-8", errors="ignore")
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


# ─── a varredura de binário: sem ruído, e sem cegueira ──────────────────────


def test_binario_com_PII_dentro_ainda_e_pego(tmp_path):
    """A troca de "decodificar bytes crus" por "sequências imprimíveis" não pode ter
    custado a capacidade — senão eu troquei falso positivo por falso NEGATIVO, que é
    infinitamente pior numa varredura de segurança.

    O arquivo imita um binário de verdade: cabeçalho com NUL, ruído comprimido, e a
    PII no meio — que é como ela aparece num parquet.
    """
    from tests.fixtures.pii import gerar_pii

    pii = gerar_pii(seed=7)
    binario = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        + bytes(range(256)) * 4
        + f"  {pii['cpf']}  ".encode()
        + bytes(range(256)) * 4
        + f"  {pii['email']}  ".encode()
    )
    alvo = tmp_path / "captura.png"
    alvo.write_bytes(binario)

    classes = {classe for classe, _ in _achados(alvo)}
    assert "cpf" in classes, "CPF dentro de binário tem de continuar sendo pego"
    assert "email" in classes


def test_binario_comprimido_nao_gera_falso_positivo():
    """O caso que motivou a mudança: a varredura acusou `ɩ_o@z.a` como e-mail dentro
    de uma captura de tela. Um falso positivo treina quem lê a ignorar."""
    reais = [p for p in _alvos() if p.suffix.lower() == ".png"]
    if not reais:
        pytest.skip("nenhum PNG versionado ainda")
    problemas = [(p.name, c, tr) for p in reais for c, tr in _achados(p)]
    assert not problemas, problemas
