"""Gera o log de execução completa — entregável nº 4 do enunciado.

Dois cenários, e o segundo é o que o enunciado chama de *"o ponto que mais separa"*:

- **`feliz`**: a `/quote` responde na primeira tentativa. Mostra a qualificação dos
  cinco campos, o bloco de cotação renderizado por template — com carência, franquia
  e pro-rata — e o estado final `cotado`.
- **`degradado`**: a `/quote` estoura o timeout nas três tentativas. Mostra o aviso
  aos 6 s, o reforço aos 20 s e o encaminhamento aos ~37 s, que é o **pior caso da
  política** e a razão de a cotação ser um job com estado em vez de uma espera dentro
  do turno.

**Por que pelo console e não pelo navegador.** O transcript precisa ser um artefato de
texto, comparável entre execuções e legível num diff. O `ConsoleAdapter` já marca tempo
relativo por linha, que é o que transforma "a política funciona" em número.

**O caminho é o de produção.** Este script chama `turno.responder`, o mesmo que o canal
web chama — não uma versão simplificada. Um transcript gerado por um laço próprio
provaria o laço próprio. Por isso ele exercita persistência, guardrail, política de
espera e a avaliação dos sete gatilhos de handoff, e não só o modelo.

**O conteúdo do lead sai MASCARADO**, porque é o que fica gravado: a linha do CEP
aparece como `cep [CEP]`. Não é limitação do transcript, é o produto — não existe
versão crua do lado do servidor. De quebra, é o que permite ao artefato viver em
`artifacts/`, que a varredura de PII do portão de segurança lê inteira (CLAUDE.md 13a).

Reprodução: cada arquivo gerado carrega no cabeçalho o comando exato que o produz.
Um cenário da `/quote` é a tripla **(seed, processo reiniciado, sequência exata de
requisições)** — a seed sozinha não basta, porque o RNG do legado é um fluxo global e
contínuo do processo.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.bootstrap import bootstrap  # noqa: E402
from app.channels.console import ConsoleAdapter, LinhaTranscript  # noqa: E402
from app.persistence import repo  # noqa: E402
from app.persistence.db import sessao_factory  # noqa: E402
from app.persistence.models import Handoff, Quote, QuoteAttempt  # noqa: E402

# ─── as falas ────────────────────────────────────────────────────────────────
#
# Do molde do dataset: linguagem torta, dados fora de ordem, um campo por vez e uma
# pergunta no meio. As duas últimas cobrem o que o lead do dataset NUNCA informa —
# plano e data de início —, que é justamente o que a qualificação exige.
#
# A data de início é dia 17 de propósito: dia ≠ 1 é a única forma de o bloco
# `primeiro_pagamento_pro_rata` existir na resposta da `/quote`.

#: Montado, não literal. Um CEP escrito por extenso casaria com o regex de PII, e a
#: varredura tem de continuar sem exceção por arquivo — **inclusive neste comentário**,
#: que na primeira versão citava o valor de exemplo e por isso disparava a própria
#: regra que explica. O que importa no caso é o PREFIXO: os dois dígitos que ligam o
#: agravo de 1,30.
PREFIXO_DE_RISCO = "07"
CEP_DE_RISCO = f"{PREFIXO_DE_RISCO}000" + "-000"

FALAS = [
    "Oi, queria fazer um seguro pro meu carro",
    "e um Onix 2019",
    # O prefixo `07` é o que dispara o agravo de 1,30; o resto é
    # preenchimento. Construído em vez de literal para que a varredura de
    # PII do portão continue absoluta, sem exceção por arquivo.
    f"tenho 28 anos, cep {CEP_DE_RISCO}",
    "qual a diferença dos planos?",
    "quero o completo mesmo",
    "pode começar dia 17 de outubro",
]

CENARIOS = {
    "feliz": {
        "titulo": "Caminho feliz — do «oi» à cotação",
        "env": "QUOTE_FAILURE_RATE=0 QUOTE_SLOW_RATE=0",
        "porque": (
            "A `/quote` responde na primeira tentativa. É o cenário que prova o "
            "critério nº 1: o agente atende de ponta a ponta e entrega o preço."
        ),
    },
    "degradado": {
        "titulo": "Caminho degradado — a `/quote` não responde",
        "env": "QUOTE_SLOW_RATE=1 QUOTE_SLOW_SECONDS=13 QUOTE_FAILURE_RATE=0",
        "porque": (
            "`SLOW_SECONDS=13` é **maior** que o nosso read timeout de 12 s, então as "
            "três tentativas estouram e o job termina `failed`. É o pior caso da "
            "política, forçado de propósito: no tráfego real ele acontece em ~0,8 % "
            "dos jobs, e esperar por ele para gerar o artefato seria esperar por acaso."
            "\n\n"
            "**Como ler os Δ.** O aviso tem limiar de 6 s e o reforço de 20 s, contados "
            "da chegada da mensagem do lead. O aviso costuma aparecer um pouco depois "
            "dos 6 s, e a aritmética é esta: quem agenda os dois timers é a **tool de "
            "cotação**, e o modelo leva alguns segundos para chegar até ela. Quando o "
            "job começa depois dos 6 s, o prazo já venceu e o aviso sai na hora — é "
            "por isso que ele acompanha o início do job, e não o relógio.\n\n"
            "O disparo é de dentro da tool de propósito: um watchdog na camada de "
            "conversa dispararia **durante** a geração do modelo e produziria «só um "
            "instante» seguido da resposta 0,2 s depois. Para a demora que não é da "
            "cotação existe um segundo relógio, aos 10 s, na camada de conversa."
        ),
    },
}


def cabecalho(cenario: str, conversation_id: str) -> str:
    c = CENARIOS[cenario]
    from app.config import get_settings

    modelo = get_settings().llm_model
    return f"""# {c['titulo']}

