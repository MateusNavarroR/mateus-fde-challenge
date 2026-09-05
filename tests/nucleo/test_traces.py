"""O trace por resposta, e a razão de ele existir sem trazer PII junto.

`ai.agno_runs` é a única tabela do sistema que **não** passa pelo mascaramento na
escrita, porque quem escreve nela é o Agno e não nós. Ela guarda `tool_args` como o
modelo os produziu — com o CEP em claro, porque é exatamente isso que a `/quote`
precisa receber. Toda a aplicação mascara PII ao gravar; servir esta tabela sem
mascarar publicaria pela porta dos fundos o dado que o resto do sistema protege, e não
só na tela: para qualquer `curl` no endpoint.

Por isso o mascaramento fica na consulta, e não no componente React — e por isso o
teste mais importante daqui é o que planta um CEP e exige que ele não volte.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text

from app.api.consultas import traces_da_conversa
from tests.fixtures.pii import cep_de

pytestmark = pytest.mark.db


@pytest.fixture(autouse=True)
def _exige_tabela_do_agno(sessao):
    """Pula com MOTIVO quando `ai.agno_runs` não existe.

    A tabela é criada pelo Agno em tempo de execução, na primeira conversa real
    contra aquele banco — não por nenhuma migração nossa. Num banco que a aplicação
    nunca tocou (um `db-debug` recém-criado, por exemplo), ela simplesmente não está
    lá, e estes testes falhavam com `relation "ai.agno_runs" does not exist`.

    Uma avaliação externa tropeçou exatamente nisso seguindo o README: três
    tracebacks que não dizem nada sobre o código e tudo sobre o estado do banco.
    Recriar a tabela aqui seria pior — duplicaríamos o schema de uma dependência,
    inclusive a FK para `agno_sessions`, e o teste passaria a medir a nossa cópia.
    """
    from sqlalchemy import text as _sql

    existe = sessao.execute(
        _sql("select to_regclass('ai.agno_runs') is not null")
    ).scalar_one()
    if not existe:
        pytest.skip(
            "ai.agno_runs ainda não existe neste banco: ela é criada pelo Agno na "
            "primeira conversa real. Rode uma conversa contra este banco (ou aponte "
            "APP_DATABASE_URL para o banco da aplicação) para exercitar estes testes."
        )


def _plantar_run(sessao, *, conversation_id: str, tool_args: dict, indice: int = 0):
    """Escreve um `agno_runs` à mão, com a forma que o Agno 3.0.6 grava.

    À mão de propósito: fazer o modelo produzir um run custaria uma chamada real e
    tornaria o teste não determinístico, e o que está sob teste é a NOSSA leitura —
    não a escrita do Agno, que é código deles.

    A tabela **não** é criada aqui: ela é do Agno, e recriá-la de memória produziria
    uma estrutura sem as restrições da real — foi assim que a FK para `agno_sessions`
    passou despercebida até o teste rodar contra o banco de verdade.
    """
    # A tabela é do Agno e não está na lista que o `conftest` trunca entre testes —
    # sem esta limpeza, a segunda execução da suíte colide na chave primária.
    sessao.execute(
        # Por `run_id`, e não por `session_id`: apagar a sessão inteira a cada
        # plantio faria o teste de ORDEM inserir três runs e sobrar com um.
        text("delete from ai.agno_runs where run_id = :rid"),
        {"rid": f"run_{conversation_id}_{indice}"},
    )
    # E `agno_runs.session_id` tem FK para `agno_sessions`: a sessão precisa existir
    # antes do run. Descoberto pelo próprio teste — a estrutura real tem restrição que
    # um `create table` escrito de memória não teria.
    sessao.execute(
        text("""
            insert into ai.agno_sessions (session_id, session_type, created_at)
            values (:sid, 'agent', 0)
            on conflict (session_id) do nothing
        """),
        {"sid": conversation_id},
    )
    sessao.execute(
        text("""
            insert into ai.agno_runs
                (run_id, session_id, run_type, status, run_index, run_data, created_at)
            values (:rid, :sid, 'agent', 'COMPLETED', :idx, cast(:dados as jsonb), 0)
        """),
        {
            "rid": f"run_{conversation_id}_{indice}",
            "sid": conversation_id,
            "idx": indice,
            "dados": json.dumps({
                "model": "claude-opus-5",
                "model_provider": "Anthropic",
                "metrics": {
                    "duration": 3.6422,
                    "input_tokens": 581,
                    "output_tokens": 161,
                    "cache_read_tokens": 5182,
                },
                "tools": [{
                    "tool_name": "qualify_lead",
                    "tool_args": tool_args,
                    "result": "Registrado.",
                    "metrics": {"duration": 0.0078},
                    "tool_call_error": False,
                }],
            }),
        },
    )
    sessao.commit()


def test_o_CEP_dos_argumentos_NAO_sai_em_claro(sessao):
    """O teste que justifica o módulo.

    O CEP é gerado, nunca literal (CLAUDE.md 13b): o regex é exercitado no formato
    real e a varredura de segurança não tem o que achar no arquivo.
    """
    cep = cep_de("07")
    _plantar_run(
        sessao,
        conversation_id="conv_trace_pii",
        tool_args={"idade": 28, "cep": cep, "plano_id": "completo"},
    )

    itens = traces_da_conversa(sessao, "conv_trace_pii")

    assert len(itens) == 1
    args = itens[0]["tools"][0]["argumentos"]
    assert cep not in json.dumps(args, ensure_ascii=False), (
        "o CEP saiu em claro pelo endpoint de trace — `ai.agno_runs` é a única tabela "
        "que não mascara na escrita, e a leitura é a última barreira"
    )
    assert args["cep"] == "[CEP]"
    # O que NÃO é PII continua legível: um trace que mascara tudo não serve para nada.
    assert args["idade"] == 28
    assert args["plano_id"] == "completo"


def test_traz_a_granularidade_que_turn_usage_nao_tem(sessao):
    """Duração e tokens do turno, mais a duração de cada tool separadamente.

    `turn_usage` sabe que o turno custou 581 tokens; só o trace sabe que dentro dele
    houve uma execução de `qualify_lead` de 7,8 ms.
    """
    _plantar_run(
        sessao, conversation_id="conv_trace_metricas", tool_args={"idade": 30},
    )

    (item,) = traces_da_conversa(sessao, "conv_trace_metricas")

    assert item["tokens_in"] == 581
    assert item["tokens_out"] == 161
    assert item["cache_read"] == 5182
    assert item["duracao_ms"] == pytest.approx(3642.2, abs=0.5)
    assert item["tools"][0]["nome"] == "qualify_lead"
    assert item["tools"][0]["duracao_ms"] == pytest.approx(7.8, abs=0.1)
    assert item["tools"][0]["erro"] is False


def test_conversa_sem_execucao_devolve_lista_vazia_e_nao_erro(sessao):
    """Conversa do dataset reproduzida fora do caminho de produção não tem run.

    Lista vazia e não 404: a conversa existe, o trace é que não. Confundir as duas
    coisas faria o detalhe mostrar "não encontrado" para uma conversa que está ali.
    """
    assert traces_da_conversa(sessao, "conv_que_nunca_rodou") == []


def test_a_ordem_e_por_run_index(sessao):
    """Mesma regra da transcrição: ordem por índice, nunca por timestamp."""
    for i in (2, 0, 1):
        _plantar_run(
            sessao, conversation_id="conv_trace_ordem",
            tool_args={"idade": 30}, indice=i,
        )

    itens = traces_da_conversa(sessao, "conv_trace_ordem")
    assert [i["index"] for i in itens] == [0, 1, 2]
