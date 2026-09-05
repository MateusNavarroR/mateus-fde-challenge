"""O relatório do replay: o que rodou, o que não rodou, e por quê.

**A regra que dá forma ao módulo:** um replay que morre na conversa 18 e não diz que
morreu é pior que um replay que não roda. Por isso o relatório sempre existe — ele é
escrito no `finally` do executor —, sempre traz `completadas`, `falhadas` e a razão de
cada falha, e sempre diz quantas conversas a amostra tinha. Um numerador sem denominador
é a forma mais educada de mentir.

**PII.** As falas do lead entram cruas no agente (`casos.py`) e **nada cru sai daqui**:
`_limpo` passa todo texto por `app.privacy.mascarar` antes de serializar. Isso vale para
a mensagem de erro do provedor, que pode ecoar o prompt — e o prompt carrega a fala do
lead. A saída default vive em `qa/_saida/`, que é ignorado pelo Git por construção
(`qa.dataset.caminhos.dir_saida`), mas a defesa não depende disso: depende do
mascaramento.

**O relatório é lido de volta.** `de_json` existe porque a comparação entre duas
execuções — antes e depois de uma mudança de prompt — é o uso principal do artefato, e
uma comparação feita a olho num JSON de 30 conversas não acontece.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.privacy.mascarar import mascarar
from qa.replay.assercoes import Desfecho
from qa.replay.falhas import ClasseDeFalha, Falha

#: Acima disto a suíte reprova por incompreensão do respondedor, não por defeito do
#: agente. 20% das perguntas é generoso e ainda assim vermelho muito antes de o número
#: virar decorativo: com o script cobrindo dois campos de cinco, uma taxa dessas
#: significa que o agente está perguntando outra coisa e ninguém percebeu.
LIMIAR_NAO_ENTENDI = 0.20

#: Segundos de parede por inferência, medido no cenário de referência (§9). Só alimenta
#: a estimativa impressa antes de começar — nunca uma asserção.
SEGUNDOS_POR_INFERENCIA = 3.0


def _limpo(texto: str | None, limite: int = 400) -> str | None:
    """Mascara e trunca. Único caminho de texto para dentro do relatório."""
    if texto is None:
        return None
    return mascarar(texto[:limite])


@dataclass
class ExtracaoConferida:
    """Três campos, e só três: idade, `veiculo_ano` e CEP (DECISOES-FECHADAS §9).

    Marca e modelo ficam fora porque `veiculo_texto` contém informação que o lead nunca
    disse, e penalizar por isso mede o ruído do gabarito.

    O CEP aparece como **acerto ou erro**, nunca como valor: ele é PII, e o relatório é
    um artefato que alguém vai colar num README.
    """

    esperado_idade: int | None = None
    obtido_idade: int | None = None
    esperado_veiculo_ano: int | None = None
    obtido_veiculo_ano: int | None = None
    #: Só o veredito. Nem o esperado nem o obtido.
    cep_correto: bool | None = None

    @property
    def acertos(self) -> int:
        certos = 0
        if self.esperado_idade is not None and self.esperado_idade == self.obtido_idade:
            certos += 1
        if (
            self.esperado_veiculo_ano is not None
            and self.esperado_veiculo_ano == self.obtido_veiculo_ano
        ):
            certos += 1
        if self.cep_correto:
            certos += 1
        return certos

    @property
    def comparaveis(self) -> int:
        """Quantos dos três o dataset oferecia gabarito para.

        Campo sem gabarito não conta como erro do agente — contar rebaixaria a taxa por
        culpa do corpus.
        """
        return sum(
            1
            for presente in (
                self.esperado_idade is not None,
                self.esperado_veiculo_ano is not None,
                self.cep_correto is not None,
            )
            if presente
        )


@dataclass
class ResultadoConversa:
    """Uma linha do relatório. Uma conversa."""

    conversation_id: str
    estrato: str
    outcome_dataset: str
    inferencias: int = 0
    turnos: int = 0

    desfecho_esperado: str = str(Desfecho.INCOMPLETO)
    desfecho_obtido: str = str(Desfecho.INCOMPLETO)
    motivo_esperado: str | None = None
    motivo_obtido: str | None = None

    tools_chamadas: list[str] = field(default_factory=list)
    tools_faltando: list[str] = field(default_factory=list)
    tools_proibidas_chamadas: list[str] = field(default_factory=list)
    reliability: str | None = None

    extracao: ExtracaoConferida = field(default_factory=ExtracaoConferida)

    preco_alcancavel: bool | None = None
    preco_exato: bool | None = None

    #: O CASO do dataset contém mídia sem transcrição.
    tem_midia: bool = False
    #: Quantas mídias foram DE FATO enviadas nesta execução.
    #:
    #: Diferente de `tem_midia`: o laço para no estado terminal, e em algumas conversas
    #: a mídia do dataset vem depois da cotação — o vendedor humano cotou no turno 9,
    #: nosso agente cota no 4, e os anexos nunca chegam a ser enviados. A política de
    #: mídia não foi exercitada ali, e contar como falha mede o instrumento.
    midias_enviadas: int = 0
    #: `None` quando nenhuma mídia foi enviada: não é sucesso nem falha, é ausência
    #: de caso.
    midia_tratada: bool | None = None

    #: Quantas vezes o lead objetou preço/franquia/concorrente nesta conversa.
    objecoes: int = 0

    perguntas_do_agente: int = 0
    nao_entendi: int = 0

    falha: dict[str, Any] | None = None
    segundos: float = 0.0

    @property
    def completou(self) -> bool:
        return self.falha is None

    @property
    def passou(self) -> bool:
        """O veredito por conversa. Falha de provedor **não** reprova o agente.

        Separar as duas coisas é o ponto inteiro do módulo: 402 é uma conta sem crédito,
        não um agente ruim, e somá-los produziria uma taxa de acerto que cai quando o
        cartão vence.
        """
        if self.falha is not None:
            return False
        if self.tools_faltando or self.tools_proibidas_chamadas:
            return False
        if self.desfecho_obtido != self.desfecho_esperado:
            return False
        if self.desfecho_esperado == str(Desfecho.REFUSED):
            if self.motivo_obtido != self.motivo_esperado:
                return False
        if self.preco_exato is False:
            return False
        if self.tem_midia and self.midia_tratada is False:
            return False
        return True


@dataclass
class Relatorio:
    """O artefato. Sempre escrito, mesmo quando a execução morre no meio."""

    modo: str
    modelo: str
    seed: int
    conversas_pedidas: int = 0
    inferencias_previstas: int = 0
    iniciado_em: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    terminado_em: str | None = None
    #: Preenchido quando a execução parou antes da última conversa (402, Ctrl-C).
    interrompido_por: str | None = None

    resultados: list[ResultadoConversa] = field(default_factory=list)
    #: Distribuição da amostra, para o relatório se explicar sozinho.
    estratificacao: dict[str, Any] = field(default_factory=dict)
    limiar_nao_entendi: float = LIMIAR_NAO_ENTENDI
    segundos_de_espera: float = 0.0
    #: O que os evals NATIVOS do Agno gravaram em `ai.eval_runs` nesta execução.
    #:
    #: Vazio quando o replay rodou sem `--evals`, e essa distinção importa: um
    #: relatório sem esta chave diz "não avaliei", enquanto zeros dentro dela dizem
    #: "avaliei e nada passou". Eram indistinguíveis enquanto os evals não rodavam.
    evals: dict[str, Any] = field(default_factory=dict)

    # ─── contagens ───────────────────────────────────────────────────────────

    @property
    def completadas(self) -> int:
        return sum(1 for r in self.resultados if r.completou)

    @property
    def falhadas(self) -> int:
        return sum(1 for r in self.resultados if not r.completou)

    @property
    def nao_alcancadas(self) -> int:
        """Conversas da amostra que a execução nunca chegou a tocar.

        Existe separada de `falhadas` porque são coisas diferentes: uma conversa que
        falhou foi tentada, uma não alcançada não foi. Somá-las esconderia onde a
        execução parou.
        """
        return max(0, self.conversas_pedidas - len(self.resultados))

    @property
    def falhas_por_classe(self) -> dict[str, int]:
        contagem: dict[str, int] = {}
        for r in self.resultados:
            if r.falha:
                classe = str(r.falha.get("classe"))
                contagem[classe] = contagem.get(classe, 0) + 1
        return contagem

    @property
    def aprovados(self) -> int:
        return sum(1 for r in self.resultados if r.passou)

    @property
    def por_grupo(self) -> dict[str, dict[str, int]]:
        """`{grupo: {n, aprovados, completadas}}` — os grupos que a cobertura exige.

        Os quatro primeiros são a partição de elegibilidade; `midia` e `objecao` são
        transversais e cortam os outros. Um mesmo caso aparece em dois grupos, e isso
        é correto: a pergunta não é "de que grupo é a conversa", é "o agente acerta
        nas conversas que têm esta característica".
        """
        grupos: dict[str, list[ResultadoConversa]] = {}
        for r in self.resultados:
            grupos.setdefault(r.estrato, []).append(r)
            # O grupo é de quem RECEBEU mídia, não de quem tinha mídia no caso: um
            # grupo que inclui conversas onde a política nunca foi exercitada mede o
            # laço do replay em vez do agente.
            if r.midias_enviadas > 0:
                grupos.setdefault("midia", []).append(r)
            if r.objecoes >= 1:
                grupos.setdefault("objecao", []).append(r)
            if r.objecoes >= 2:
                grupos.setdefault("objecao_repetida", []).append(r)
        return {
            nome: {
                "n": len(rs),
                "completadas": sum(1 for r in rs if r.completou),
                "aprovados": sum(1 for r in rs if r.passou),
            }
            for nome, rs in sorted(grupos.items())
        }

    @property
    def taxa_de_acerto(self) -> float | None:
        """Sobre as **completadas**, não sobre as pedidas.

        E devolve `None` quando nenhuma completou, em vez de 0,0: zero acertos em zero
        conversas é indefinido, e imprimir "0%" convidaria alguém a ler uma execução que
        não rodou como uma execução que falhou tudo.
        """
        base = self.completadas
        return None if base == 0 else self.aprovados / base

    @property
    def extracao_por_campo(self) -> dict[str, dict[str, int]]:
        campos = {
            "idade": ("esperado_idade", "obtido_idade"),
            "veiculo_ano": ("esperado_veiculo_ano", "obtido_veiculo_ano"),
        }
        saida: dict[str, dict[str, int]] = {}
        for nome, (esperado, obtido) in campos.items():
            comparaveis = [
                r.extracao for r in self.resultados
                if getattr(r.extracao, esperado) is not None
            ]
            saida[nome] = {
                "comparaveis": len(comparaveis),
                "acertos": sum(
                    1 for e in comparaveis if getattr(e, esperado) == getattr(e, obtido)
                ),
            }
        ceps = [r.extracao for r in self.resultados if r.extracao.cep_correto is not None]
        saida["cep"] = {
            "comparaveis": len(ceps),
            "acertos": sum(1 for e in ceps if e.cep_correto),
        }
        return saida

    @property
    def taxa_nao_entendi(self) -> float:
        perguntas = sum(r.perguntas_do_agente for r in self.resultados)
        if perguntas == 0:
            return 0.0
        return sum(r.nao_entendi for r in self.resultados) / perguntas

    @property
    def respondedor_reprovou(self) -> bool:
        """O script não deu conta das perguntas do agente acima do limiar.

        Quando isto é verdade, **a suíte reprova mesmo que o agente tenha ido bem** — e
        a mensagem tem que dizer que o motivo é o harness, não o agente. Fragilidade
        visível em vez de silenciosa: sem esta linha, um respondedor que parou de casar
        produziria uma queda de desfechos que alguém debugaria no prompt por dois dias.
        """
        return self.taxa_nao_entendi > self.limiar_nao_entendi

    @property
    def aprovado(self) -> bool:
        return (
            self.completadas > 0
            and self.falhadas == 0
            and self.nao_alcancadas == 0
            and not self.respondedor_reprovou
            and self.aprovados == self.completadas
        )

    # ─── serialização ────────────────────────────────────────────────────────

    def para_dict(self) -> dict[str, Any]:
        dados = asdict(self)
        dados["resumo"] = {
            "conversas_pedidas": self.conversas_pedidas,
            "completadas": self.completadas,
            "falhadas": self.falhadas,
            "nao_alcancadas": self.nao_alcancadas,
            "aprovados": self.aprovados,
            "taxa_de_acerto": self.taxa_de_acerto,
            "por_grupo": self.por_grupo,
            "falhas_por_classe": self.falhas_por_classe,
            "extracao_por_campo": self.extracao_por_campo,
            "taxa_nao_entendi": self.taxa_nao_entendi,
            "respondedor_reprovou": self.respondedor_reprovou,
            "aprovado": self.aprovado,
        }
        return dados

    def escrever(self, destino: Path) -> Path:
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(
            json.dumps(self.para_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return destino


def de_dict(dados: dict[str, Any]) -> Relatorio:
    """Parser. O `resumo` é **derivado** e por isso descartado na leitura.

    Reconstruí-lo das linhas em vez de confiar no que está escrito é o que impede um
    relatório editado à mão de afirmar 100% com 12 linhas vermelhas embaixo.
    """
    dados = dict(dados)
    dados.pop("resumo", None)
    resultados = [
        ResultadoConversa(
            **{
                **linha,
                "extracao": ExtracaoConferida(**(linha.get("extracao") or {})),
            }
        )
        for linha in dados.pop("resultados", [])
    ]
    return Relatorio(resultados=resultados, **dados)


def de_json(texto: str) -> Relatorio:
    return de_dict(json.loads(texto))


def ler(origem: Path) -> Relatorio:
    return de_json(origem.read_text(encoding="utf-8"))


def falha_para_dict(falha: Falha) -> dict[str, Any]:
    """`Falha` → linha do relatório, mascarada. Ver o docstring do módulo."""
    return {
        "classe": str(falha.classe),
        "mensagem": _limpo(falha.mensagem),
        "message_index": falha.message_index,
        "fatal": falha.fatal,
    }


# ─── render de texto ─────────────────────────────────────────────────────────


#: Abaixo disto, uma taxa é ruído com casas decimais. O relatório diz o tamanho da
#: amostra e se recusa a converter em percentual — que é o oposto de reportar "67%"
#: sobre três casos e deixar o leitor descobrir sozinho o denominador.
MINIMO_PARA_TAXA = 5

#: O que cada grupo prova, para o relatório dizer POR QUE aquele número importa.
SENTIDO_DO_GRUPO = {
    "so_idade": "incotável por idade: recusa com o motivo certo, sem escalar",
    "so_veiculo": "incotável por veículo: recusa + oferta de outro veículo",
    "ambos": "incotável pelos dois motivos ao mesmo tempo",
    "cotavel": "argumentos batendo com o gabarito — idade, ano e CEP",
    "midia": "mídia sem texto: o agente pede o dado por escrito",
    "objecao": "uma objeção NÃO encaminha — o agente trata e segue",
    "objecao_repetida": "objeção repetida encaminha (gatilho)",
}


def render_grupos(rel: Relatorio) -> list[str]:
    """O recorte por grupo, com o denominador sempre visível."""
    linhas = ["cobertura por grupo"]
    grupos = rel.por_grupo
    for nome, sentido in SENTIDO_DO_GRUPO.items():
        d = grupos.get(nome)
        if d is None or d["n"] == 0:
            linhas.append(f"  {nome:<18} n=0   AUSENTE — {sentido}")
            continue
        base = d["completadas"]
        if base < MINIMO_PARA_TAXA:
            veredito = f"amostra pequena (n={base}), sem taxa: {d['aprovados']}/{base}"
        else:
            veredito = f"{d['aprovados'] / base:.0%}  ({d['aprovados']}/{base})"
        linhas.append(f"  {nome:<18} n={d['n']:<4} {veredito}")
    return linhas


def render(rel: Relatorio) -> str:
    """A versão para o terminal. Curta, e obrigada a dizer o denominador."""
    linhas = [
        f"replay {rel.modo} · modelo {rel.modelo} · seed {rel.seed}",
        f"conversas ....... {rel.completadas}/{rel.conversas_pedidas} completadas"
        f"  ({rel.falhadas} falharam, {rel.nao_alcancadas} não alcançadas)",
    ]
    if rel.interrompido_por:
        linhas.append(f"INTERROMPIDO .... {rel.interrompido_por}")
    for classe, n in sorted(rel.falhas_por_classe.items()):
        linhas.append(f"  falha {classe:<16} {n}")

    taxa = rel.taxa_de_acerto
    linhas.append(
        "acerto .......... "
        + ("n/a (nenhuma conversa completou)" if taxa is None else f"{taxa:.0%}"
           f"  ({rel.aprovados}/{rel.completadas})")
    )
    if rel.modo == "extracao":
        for campo, n in rel.extracao_por_campo.items():
            base = n["comparaveis"]
            pct = "n/a" if base == 0 else f"{n['acertos'] / base:.0%}"
            linhas.append(f"  {campo:<14} {n['acertos']:>4}/{base:<4} {pct}")

    linhas.append(
        f"não entendi ..... {rel.taxa_nao_entendi:.0%}"
        f" (limiar {rel.limiar_nao_entendi:.0%})"
        + ("  ⇒ REPROVA: o harness, não o agente" if rel.respondedor_reprovou else "")
    )
    if rel.segundos_de_espera:
        linhas.append(f"esperando ....... {rel.segundos_de_espera:.0f}s em backoff")
    linhas.extend(render_grupos(rel))
    linhas.append(f"veredito ........ {'APROVADO' if rel.aprovado else 'REPROVADO'}")
    return "\n".join(linhas)


def estimativa_de_parede(inferencias: int) -> str:
    segundos = inferencias * SEGUNDOS_POR_INFERENCIA
    if segundos < 90:
        return f"~{segundos:.0f}s"
    if segundos < 5400:
        return f"~{segundos / 60:.0f} min"
    return f"~{segundos / 3600:.1f} h"


__all__ = [
    "ClasseDeFalha",
    "ExtracaoConferida",
    "LIMIAR_NAO_ENTENDI",
    "Relatorio",
    "ResultadoConversa",
    "de_dict",
    "de_json",
    "estimativa_de_parede",
    "falha_para_dict",
    "ler",
    "render",
]