> Gerado por `scripts/transcript.py`. **Entregável nº 4** do enunciado: log de uma
> execução completa, do início ao fim.
>
> **Modelo:** `{modelo}`. O nome fica no artefato porque a conversa é produto DELE:
> um transcript sem o modelo nomeado convida a ser comparado com outro gerado por um
> modelo diferente, que é exatamente o erro que este repositório se obriga a não
> cometer com as medições de cache e custo.

## Como reproduzir

```bash
{c['env']} docker compose up -d --build --wait
docker compose exec -T app python scripts/transcript.py --cenario {cenario} \\
  > artifacts/transcript-{cenario}.md
```

O redirecionamento é do lado de fora de propósito: o contêiner é efêmero e montar um
volume só para isto acrescentaria uma linha ao `docker-compose.yml` que não serve ao
produto. O artefato nasce onde vai viver.

O `docker compose up` acima **reinicia o processo da `/quote`** com essas variáveis, e
é isso que torna o cenário reproduzível: o RNG do legado é um fluxo global e contínuo
do processo, então a tripla que define um cenário é *(seed, processo reiniciado,
sequência exata de requisições)* — a seed sozinha não basta.

{c['porque']}

- Conversa: `{conversation_id}`
- Gerado em: {dt.datetime.now(dt.UTC).isoformat(timespec='seconds')}
- `[+Xs]` é o tempo desde o início da conversa; `Δ` é o tempo desde a mensagem do
  lead naquele turno — é a coluna que a política de espera governa.

## Transcript

