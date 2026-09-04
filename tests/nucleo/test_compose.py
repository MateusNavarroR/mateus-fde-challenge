"""O compose e o arquivo de exemplo.

Dois testes baratos que pegam os dois acidentes mais caros de um repositório público:
uma porta aberta na rede e uma chave real no `.env.example`.
"""

from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def compose():
    return yaml.safe_load((RAIZ / "docker-compose.yml").read_text())


def test_nenhuma_porta_publica_em_todas_as_interfaces(compose):
    """O compose do desafio publica "8000:8000", que é bind em 0.0.0.0. O nosso não
    repete isso: é uma linha, e é o que torna o /admin inalcançável da rede
    independente de autenticação (CLAUDE.md 14b)."""
    for nome, svc in compose["services"].items():
        for porta in svc.get("ports", []):
            assert str(porta).startswith("127.0.0.1:"), f"{nome} publica em {porta}"


def test_ha_portas_para_verificar(compose):
    """Se nenhum serviço publicasse porta, o teste acima passaria sem olhar nada."""
    assert sum(len(s.get("ports", [])) for s in compose["services"].values()) >= 3


def test_anthropic_key_nao_tem_default(compose):
    env = compose["services"]["app"]["environment"]
    assert env["ANTHROPIC_API_KEY"] == "${ANTHROPIC_API_KEY}"  # sem `:-`


def test_admin_token_e_opcional(compose):
    """CLAUDE.md 14c: definido ⇒ exigido; ausente ⇒ sobe com aviso. Não contradiz o
    'no máximo uma variável documentada' porque não é obrigatória."""
    assert compose["services"]["app"]["environment"]["APP_ADMIN_TOKEN"] == "${ADMIN_TOKEN:-}"


def test_app_espera_o_banco_e_a_api(compose):
    dep = compose["services"]["app"]["depends_on"]
    assert dep["db"]["condition"] == "service_healthy"
    assert dep["quote-api"]["condition"] == "service_healthy"


def test_env_example_so_tem_placeholder():
    """O acidente mais caro que existe num repositório público."""
    for linha in (RAIZ / ".env.example").read_text().splitlines():
        if "=" in linha and not linha.strip().startswith("#"):
            valor = linha.split("=", 1)[1].strip()
            assert valor == "" or valor.startswith("<"), linha
