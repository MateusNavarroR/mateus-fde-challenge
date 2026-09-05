"""A execução do replay: injeta as falas, observa o banco, monta o relatório.

**Dois modos, e a diferença entre eles é o que se pergunta ao corpus.**

- **`extracao`** injeta as falas e afere o que foi extraído. Gabarito: a coluna
  `lead_idade_informada`, o ano de `veiculo_texto` e o CEP que o lead pronunciou. Três
  campos, e só três (`casos.py` explica por que marca e modelo ficam fora). O respondedor
  roteirizado fica **desligado** aqui: `data_inicio` e `plano_id` não têm gabarito e não
  são medidos, e injetar respostas para eles gastaria inferência sem mudar a medição.
- **`desfecho`** exercita a cadeia inteira até `cotado`, `refused` ou `encaminhado`, com
  o respondedor ligado. Para na primeira conversa que chega a estado terminal: as falas
  seguintes são o lead continuando a negociar, e continuar custaria inferência sem mudar
  o desfecho que se está medindo.

**O caminho exercitado é o de produção.** O executor chama `app.agent.turno.responder` —
a mesma função que o canal web chama — e observa o resultado **no banco**, não em
variáveis suas. Reimplementar a regra de descarte ou a avaliação dos gatilhos aqui faria
o replay medir a si mesmo.

**Falhas do provedor não matam a execução.** `responder` captura `Exception` de forma
ampla ao redor de `agente.run`: um 402 chegaria ao relatório disfarçado de "conversa que
respondeu estranho". Por isso o executor não usa `try/except` para detectá-las — ele
compara o tamanho de `coletor.falhas` antes e depois de cada turno (`captura.py`). Rate
limit espera e retenta; 402 encerra a execução **com relatório**, porque o free tier do
Ollama Cloud devolve 402 em três dos quatro modelos e insistir só produziria mais 402.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Sequence

from qa.replay import amostra as amostragem
from qa.replay import assercoes, precos
from qa.replay.captura import Coletor, capturando
from qa.replay.casos import CasoReplay
from qa.replay.falhas import Backoff, ClasseDeFalha, Falha, TENTATIVAS
from qa.replay.relatorio import (
    ExtracaoConferida,
    Relatorio,
    ResultadoConversa,
    falha_para_dict,
)
from qa.replay.respondedor import RespondedorRoteirizado

#: Quantas respostas roteirizadas o executor injeta por fala do lead antes de seguir em
#: frente. Dois é o número de buracos do script: se o agente ainda estiver perguntando
#: depois de responder plano e data, insistir vira laço — e o laço apareceria no
#: relatório como custo, não como defeito.
MAX_INJECOES_POR_FALA = 2

ESTADOS_TERMINAIS = ("cotado", "encaminhado", "fechado")


class Modo(str, Enum):
    EXTRACAO = "extracao"
    DESFECHO = "desfecho"

    def __str__(self) -> str:
        return self.value


@dataclass
class AdaptadorDeReplay:
    """`ChannelAdapter` de mentira: acumula o que sairia para o lead.

    `send` aceita `**extras` de propósito. `turno.responder` passa `index` e `status`,
    que o `ConsoleAdapter` não declara — engolir os extras aqui evita que o replay
    quebre por uma diferença de assinatura entre canais que não tem nada a ver com o
    que ele mede.
    """

    name: str = "replay"
    enviadas: list[dict[str, Any]] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.enviadas = []

    async def send(
        self,
        conversation_id: str,
        text: str,
        *,
        message_id: str = "",
        quote_id: str | None = None,
        autor: str = "agente",
        **extras: Any,
    ) -> str:
        self.enviadas.append(
            {"text": text, "autor": autor, "quote_id": quote_id, "message_id": message_id}
        )
        return f"replay:{message_id}"

    async def typing(self, conversation_id: str, *, ativo: bool) -> None:
        return None

    def desde(self, marca: int) -> list[str]:
        """As falas do agente a partir da marca — o que o respondedor lê."""
        return [m["text"] for m in self.enviadas[marca:]]


@dataclass
class Observacao:
    """O desfecho lido do banco, não deduzido do texto."""

    desfecho: assercoes.Desfecho
    motivo: str | None = None
    trigger_handoff: str | None = None
    premio: Any = None
    plano_id: str | None = None
    req_idade: int | None = None
    req_veiculo_ano: int | None = None
    req_cep: str | None = None
    idade: int | None = None
    veiculo_ano: int | None = None
    cep: str | None = None


def observar(sessao, conversation_id: str) -> Observacao:
    """Lê `conversations`, `quotes` e `handoffs`. A fonte da verdade é o banco.

    Precedência: handoff vence cotação. Um handoff depois de uma cotação recusada seria
    o defeito que a §2 proíbe — recusa não cria handoff — e ler a cotação primeiro
    esconderia exatamente esse defeito.
    """
    from sqlalchemy import select

    from app.persistence.models import Conversation, Handoff, Quote

    conv = sessao.get(Conversation, conversation_id)
    handoff = sessao.execute(
        select(Handoff)
        .where(Handoff.conversation_id == conversation_id)
        .order_by(Handoff.criado_em.desc())
    ).scalars().first()
    cotacao = sessao.execute(
        select(Quote)
        .where(Quote.conversation_id == conversation_id)
        .order_by(Quote.criado_em.desc())
    ).scalars().first()

    base = {
        "idade": getattr(conv, "idade", None),
        "veiculo_ano": getattr(conv, "veiculo_ano", None),
        "cep": getattr(conv, "cep", None),
    }
    if cotacao is not None:
        base.update(
            premio=cotacao.premio_mensal,
            plano_id=cotacao.req_plano_id,
            req_idade=cotacao.req_idade,
            req_veiculo_ano=cotacao.req_veiculo_ano,
            req_cep=cotacao.req_cep,
        )

    if handoff is not None:
        # `lead_aceitou_cotacao` NÃO é um desvio do desfecho — é a consequência dele.
        #
        # O gatilho nasce de uma cotação entregue e aceita: o fluxo feliz inteiro
        # aconteceu. Contá-lo como `encaminhado` faria toda conversa que dá certo até o
        # fim aparecer como se tivesse escapado do agente, e a taxa de acerto cairia
        # medindo o INSTRUMENTO em vez do agente. O trigger continua registrado, para
        # quem quiser contar quantos aceites houve.
        aceitou = (
            str(handoff.trigger) == "lead_aceitou_cotacao"
            and cotacao is not None
            and cotacao.status == "ok"
        )
        if not aceitou:
            return Observacao(
                desfecho=assercoes.Desfecho.ENCAMINHADO,
                trigger_handoff=handoff.trigger,
                motivo=handoff.trigger,
                **base,
            )
        return Observacao(
            desfecho=assercoes.Desfecho.OK, trigger_handoff=handoff.trigger, **base,
        )
    if cotacao is not None and cotacao.status == "ok":
        return Observacao(desfecho=assercoes.Desfecho.OK, **base)
    if cotacao is not None and cotacao.status == "refused":
        return Observacao(
            desfecho=assercoes.Desfecho.REFUSED, motivo=cotacao.motivo_recusa, **base
        )
    return Observacao(desfecho=assercoes.Desfecho.INCOMPLETO, **base)


# ─── o laço de uma conversa ──────────────────────────────────────────────────


@dataclass
class Executor:
    """Estado de uma execução inteira. Um por invocação, nunca reusado.

    `sessao_factory`, `responder` e `dormir` são injetáveis para que a suíte do harness
    exercite o laço, a estratificação e a resiliência **sem banco, sem modelo e sem
    dormir de verdade** — que é o que permite testar o replay sem rodá-lo.
    """

    modo: Modo = Modo.DESFECHO
    seed: int = 20260904
    ano_corrente: int | None = None
    parar_no_402: bool = True
    max_injecoes: int = MAX_INJECOES_POR_FALA
    #: Injetáveis. Default: o caminho de produção.
    sessao_factory: Callable[[], Any] | None = None
    #: `id do dataset → id da nossa conversa`, preenchido durante a execução.
    conversas_criadas: dict[str, str] = field(default_factory=dict)
    responder: Callable[..., Any] | None = None
    backoff: Backoff | None = None
    modelo: str = ""
    #: `PostgresDb` apontado para `ai.eval_runs`, ou `None` para não avaliar.
    #:
    #: Opcional de propósito: a suíte do harness roda o laço inteiro sem banco, e um
    #: `db` obrigatório aqui a obrigaria a subir Postgres para testar amostragem.
    #: Quem quer o número no painel liga com `--evals`; quem quer só o replay, não.
    db_evals: Any = None
    registro_evals: Any = None

    def __post_init__(self) -> None:
        if self.backoff is None:
            self.backoff = Backoff(seed=self.seed)
        if self.registro_evals is None:
            from qa.replay.evals import Registro

            self.registro_evals = Registro()

    def _engine_de_evals(self):
        """A engine para conferir o que foi gravado. Do mesmo banco do `db_evals`."""
        from sqlalchemy import create_engine

        from app.config import get_settings

        return create_engine(get_settings().database_url)

    def _fabrica(self):
        if self.sessao_factory is not None:
            return self.sessao_factory()
        from app.persistence.db import sessao_factory

        return sessao_factory()()

    async def _turno(
        self,
        coletor: Coletor,
        conversation_id: str,
        texto: str,
        adaptador,
        tipo: str = "text",
        sessao=None,
    ) -> Falha | None:
        """Um turno, com retentativa. Devolve a falha que sobrou, ou `None`.

        A falha é detectada por **delta no coletor**, não por `except`: `responder` já
        capturou a exceção lá dentro e devolveu normalmente. Ver o docstring do módulo.
        """
        responder = self.responder
        if responder is None:
            from app.agent.turno import responder as responder_producao

            responder = responder_producao

        # ⚠️ **A fala do lead é PERSISTIDA antes do turno**, como `processar_turno_web`
        # faz em produção — e não era.
        #
        # O efeito medido: o replay gravava 157 mensagens do agente, 32 do sistema e
        # **zero do lead**. `repo.midias_do_lead()` conta `messages` com `autor='lead'`
        # e `tipo != 'text'`, então devolvia 0 sempre, e `MIDIA_SEM_TEXTO` não tinha
        # como disparar por mais que o `tipo` atravessasse o replay. Foram 4 das 5
        # reprovações de uma execução — todas com desfecho de negócio CERTO.
        #
        # Em produção o gatilho funciona, porque lá a fala é gravada. Era o harness
        # que não exercitava o caminho inteiro.
        #
        # O segundo prejuízo era de evidência: os transcripts exportados mostravam só
        # um lado da conversa, e um transcript sem as perguntas não deixa ninguém
        # entender por que o agente respondeu aquilo.
        if sessao is not None:
            from app.persistence import repo as _repo

            _repo.gravar_mensagem(
                sessao, conversation_id, autor="lead", conteudo=texto,
                status="received", tipo=tipo,
            )
            sessao.commit()

        tentativa = 0
        while True:
            antes = len(coletor.falhas)
            coletor.message_index = None
            await responder(
                conversation_id, texto, adaptador,
                chegada_do_lead=time.monotonic(), tipo=tipo,
            )
            if len(coletor.falhas) == antes:
                return None

            falha = coletor.falhas[-1]
            tentativa += 1
            if tentativa > TENTATIVAS.get(falha.classe, 0):
                return falha
            self.backoff.esperar(tentativa)  # type: ignore[union-attr]

    async def rodar_conversa(
        self, caso: CasoReplay, coletor: Coletor
    ) -> ResultadoConversa:
        from app.persistence import repo

        adaptador = AdaptadorDeReplay()
        respondedor = RespondedorRoteirizado(conversation_id=caso.conversation_id)
        resultado = ResultadoConversa(
            conversation_id=caso.conversation_id,
            estrato=amostragem.estrato_de(caso),
            outcome_dataset=caso.outcome,
            inferencias=caso.inferencias,
            tem_midia=caso.tem_midia_sem_transcricao,
            objecoes=caso.objecoes,
        )
        expectativa = assercoes.esperado_para(caso)
        resultado.desfecho_esperado = str(expectativa.desfecho)
        resultado.motivo_esperado = expectativa.motivo_recusa

        t0 = time.monotonic()
        sessao = self._fabrica()
        try:
            conv = repo.criar_conversa(
                sessao, channel="replay", external_ref=f"replay:{caso.conversation_id}"
            )
            sessao.commit()
            conversation_id = conv.id
            coletor.conversation_id = conversation_id
            # Guardado para que a evidência possa ser exportada depois: o relatório
            # cita o id do DATASET, e o banco conhece o NOSSO. Sem os dois, ir do
            # relatório ao transcript vira adivinhação.
            self.conversas_criadas[caso.conversation_id] = conversation_id

            falha = await self._injetar(
                caso, coletor, conversation_id, adaptador, respondedor, sessao
            )

            resultado.turnos = len(coletor.runs)
            resultado.perguntas_do_agente = respondedor.perguntas
            resultado.nao_entendi = respondedor.nao_entendi

            if falha is not None:
                resultado.falha = falha_para_dict(falha)
                resultado.desfecho_obtido = str(assercoes.Desfecho.FALHOU)
                return resultado

            sessao.expire_all()
            obs = observar(sessao, conversation_id)
            self._conferir(caso, expectativa, obs, coletor, adaptador, resultado)
            return resultado
        finally:
            resultado.segundos = time.monotonic() - t0
            sessao.close()

    async def _injetar(
        self, caso, coletor, conversation_id, adaptador, respondedor, sessao
    ) -> Falha | None:
        """As falas, em ordem de `message_index`, com o script nos dois buracos."""
        from app.persistence import repo

        for fala in caso.falas:
            coletor.message_index = fala.message_index
            marca = len(adaptador.enviadas)
            # ⚠️ O `tipo` da fala vai junto, e sem ele o estrato de mídia mede a
            # coisa errada: uma fala `[documento] CNH_frente.pdf` chegava ao agente
            # como TEXTO comum, `messages.tipo` gravava `text`, e `MIDIA_SEM_TEXTO`
            # não tinha como disparar. A política de mídia nunca era exercitada — e a
            # taxa do grupo media se o modelo, por conta própria, reagia a uma string
            # que parecia um anexo.
            falha = await self._turno(
                coletor, conversation_id, fala.texto, adaptador, tipo=fala.tipo,
                sessao=sessao,
            )
            if falha is not None:
                return falha

            if self.modo is Modo.DESFECHO:
                for _ in range(self.max_injecoes):
                    resposta = self._resposta_roteirizada(
                        respondedor, adaptador.desde(marca)
                    )
                    if resposta is None:
                        break
                    marca = len(adaptador.enviadas)
                    falha = await self._turno(
                        coletor, conversation_id, resposta, adaptador, sessao=sessao,
                    )
                    if falha is not None:
                        return falha

                sessao.expire_all()
                conv = repo.obter_conversa(sessao, conversation_id)
                if conv is not None and conv.state in ESTADOS_TERMINAIS:
                    # Terminal: as falas seguintes são o lead continuando a negociar.
                    break
        return None

    @staticmethod
    def _resposta_roteirizada(respondedor, falas_do_agente: Sequence[str]) -> str | None:
        """A última fala do agente é a que vale — as anteriores do mesmo turno são
        aviso de espera e bloco de cotação, que não são perguntas."""
        resposta = None
        for fala in falas_do_agente:
            resposta = respondedor.responder(fala) or resposta
        return resposta

    def _conferir(
        self, caso, expectativa, obs: Observacao, coletor, adaptador, resultado
    ) -> None:
        chamadas = coletor.chamadas_de_tool()
        resultado.tools_chamadas = sorted(set(chamadas))

        # O `ReliabilityEval` do Agno, com persistência, ao lado da nossa própria
        # conferência — e não no lugar dela. As duas medem coisas diferentes:
        # `conferir_tools` responde "faltou alguma obrigatória, chamou alguma
        # proibida" e alimenta o relatório do replay; o eval nativo grava em
        # `ai.eval_runs`, que é o que o painel lê e o que o invariante 27 promete.
        # Trocar uma pela outra perderia metade — a nossa cobre o "não deve chamar",
        # que `expected_tool_calls` não expressa.
        if self.db_evals is not None:
            from qa.replay import evals as _evals

            _evals.gravar_reliability(
                caso, expectativa, coletor.runs,
                db=self.db_evals, registro=self.registro_evals,
            )

        faltando, proibidas = assercoes.conferir_tools(expectativa, chamadas)
        resultado.tools_faltando = list(faltando)
        resultado.tools_proibidas_chamadas = list(proibidas)

        resultado.desfecho_obtido = str(obs.desfecho)
        resultado.motivo_obtido = obs.motivo

        if obs.trigger_handoff == "cotacao_indisponivel":
            # A `/quote` falhou depois de esgotadas as tentativas. É comportamento
            # correto do agente sob dependência caída — não é veredito sobre ele, e
            # contá-lo como erro faria a taxa de acerto oscilar com `FAILURE_RATE`.
            resultado.falha = falha_para_dict(
                Falha(
                    classe=ClasseDeFalha.INDISPONIVEL,
                    mensagem="a /quote não respondeu depois de esgotadas as tentativas",
                    conversation_id=caso.conversation_id,
                )
            )
            return

        if self.modo is Modo.EXTRACAO or expectativa.tools_obrigatorias:
            resultado.extracao = ExtracaoConferida(
                esperado_idade=caso.gabarito.idade,
                obtido_idade=obs.idade,
                esperado_veiculo_ano=caso.gabarito.veiculo_ano,
                obtido_veiculo_ano=obs.veiculo_ano,
                cep_correto=(
                    None
                    if caso.gabarito.cep is None
                    else obs.cep == caso.gabarito.cep
                ),
            )

        if obs.desfecho is assercoes.Desfecho.OK and obs.premio is not None:
            conferencia = precos.conferir(
                premio=obs.premio,
                plano_id=obs.plano_id or "",
                idade=obs.req_idade or 0,
                veiculo_ano=obs.req_veiculo_ano or 0,
                cep=obs.req_cep,
                ano_corrente=self.ano_corrente,
            )
            resultado.preco_alcancavel = conferencia.alcancavel
            resultado.preco_exato = conferencia.exato

        if caso.tem_midia_sem_transcricao:
            # `desfecho_correto` é o mesmo critério do resto do relatório, e não um
            # atalho: o desfecho bate com o esperado e, quando é recusa, o motivo
            # também. Sem isso, "chegou a um desfecho qualquer" contaria como tratar.
            correto = resultado.desfecho_obtido == resultado.desfecho_esperado and (
                resultado.desfecho_esperado != str(assercoes.Desfecho.REFUSED)
                or resultado.motivo_obtido == resultado.motivo_esperado
            )
            resultado.midia_tratada = assercoes.tratou_midia(
                [m["text"] for m in adaptador.enviadas],
                encaminhou=obs.desfecho is assercoes.Desfecho.ENCAMINHADO,
                midias=caso.midias,
                desfecho_correto=correto,
            )

    # ─── a execução inteira ──────────────────────────────────────────────────

    async def executar(self, estratificacao: amostragem.Estratificacao) -> Relatorio:
        """Roda a amostra. **O relatório existe mesmo se nada rodar.**

        Ele é construído antes do laço e devolvido pelo `finally`: uma execução que
        morre na conversa 18 devolve 17 linhas e diz por que parou, em vez de devolver
        um traceback e nenhum artefato.
        """
        rel = Relatorio(
            modo=str(self.modo),
            modelo=self.modelo or _modelo_configurado(),
            seed=self.seed,
            conversas_pedidas=len(estratificacao),
            inferencias_previstas=estratificacao.inferencias,
            estratificacao={
                "por_elegibilidade": estratificacao.por_elegibilidade,
                "por_outcome": estratificacao.por_outcome,
                "com_midia": estratificacao.com_midia,
            },
        )
        try:
            for caso in estratificacao.casos:
                coletor = Coletor()
                with capturando(coletor):
                    resultado = await self.rodar_conversa(caso, coletor)
                rel.resultados.append(resultado)

                if (
                    self.parar_no_402
                    and resultado.falha
                    and resultado.falha.get("classe") == str(ClasseDeFalha.PAGAMENTO)
                ):
                    rel.interrompido_por = (
                        "HTTP 402 do provedor — sem crédito para o modelo configurado; "
                        "as conversas restantes não foram tentadas"
                    )
                    break
        except KeyboardInterrupt:  # pragma: no cover - operação, não suíte
            rel.interrompido_por = "interrompido pelo operador (Ctrl-C)"
        finally:
            from datetime import datetime, timezone

            # O juiz roda UMA vez por execução, e não por conversa: o alvo é a nossa
            # redação fixa das três recusas, que é byte a byte a mesma em toda
            # conversa recusada. No `finally` porque uma execução interrompida no meio
            # ainda produziu texto para avaliar — e porque são três chamadas, não
            # trezentas.
            if self.db_evals is not None:
                from qa.replay import evals as _evals

                _evals.gravar_juiz_das_recusas(
                    db=self.db_evals, registro=self.registro_evals,
                )
                # E então PERGUNTA AO BANCO quantas linhas existem, em vez de
                # confiar no retorno: o Agno engole erro de escrita (loga um WARNING
                # e devolve o resultado como se tivesse gravado), então um contador
                # incrementado no retorno afirmaria gravações que nunca aconteceram.
                _evals.conferir_gravacao(self._engine_de_evals(), self.registro_evals)
                rel.evals = {
                    "reliability_avaliados": self.registro_evals.reliability_avaliados,
                    "reliability_passaram": self.registro_evals.reliability_passaram,
                    "juiz_avaliados": self.registro_evals.juiz_avaliados,
                    "juiz_passaram": self.registro_evals.juiz_passaram,
                    "linhas_no_banco": self.registro_evals.linhas_no_banco,
                    "erros": list(self.registro_evals.erros),
                }

            rel.terminado_em = datetime.now(timezone.utc).isoformat(timespec="seconds")
            rel.segundos_de_espera = self.backoff.esperado_s  # type: ignore[union-attr]
        return rel


def _modelo_configurado() -> str:
    try:
        from app.config import get_settings

        return get_settings().llm_model
    except Exception:  # noqa: BLE001 - o relatório não morre por causa do rótulo
        return "desconhecido"


def executar(
    casos: Sequence[CasoReplay],
    *,
    modo: Modo = Modo.DESFECHO,
    n: int = 30,
    seed: int = 20260904,
    **kwargs: Any,
) -> Relatorio:
    """Amostra, roda e devolve o relatório. O ponto de entrada síncrono."""
    estratificacao = amostragem.amostrar(casos, n=n, seed=seed)
    executor = Executor(modo=modo, seed=seed, **kwargs)
    return asyncio.run(executor.executar(estratificacao))
