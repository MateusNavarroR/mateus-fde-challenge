"""A cadeia de suprimentos: o que é dependência, o que só parece, e o que trava.

A lista de dependências é o vetor de comprometimento mais barato que existe — não
precisa de bug no nosso código, só de um pacote comprometido lá atrás. Este arquivo é o
que sobrou do passe de `supply-chain-risk-auditor`, incluindo **o falso positivo**,
porque uma auditoria que só registra o que o autor quis explicar não é auditoria.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
import tomllib
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]


def _diretas() -> list[str]:
    d = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))
    return d["project"]["dependencies"]


def test_o_lock_existe_e_trava_com_hash():
    """Sem hash, `uv sync` aceita um artefato trocado no índice com o mesmo número de
    versão. Com hash, a troca é detectada na instalação."""
    lock = RAIZ / "uv.lock"
    assert lock.exists(), "sem lock não há instalação reproduzível"
    texto = lock.read_text(encoding="utf-8")
    assert texto.count("hash = ") > 100, "o lock não está registrando hashes"


def test_toda_dependencia_direta_tem_piso_de_versao():
    """`nome` sem versão aceita qualquer coisa, inclusive uma major que quebre — ou
    uma versão anterior à correção de uma CVE conhecida."""
    sem_piso = [d for d in _diretas() if not any(op in d for op in (">=", "==", "~="))]
    assert not sem_piso, f"dependências sem piso de versão: {sem_piso}"


# ─── o falso positivo, guardado para não ser refeito ────────────────────────


def test_openai_NAO_e_dependencia_morta():
    """**Falso positivo do passe de cadeia de suprimentos, e ele quase virou commit.**

    Nenhum arquivo do projeto importa `openai`, o README declara que só Anthropic e
    Ollama são validados, e a verificação inicial — importar `agno.models.anthropic`
    com o módulo ausente — passou. A conclusão parecia sólida: dependência que ninguém
    usa é superfície de ataque de graça. A linha foi removida e o lock refeito.

    Estava errada. O caminho **Ollama** — um dos dois providers validados — importa
    `agno.models.ollama.responses`, que importa `agno.models.openai.open_responses`,
    que levanta `ImportError` sem o SDK. O erro do primeiro teste foi checar só o
    provider errado.

    Este teste roda em **subprocesso**, com o módulo escondido por um `MetaPathFinder`:
    no processo do pytest o `openai` já está em `sys.modules` por importações
    anteriores, e qualquer bloqueio em memória mede a ordem de importação em vez da
    dependência real. Foi assim que a primeira verificação se enganou.
    """
    if "openai" not in " ".join(_diretas()):
        pytest.fail(
            "`openai` saiu do pyproject. Ele NÃO é dependência morta: o caminho "
            "Ollama quebra sem ele — ver o corpo deste teste."
        )

    guarda = textwrap.dedent(
        """
        import sys, importlib.abc
        class Bloqueio(importlib.abc.MetaPathFinder):
            def find_spec(self, nome, path=None, target=None):
                if nome == "openai" or nome.startswith("openai."):
                    raise ImportError(nome)
                return None
        sys.meta_path.insert(0, Bloqueio())
        try:
            import agno.models.ollama  # noqa: F401
        except ImportError:
            print("PRECISA")
        else:
            print("DISPENSAVEL")
        """
    )
    r = subprocess.run([sys.executable, "-c", guarda], capture_output=True, text=True,
                       cwd=RAIZ, timeout=120)
    assert "PRECISA" in r.stdout, (
        "o caminho Ollama passou a dispensar o SDK da OpenAI. Se isso for verdade "
        "numa versão nova do Agno, a dependência pode sair — mas confirme rodando "
        "uma cotação pelo Ollama antes, e atualize o comentário do pyproject."
    )
