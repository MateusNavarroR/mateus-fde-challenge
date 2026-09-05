"""A ponte entre o replay e a tabela `ai.eval_runs` do Agno.

**Por que este módulo existe.** `assercoes.py` já sabia *montar* um `ReliabilityEval`
e um `AgentAsJudgeEval`, e os dois tinham parâmetro `db` desde o começo. Ninguém os
chamava fora dos testes. A consequência era pior do que "faltou uma feature": a tabela
`ai.eval_runs` nunca existia, `app/api/consultas.py::_evals()` caía no `except` e
devolvia zeros em silêncio, e o painel exibia um traço — indistinguível, para quem
opera, de "a avaliação rodou e nada passou". Enquanto isso `docs/EVALS.md`,
`docs/DECISOES-FECHADAS.md` e o invariante 27 do `CLAUDE.md` descreviam uma integração
fim a fim que não acontecia. Este arquivo é o que fecha essa distância.

**Três coisas que só se descobrem lendo o Agno 3.0.6 instalado, e cada uma quebraria
a integração em silêncio:**

1. **`eval_table="eval_runs"` é obrigatório e não é o default.** `PostgresDb` monta
   outro nome quando o argumento falta, e a consulta do painel é literal sobre
   `ai.eval_runs`. Sem passar o nome, tudo "funciona": os evals rodam, gravam numa
   tabela de outro nome, e o painel continua mostrando um traço.
2. **As duas classes têm assinaturas de `run()` diferentes.** `ReliabilityEval.run()`
   usa o `agent_response` que já veio no construtor; `AgentAsJudgeEval.run()` recebe
   `input=` e `output=` como **strings**. Quem assume simetria escreve uma chamada que
   levanta em runtime — e só no fim de um replay caro.
3. **A gravação é síncrona, dentro do `.run()`, e só acontece se `db` for truthy.** Não
   há flush posterior nem job separado; um `db=None` esquecido é um eval que roda,
   imprime um resultado correto e não deixa rastro.

**O que é avaliado por juiz de modelo, e o que nunca é.** Preço e elegibilidade têm
gabarito fechado — 72 prêmios possíveis e `plans.json` — e conferi-los com um juiz
trocaria uma conta exata por uma opinião cara. O juiz avalia só o que não tem conta: se
o texto da recusa fecha a porta com respeito ou promete o que ninguém vai cumprir. E
como esse texto vem de um mapa fixo nosso, ele roda **uma vez por motivo**, não uma vez
por conversa: são três chamadas de modelo por replay, independentemente do tamanho da
amostra.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

#: O nome que `app/api/consultas.py` consulta, literalmente. Ver ponto 1 do módulo.
TABELA = "eval_runs"


def db_de_evals(db_url: str) -> Any:
    """`PostgresDb` apontado para a tabela que o painel lê.

    Uma função e não uma constante porque a URL vem das settings em tempo de execução,
    e porque importar `agno.db` no topo faria o módulo inteiro depender do Agno — o
    harness precisa ser importável para testar a montagem sem o pacote presente.
    """
    from agno.db.postgres import PostgresDb

    return PostgresDb(db_url=db_url, eval_table=TABELA)


@dataclass
class Registro:
    """O que foi AVALIADO, e — separadamente — o que o banco de fato tem.

    **A distinção não é preciosismo, é um defeito real que apareceu no teste.** O Agno
    engole a falha de escrita: `log_eval_run` captura a exceção, emite um WARNING no
    logger e devolve o resultado como se nada tivesse acontecido. Com o banco fora do
    ar, `.run()` retorna um `PASSED` perfeito e a tabela continua vazia — de modo que
    um contador incrementado no retorno diria "20 gravados" sobre zero linhas.

    Por isso `avaliados` conta o que rodou, e `conferir_gravacao()` pergunta ao banco
    quantas linhas existem. O relatório publica o número do BANCO; a divergência entre
    os dois vira erro registrado, em vez de virar um número bonito e falso.
    """

    reliability_avaliados: int = 0
    reliability_passaram: int = 0
    juiz_avaliados: int = 0
    juiz_passaram: int = 0
    #: Linhas realmente presentes em `ai.eval_runs`, medidas depois da execução.
    linhas_no_banco: int | None = None
    erros: list[str] = field(default_factory=list)

    @property
    def total_avaliados(self) -> int:
        return self.reliability_avaliados + self.juiz_avaliados


def _passou(resultado: Any) -> bool:
    """`eval_status == "PASSED"`, com o mesmo nome de chave que o painel filtra.

    Lido do `ReliabilityResult` do Agno instalado. Se um dia a chave mudar de nome, a
    consulta do painel para de casar — e é por isso que existe um teste conferindo que
    o valor gravado bate com o que `_evals()` procura, em vez de duas cópias da string
    em lados opostos do sistema esperando não divergir.
    """
    return str(getattr(resultado, "eval_status", "")).upper() == "PASSED"


def gravar_reliability(
    caso: Any,
    expectativa: Any,
    runs: Sequence[Any],
    *,
    db: Any,
    registro: Registro,
) -> None:
    """Roda o `ReliabilityEval` de uma conversa e persiste o resultado.

    **Não levanta.** Um replay é caro e demorado; deixar a avaliação derrubar a
    execução inteira trocaria o dado que já foi produzido por um traceback. O erro vai
    para `registro.erros` e o relatório o mostra — que é a diferença entre uma falha
    conhecida e uma falha engolida.

    Devolve cedo quando não há tool obrigatória: `montar_reliability` já devolve `None`
    nesse caso, e forçar um eval sem expectativa gravaria um `PASSED` que não significa
    nada — um número que sobe sem nada ter sido verificado é pior que número nenhum.
    """
    from qa.replay import assercoes

    try:
        eval_ = assercoes.montar_reliability(caso, expectativa, runs, db=db)
        if eval_ is None:
            return
        resultado = eval_.run(print_results=False)
    except Exception as e:  # noqa: BLE001 — ver docstring
        registro.erros.append(f"{caso.conversation_id}: {type(e).__name__}: {e}")
        return

    registro.reliability_avaliados += 1
    if _passou(resultado):
        registro.reliability_passaram += 1


def gravar_juiz_das_recusas(*, db: Any, registro: Registro, model: Any = None) -> None:
    """Avalia os três textos de recusa — **uma vez por motivo**, não por conversa.

    O alvo é a NOSSA redação, que vem de um mapa fixo: o modelo não escreve nada no
    turno de recusa. Avaliá-la por conversa multiplicaria o custo por uma amostra sem
    produzir um único bit de informação nova, porque a entrada seria byte a byte a
    mesma. Três motivos, três chamadas, e o custo do replay não cresce com `n`.

    `input` e `output` como strings: `AgentAsJudgeEval.run()` tem assinatura diferente
    da do `ReliabilityEval` (ponto 2 do módulo), e passar `agent_response` aqui levanta.
    """
    from app import textos
    from app.contracts.quote import MotivoRecusa
    from qa.replay import assercoes

    for motivo in MotivoRecusa:
        texto = textos.POR_MOTIVO.get(motivo)
        if not texto:
            continue
        try:
            juiz = assercoes.montar_juiz_da_recusa(model=model, db=db)
            resultado = juiz.run(
                input=f"Um lead foi recusado pelo motivo: {motivo}.",
                output=texto,
            )
        except Exception as e:  # noqa: BLE001 — ver `gravar_reliability`
            registro.erros.append(f"juiz[{motivo}]: {type(e).__name__}: {e}")
            continue

        registro.juiz_avaliados += 1
        if _passou(resultado):
            registro.juiz_passaram += 1


def conferir_gravacao(engine: Any, registro: Registro) -> None:
    """Pergunta ao BANCO quantas linhas existem, e acusa a divergência.

    Existe porque o Agno não deixa a escrita falhar de forma observável (ver `Registro`).
    Sem esta conferência, o único jeito de descobrir que nada foi gravado seria abrir o
    painel depois e achar estranho o traço — que é como o defeito original sobreviveu
    tanto tempo.

    Não levanta: um replay que terminou não pode morrer na hora de se medir.
    """
    from sqlalchemy import text as _sql

    # `to_regclass` devolve NULL em vez de levantar quando a tabela não existe, e a
    # distinção importa: tabela ausente é o resultado esperado de "nada gravou", e
    # tratá-la como erro de conferência esconderia justamente o diagnóstico útil
    # atrás de um traceback de SQL. Erro de conferência é o outro caso — a conexão
    # caiu, e aí não sabemos nada.
    try:
        with engine.connect() as c:
            existe = c.execute(
                _sql(f"select to_regclass('ai.{TABELA}') is not null")
            ).scalar_one()
            registro.linhas_no_banco = (
                int(c.execute(_sql(f"select count(*) from ai.{TABELA}")).scalar_one())
                if existe
                else 0
            )
    except Exception as e:  # noqa: BLE001 — ver docstring
        registro.erros.append(f"conferência: {type(e).__name__}: {e}")
        return

    if registro.linhas_no_banco < registro.total_avaliados:
        registro.erros.append(
            f"{registro.total_avaliados} evals rodaram e o banco tem "
            f"{registro.linhas_no_banco} linhas — o Agno engoliu erro de escrita"
        )
