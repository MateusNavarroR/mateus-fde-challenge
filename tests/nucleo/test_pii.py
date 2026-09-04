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
