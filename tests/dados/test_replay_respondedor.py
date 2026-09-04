"""O respondedor roteirizado e o contador que torna a fragilidade visível.

O contador é o teste mais importante do arquivo. Um casador de intenção por regex que
para de casar não produz erro: produz uma suíte que passa medindo nada, e uma queda de
desfechos que alguém debugaria no prompt por dois dias. O contador é o que transforma
esse silêncio em vermelho — e é por isso que ele tem teste próprio, não só o casamento.
"""

from __future__ import annotations

import pytest

from qa.replay.respondedor import Intencao, RespondedorRoteirizado, classificar


# ─────────────────────────────────────────────────────────────────────────────
# Casamento por intenção
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "fala,esperado",
    [
        ("Qual plano você prefere: essencial, completo ou premium?", Intencao.PLANO_ID),
        ("me diga qual dos três te atende melhor", Intencao.PLANO_ID),
        ("A partir de quando você quer que a cobertura comece?", Intencao.DATA_INICIO),
        ("qual a data de início da vigência?", Intencao.DATA_INICIO),
        ("Quantos anos você tem?", Intencao.IDADE),
        ("qual o ano do carro?", Intencao.VEICULO_ANO),
        ("me informe o CEP onde o carro dorme", Intencao.CEP),
    ],
)
def test_classifica_as_cinco_intencoes(fala, esperado):
    assert classificar(fala) is esperado


@pytest.mark.parametrize(
    "fala",
    [
        "",
        "   ",
        "Perfeito, já anotei aqui.",
        "Obrigado pelas informações, vou calcular.",
    ],
)
def test_fala_que_nao_pergunta_nada_nao_conta(fala):
    """Nem responde, nem soma no contador. É o caso mais comum e o mais fácil de errar:
    sem a guarda de "isto é uma pergunta?", metade das falas do agente viraria
    incompreensão."""
    assert classificar(fala) is Intencao.NENHUMA


def test_bloco_de_cotacao_nao_e_lido_como_pergunta_de_plano():
    """O bloco cita plano, franquia e carência. Sem a guarda, o respondedor responderia
    a uma pergunta que ninguém fez — e injetaria um turno a mais por cotação."""
    bloco = (
        "Plano Completo: R$ 494,58 por mês. Franquia de R$ 3.000. "
        "Roubo e furto têm carência de 30 dias a partir do início da vigência."
    )
    assert classificar(bloco) is Intencao.NENHUMA


def test_pergunta_fora_dos_cinco_campos_e_desconhecida():
    assert classificar("Você já teve algum sinistro nos últimos 5 anos?") is (
        Intencao.DESCONHECIDA
    )


def test_plano_vence_data_quando_a_pergunta_junta_os_dois():
    """Um lead real também responderia uma coisa de cada vez; a outra volta no turno
    seguinte."""
    fala = "Qual plano você quer e quando a cobertura deve começar?"
    assert classificar(fala) is Intencao.PLANO_ID


# ─────────────────────────────────────────────────────────────────────────────
# As duas respostas
# ─────────────────────────────────────────────────────────────────────────────


def test_responde_plano_com_um_dos_tres_do_catalogo():
    r = RespondedorRoteirizado(conversation_id="conv-a")
    resposta = r.responder("Qual plano você prefere?")
    assert resposta is not None
    assert r.plano_escolhido in {"essencial", "completo", "premium"}
    assert r.plano_escolhido in resposta


def test_responde_data_em_texto_livre_e_nunca_no_dia_1():
    """Duas razões, e as duas estão no docstring de `data_escolhida`: ISO testaria o
    caminho fácil de `normalizar_data`, e **dia 1 faz o `primeiro_pagamento_pro_rata`
    sumir da resposta** (API-COTACAO §6.2) — o replay deixaria de exercitar o pro-rata."""
    r = RespondedorRoteirizado(conversation_id="conv-a")
    resposta = r.responder("Quando a cobertura deve começar?")
    assert resposta is not None
    assert "dia " in resposta and not resposta.startswith("20")
    dia = int(r.data_escolhida.split()[1])
    assert dia != 1


