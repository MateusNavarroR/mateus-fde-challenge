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


#: Serviços do caminho padrão — os de depuração ficam atrás do profile `debug`.
def _padrao(compose):
    return {n: s for n, s in compose["services"].items() if not s.get("profiles")}


def test_so_a_porta_da_aplicacao_e_publicada(compose):
    """O acidente que reprovaria o critério nº 1 antes de uma linha nossa rodar.

    O app fala com `db:5432` e `quote-api:8000` pela rede interna do compose;
    publicá-las no host não serve a aplicação, só à depuração. E publicar cria
    conflito garantido: quem tem Postgres instalado colide na 5432, e quem rodou o
    `docker compose up` do repositório do desafio — o caminho natural antes de olhar
    esta entrega — já tem a 8000 ocupada. "Port is already allocated" é o que o
    avaliador veria.
    """
    publicadas = {
        nome: svc.get("ports", []) for nome, svc in _padrao(compose).items()
    }
    com_porta = {n: p for n, p in publicadas.items() if p}
    assert set(com_porta) == {"app"}, (
        f"só a aplicação publica porta no caminho padrão; publicam: {com_porta}"
    )


def test_as_portas_de_depuracao_existem_atras_de_profile(compose):
    """Quem quiser depurar opta — e o caminho padrão continua sem conflito."""
    debug = {n: s for n, s in compose["services"].items() if "debug" in (s.get("profiles") or [])}
    assert debug, "as portas de depuração precisam existir, só que opcionais"
    for svc in debug.values():
        assert svc.get("ports")


def test_nenhuma_porta_publica_em_todas_as_interfaces(compose):
    """O compose do desafio publica "8000:8000", que é bind em 0.0.0.0. O nosso não
    repete isso: é uma linha, e é o que torna o /admin inalcançável da rede
    independente de autenticação (CLAUDE.md 14b)."""
    for nome, svc in compose["services"].items():
        for porta in svc.get("ports", []):
            assert str(porta).startswith("127.0.0.1:"), f"{nome} publica em {porta}"


def test_ha_portas_para_verificar(compose):
    """Se nenhum serviço publicasse porta, os testes acima passariam sem olhar nada."""
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


@pytest.mark.integracao
def test_sobe_com_5432_e_8000_ocupadas_no_host():
    """O teste que só falha na máquina de outra pessoa — então ele ocupa as portas
    de propósito e sobe o compose por cima.

    Marcado `integracao` porque leva minutos e constrói imagem; roda no portão de
    validação final, não a cada commit.
    """
    import socket
    import subprocess

    # ⚠️ **Projeto PRÓPRIO, e isto não é detalhe.**
    #
    # Sem `-p`, o teste falava com a MESMA pilha que a pessoa está usando: subia por
    # cima dela e, no `finally`, dava `down -v` — que apaga o volume. Aconteceu três
    # vezes nesta máquina: rodar a suíte derrubava a aplicação aberta no navegador e
    # **destruía as conversas gravadas**, sem nenhum aviso ligando uma coisa à outra.
    #
    # Um teste que exercita o compose precisa exercitar UMA CÓPIA dele. Com projeto
    # separado, `down -v` no fim apaga só o que este teste criou — que é o que
    # `down -v` deve significar.
    PROJETO = ["-p", "autoseguro-teste-compose"]

    # A 8080 é a única porta que o compose publica, então a cópia do teste precisa
    # dela livre. Ocupada, o teste PULA com o motivo — que é honesto: ele não pode
    # rodar, e derrubar a pilha de quem está usando para conseguir rodar seria
    # exatamente o defeito que o projeto separado veio corrigir.
    sonda = socket.socket()
    try:
        sonda.connect(("127.0.0.1", 8080))
        pytest.skip(
            "a porta 8080 já está em uso — provavelmente pelo `docker compose up` "
            "desta máquina. Este teste sobe uma CÓPIA da pilha e precisa da porta; "
            "derrube a sua com `docker compose down` para rodá-lo."
        )
    except OSError:
        pass  # livre: é o que se quer
    finally:
        sonda.close()

    bloqueios = []
    try:
        for porta in (5432, 8000):
            s = socket.socket()
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", porta))
                s.listen(1)
                bloqueios.append(s)
            except OSError:
                s.close()  # já ocupada por outro processo: melhor ainda para o teste

        r = subprocess.run(
            ["docker", "compose", *PROJETO, "up", "-d", "--wait", "--build"],
            cwd=RAIZ, capture_output=True, text=True, timeout=900,
        )
        assert r.returncode == 0, (
            "o compose não subiu com 5432 e 8000 ocupadas no host:\n" + r.stderr[-2000:]
        )
        # `--wait` já espera o healthcheck do serviço `app`, então uma leitura basta.
        # Se voltar a precisar de laço aqui, é sinal de que o healthcheck sumiu.
        import json
        import urllib.request

        with urllib.request.urlopen("http://127.0.0.1:8080/api/health", timeout=10) as resp:
            assert resp.status == 200
            assert json.load(resp)["db"] == "ok"

        # E o produto inteiro, não só a API: o SPA é servido pela mesma origem.
        with urllib.request.urlopen("http://127.0.0.1:8080/chat", timeout=10) as resp:
            assert resp.status == 200
            assert "text/html" in resp.headers["content-type"]
    finally:
        subprocess.run(["docker", "compose", *PROJETO, "down", "-v"],
                       cwd=RAIZ, capture_output=True)
        for s in bloqueios:
            s.close()
