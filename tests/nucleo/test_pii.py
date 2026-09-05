"""Mascaramento de PII.

100% das conversas do dataset têm CPF e CEP em texto livre, 55% têm telefone e e-mail,
34% têm placa. O mascaramento não é opcional, e ele acontece **na gravação** — não na
exibição —, porque não existe versão crua para vazar depois.

Nenhum literal de PII neste arquivo: ver `tests/fixtures/pii.py` e CLAUDE.md 13b.
"""

import pytest

from app.privacy.mascarar import MARCADORES, mascarar
from tests.fixtures.pii import frase_do_lead, gerar_pii


def test_mascara_todas_as_classes():
    frase, pii = frase_do_lead(seed=1)
    saida = mascarar(frase)
    for classe, valor in pii.items():
        assert valor not in saida, classe


def test_cem_amostras_nao_escapam():
    """Um literal exercita um formato de CPF. O gerador exercita cem, de graça — e é
    onde aparece o zero à esquerda e a variação que um exemplo a dedo esconde."""
    for seed in range(100):
        frase, pii = frase_do_lead(seed)
        saida = mascarar(frase)
        escaparam = [c for c, v in pii.items() if v in saida]
        assert not escaparam, f"seed={seed} escapou: {escaparam}"


def test_preserva_o_que_nao_e_pii():
    """A idade é dado de qualificação, não PII a mascarar — cotar depende dela."""
    frase, _ = frase_do_lead(seed=1)
    assert "35 anos" in mascarar(frase)


@pytest.mark.parametrize(
    "texto",
    [
        "meu carro é 2019",
        "quero o plano completo",
        "começando dia 15",
        "tenho 62 anos",
    ],
)
def test_texto_sem_pii_passa_intacto(texto):
    assert mascarar(texto) == texto


def test_e_idempotente():
    """Os marcadores não podem casar com os próprios regexes — e isto é testado,
    não presumido."""
    for seed in range(20):
        frase, _ = frase_do_lead(seed)
        uma = mascarar(frase)
        assert mascarar(uma) == uma, f"seed={seed}"


def test_cpf_sem_pontuacao_tambem_e_pego():
    """O dataset traz CPF em formatos variados; só o pontuado seria meia proteção."""
    for seed in range(20):
        pii = gerar_pii(seed)
        nu = pii["cpf"].replace(".", "").replace("-", "")
        assert nu not in mascarar(f"cpf {nu} obrigado"), f"seed={seed}"


def test_cep_sem_hifen_tambem_e_pego():
    for seed in range(20):
        pii = gerar_pii(seed)
        nu = pii["cep"].replace("-", "")
        assert nu not in mascarar(f"cep {nu}"), f"seed={seed}"


def test_marcadores_sao_estaveis():
    """A UI e o transcript mostram estes marcadores; mudá-los muda a saída visível."""
    assert set(MARCADORES) == {"[CPF]", "[CEP]", "[EMAIL]", "[TELEFONE]", "[PLACA]"}


def test_none_e_vazio_nao_quebram():
    assert mascarar("") == ""
    assert mascarar(None) is None


# ─── o detector de credenciais: nos DOIS sentidos ────────────────────────────


def test_o_detector_pega_credencial_de_verdade():
    """Metade da mutação. Sem isto, afrouxar o detector passaria despercebido."""
    import secrets

    from app.privacy.segredos import achados

    reais = [
        "ANTHROPIC_API_KEY=sk-ant-api03-" + secrets.token_urlsafe(40),
        "ADMIN_PASSWORD=" + secrets.token_urlsafe(16),
        'admin_token: "' + secrets.token_hex(16) + '"',
        "ghp_" + secrets.token_hex(20),
    ]
    for t in reais:
        assert achados(t), f"credencial passou pelo detector: {t[:40]}…"


def test_o_detector_NAO_acusa_a_propria_marca_de_redacao_nem_codigo():
    """A outra metade, e ela nasceu de um laço real.

    O exportador de sessão redigia o segredo, o portão acusava a marca `<REDIGIDO>`, e
    a exportação abortava — limpando corretamente e sendo reprovada pela limpeza. Duas
    causas distintas, as duas de captura:

    1. `APP_ADMIN_TOKEN=<REDIGIDO>}]` capturava o `}]` do JSON em volta, e o valor
       deixava de casar o placeholder `<...>` por causa do rabo;
    2. `admin_token  =', repr(c.admin_token))` é um trecho de código Python que uma
       sessão executou e o log guardou. Segredo não tem parênteses nem `repr`.

    Uma varredura que grita pelo que ela mesma escreveu treina quem a lê a ignorá-la —
    que é o oposto do que ela existe para fazer.
    """
    from app.privacy.segredos import achados

    inocentes = [
        "APP_ADMIN_TOKEN=<REDIGIDO>}]",
        "\"admin_token  =', repr(c.admin_token))\\nprint('\"",
        "ADMIN_TOKEN=<seu-token>",
        "ADMIN_TOKEN=APP_ADMIN_TOKEN",
    ]
    for t in inocentes:
        assert not achados(t), f"falso positivo: {t[:50]}"