def test_a_data_roteirizada_e_lida_pela_normalizacao_de_producao():
    """Se `normalizar_data` não lê a nossa frase, o replay injeta um campo que a
    qualificação rejeita — e mediria o nosso script, não o agente."""
    import datetime as dt

    from app.agent.tools import normalizar_data

    r = RespondedorRoteirizado(conversation_id="conv-a")
    data = normalizar_data(r.data_escolhida, hoje=dt.date(2026, 9, 4))
    assert data > dt.date(2026, 9, 4)
    assert data.day != 1


def test_idade_ano_e_cep_sao_reconhecidos_e_nao_respondidos():
    """Quem os responde são as falas do dataset. Reconhecê-los sem responder é o que
    impede o contador de subir por perguntas que o corpus já cobre — senão ele mediria o
    dataset, não o script."""
    r = RespondedorRoteirizado(conversation_id="conv-a")
    for fala in ("Quantos anos você tem?", "Qual o ano do carro?", "Qual o CEP?"):
        assert r.responder(fala) is None
    assert r.nao_entendi == 0
    assert r.perguntas == 3


def test_o_script_cobre_dois_buracos_e_so_dois():
    """"Script cobrindo dois buracos conhecidos, não a conversa inteira" — a garantia
    fica em teste para que ampliar o script seja uma decisão, não um deslize."""
    r = RespondedorRoteirizado(conversation_id="conv-a")
    r.responder("Qual plano?")
    r.responder("Quando começa?")
    assert set(r.respondeu) == {"plano_id", "data_inicio"}


# ─────────────────────────────────────────────────────────────────────────────
# O contador
# ─────────────────────────────────────────────────────────────────────────────


def test_contador_sobe_so_para_pergunta_desconhecida():
    r = RespondedorRoteirizado(conversation_id="conv-a")
    r.responder("Qual plano você prefere?")
    r.responder("Perfeito, anotado.")
    r.responder("Você tem carta de bônus de outra seguradora?")
    r.responder("Prefere pagar no cartão ou no boleto?")
    assert r.nao_entendi == 2
    assert len(r.nao_entendidas) == 2


def test_perguntas_e_o_denominador_da_taxa():
    """"não entendi" sozinho não diz nada: 3 em 4 é ruim, 3 em 200 é ruído."""
    r = RespondedorRoteirizado(conversation_id="conv-a")
    r.responder("Perfeito, anotado.")            # não é pergunta
    r.responder("Qual plano?")                    # pergunta reconhecida
    r.responder("Tem carta de bônus?")            # pergunta desconhecida
    assert r.perguntas == 2
    assert r.nao_entendi == 1


def test_pedidos_repetidos_ficam_visiveis():
    """O agente pedindo o mesmo campo cinco vezes é sinal de que a nossa resposta não
    está sendo lida — e isso tem que aparecer no relatório, não sumir na média."""
    r = RespondedorRoteirizado(conversation_id="conv-a")
    for _ in range(5):
        r.responder("Qual plano você prefere?")
    assert r.pedidos["plano_id"] == 5


# ─────────────────────────────────────────────────────────────────────────────
# Determinismo
# ─────────────────────────────────────────────────────────────────────────────


def test_mesma_conversa_recebe_sempre_o_mesmo_plano_e_a_mesma_data():
    a = RespondedorRoteirizado(conversation_id="conv-xyz")
    b = RespondedorRoteirizado(conversation_id="conv-xyz")
    assert (a.plano_escolhido, a.data_escolhida) == (b.plano_escolhido, b.data_escolhida)


def test_conversas_diferentes_exercitam_os_tres_planos():
    """Fixar um único plano exercitaria um terço da tabela de preço."""
    planos = {
        RespondedorRoteirizado(conversation_id=f"conv-{i}").plano_escolhido
        for i in range(50)
    }
    assert planos == {"essencial", "completo", "premium"}


def test_a_semente_nao_depende_de_pythonhashseed():
    """`hash()` de `str` é aleatorizado por processo: usá-lo faria a mesma conversa
    receber planos diferentes em execuções diferentes, e a comparação entre duas
    execuções do replay deixaria de valer."""
    import subprocess
    import sys

    codigo = (
        "from qa.replay.respondedor import _semente; print(_semente('conv-estavel'))"
    )
    saidas = {
        subprocess.run(
            [sys.executable, "-c", codigo], capture_output=True, text=True,
            env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin", "PYTHONPATH": "."},
            check=True,
        ).stdout.strip()
        for seed in ("0", "1", "12345")
    }
    assert len(saidas) == 1