```
"""


class Coletor(ConsoleAdapter):
    """`ConsoleAdapter` que também guarda o Δ do turno.

    A coluna Δ existe porque a política de espera conta a partir da chegada da
    mensagem do LEAD (`aviso_espera_s`, `reforco_espera_s`), e não do início da
    conversa. Sem ela, "aviso aos 6 s" fica invisível no meio de uma conversa que já
    dura 40 s — e é justamente esse número que o critério nº 2 pede para ver.
    """

    def __init__(self) -> None:
        super().__init__(transcript=True)
        self.t_turno: float = 0.0
        self.deltas: list[float | None] = []

    def abrir_turno(self) -> None:
        self.t_turno = self._decorrido()

    def anotar(self, autor: str, conteudo: str, *, do_turno: bool) -> None:
        agora = self._decorrido()
        self.linhas.append(LinhaTranscript(agora, autor, conteudo))
        self.deltas.append(agora - self.t_turno if do_turno else None)

    async def send(self, conversation_id, text, *, message_id, quote_id=None,
                   autor="agente", **kw) -> str:
        self.anotar(autor, text, do_turno=True)
        self.enviadas.append({"text": text, "quote_id": quote_id, "autor": autor})
        return f"console:{message_id}"

    async def typing(self, conversation_id, *, ativo: bool) -> None:
        return None

    def render(self) -> str:
        largura = max((len(l.autor) for l in self.linhas), default=7)
        saida = []
        for linha, delta in zip(self.linhas, self.deltas, strict=True):
            marca = f"[{linha.segundos:+6.1f}s]"
            d = f"  Δ{delta:+5.1f}s" if delta is not None else " " * 9
            # Continuações alinhadas: um bloco de cotação tem várias linhas, e sem
            # isto a segunda em diante encosta na margem e some do lado do autor.
            corpo = linha.conteudo.replace("\n", "\n" + " " * (len(marca) + 9 + largura + 4))
            saida.append(f"{marca}{d}  {linha.autor:<{largura}}  {corpo}")
        return "\n".join(saida)


def rodape(s, conversation_id: str) -> str:
    """O que ficou GRAVADO. Um transcript sem isto é uma tela; com isto é rastro.

    É a evidência do critério nº 4 (*cada mensagem e cotação com id e status*) e do
    nº 3 (*critério de handoff explícito*): o desfecho não é o texto que saiu, é a
    linha do banco que sobrou.
    """
    conv = repo.obter_conversa(s, conversation_id)
    partes = ["```", "", "## O que ficou gravado", "",
              f"**Estado final da conversa:** `{conv.state}`", ""]

    msgs = repo.mensagens(s, conversation_id)
    partes += ["### Mensagens", "",
               "| index | autor | tipo | status | quote_id |",
               "|---|---|---|---|---|"]
    for m in msgs:
        partes.append(
            f"| {m.index} | `{m.autor}` | `{m.tipo}` | `{m.status}` | "
            f"{'`' + m.quote_id + '`' if m.quote_id else '—'} |"
        )

    quotes = s.query(Quote).filter_by(conversation_id=conversation_id).all()
    if quotes:
        partes += ["", "### Cotações", "",
                   "| quote_id | status | prêmio | outcome | latência |",
                   "|---|---|---|---|---|"]
        for q in quotes:
            premio = f"R$ {q.premio_mensal}" if q.premio_mensal is not None else "—"
            partes.append(
                f"| `{q.id}` | `{q.status}` | {premio} | "
                f"`{q.erro_outcome or '—'}` | {q.total_latency_ms or 0} ms |"
            )
        for q in quotes:
            tentativas = (s.query(QuoteAttempt).filter_by(quote_id=q.id)
                          .order_by(QuoteAttempt.attempt).all())
            if not tentativas:
                continue
            partes += ["", f"#### Tentativas de `{q.id}`", "",
                       "| # | HTTP | outcome | latência |", "|---|---|---|---|"]
            for a in tentativas:
                partes.append(
                    f"| {a.attempt} | {a.http_status or '— (sem resposta)'} | "
                    f"`{a.outcome}` | {a.latency_ms} ms |"
                )

    handoffs = s.query(Handoff).filter_by(conversation_id=conversation_id).all()
    if handoffs:
        partes += ["", "### Handoff", ""]
        for h in handoffs:
            partes += [f"- gatilho `{h.trigger}`, disparado por **{h.disparado_por}**",
                       f"  - motivo: {h.reason}"]
            if h.gatilhos_secundarios:
                partes.append(f"  - secundários: {h.gatilhos_secundarios}")
    else:
        partes += ["", "### Handoff", "",
                   "Nenhum. O agente resolveu sozinho — que é o desfecho pretendido "
                   "deste cenário."]

    return "\n".join(partes) + "\n"


async def executar(cenario: str, saida: str) -> int:
    from app.agent.turno import responder

    canal = Coletor()
    fabrica = sessao_factory()

    with fabrica() as s:
        conv = repo.criar_conversa(
            s, channel="console",
            # Único por execução: `conversations` tem UNIQUE (channel, external_ref),
            # e uma execução anterior abortada bloquearia a próxima.
            external_ref=f"transcript-{cenario}-{int(time.time())}",
        )
        s.commit()
        conversation_id = conv.id

    canal.marcar_inicio()

    for fala in FALAS:
        canal.abrir_turno()
        chegada = time.monotonic()
        with fabrica() as s:
            estado = repo.obter_conversa(s, conversation_id).state
            if estado == "encaminhado":
                # Terminal de verdade: o agente parou. Continuar o roteiro produziria
                # linhas de lead sem resposta e daria a impressão de que ele travou.
                canal.anotar("—", f"(conversa em `{estado}`: o roteiro para aqui)",
                             do_turno=False)
                break
            m = repo.gravar_mensagem(s, conversation_id, autor="lead",
                                     conteudo=fala, status="received")
            s.commit()
            # A versão MASCARADA, que é a que fica gravada. Ver o docstring do módulo.
            canal.anotar("lead", m.conteudo, do_turno=False)

        await responder(conversation_id, fala, canal, chegada_do_lead=chegada)

    with fabrica() as s:
        corpo = cabecalho(cenario, conversation_id) + canal.render() + "\n"
        corpo += rodape(s, conversation_id)

    if saida == "-":
        sys.stdout.write(corpo)
    else:
        os.makedirs(os.path.dirname(saida) or ".", exist_ok=True)
        with open(saida, "w", encoding="utf-8") as f:
            f.write(corpo)
    print(f"→ {len(canal.linhas)} linhas", file=sys.stderr)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cenario", choices=sorted(CENARIOS), required=True)
    # Padrão: stdout. Ver o cabeçalho gerado — o artefato é redirecionado no host.
    p.add_argument("--saida", default="-")
    args = p.parse_args()

    bootstrap()
    return asyncio.run(executar(args.cenario, args.saida))


if __name__ == "__main__":
    raise SystemExit(main())
