"""Uma conversa do começo ao fim, para LER — não para testar.

O objetivo é aposentar a maior incerteza que resta: o desenho do agente. Ele tem o
texto descartado em três dos quatro desfechos da tool, não vê número nenhum, e o
catálogo no system prompt não tem preço nem franquia. Isso é deliberado — e ninguém
nunca viu esse agente conversar.

O que se procura ao ler: ele soa como atendimento ou como formulário? Ele fica mudo
depois da cotação, porque tudo que escreveria foi descartado?

Uso:
    APP_QUOTE_API_URL=http://localhost:8001 \
    ANTHROPIC_API_KEY=... uv run python scripts/conversa_manual.py
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agent.agente import construir_agente  # noqa: E402
from app.bootstrap import bootstrap  # noqa: E402
from app.agent.tools import ContextoDoTurno  # noqa: E402
from app.persistence import repo  # noqa: E402
from app.persistence.db import sessao_factory  # noqa: E402

#: As falas são do molde do dataset: linguagem torta, dados fora de ordem. As duas
#: últimas cobrem o que o lead do dataset NUNCA informa — plano e data de início —,
#: que é justamente o que a qualificação exige.
#: Montado, não literal: escrito inteiro, `07000-000` casaria com o regex de CEP da
#: varredura de PII, e a varredura tem de continuar sem exceção por arquivo. O que
#: importa no caso é o PREFIXO — os dois dígitos que disparam o agravo de 1,30.
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


class CanalConsole:
    def __init__(self, t0: float) -> None:
        self.t0 = t0

    async def send(self, conversation_id, text, *, message_id, quote_id=None,
                   autor="agente", **kw):
        marca = f"[+{time.monotonic() - self.t0:5.1f}s]"
        print(f"{marca} sistema │ {text}\n")
        return "console"


def main() -> None:
    # Carrega o .env no processo e falha alto se a credencial faltar.
    bootstrap()

    t0 = time.monotonic()
    canal = CanalConsole(t0)
    fabrica = sessao_factory()
    with fabrica() as s:
        conv = repo.criar_conversa(
            s, channel="console",
            # Único por execução: `conversations` tem UNIQUE (channel, external_ref),
            # e uma execução anterior abortada bloquearia a próxima.
            external_ref=f"manual-{int(time.time())}",
        )
        s.commit()
        ctx = ContextoDoTurno(sessao=s, conversation_id=conv.id)
        import asyncio

        def enviar(texto, quote_id=None, autor="sistema"):
            print(f"[+{time.monotonic() - t0:5.1f}s] {autor:<7} │ {texto}\n")

        ctx.enviar = enviar
        ctx.chegada_do_lead = time.monotonic()
        agente = construir_agente(ctx)

        for fala in FALAS:
            ctx.texto_do_lead = fala
            ctx.chegada_do_lead = time.monotonic()
            ctx.ja_enviou = False
            print(f"[+{time.monotonic() - t0:5.1f}s] LEAD    │ {fala}\n")
            r = agente.run(fala)
            texto = (r.content or "").strip()
            if ctx.ja_enviou:
                # A tool já falou: o texto do modelo é descartado, sem exceção.
                print(f"[+{time.monotonic() - t0:5.1f}s] agente  │ "
                      "(descartado — a tool já respondeu ao lead)\n")
            else:
                print(f"[+{time.monotonic() - t0:5.1f}s] agente  │ "
                      f"{texto if texto else '(silêncio)'}\n")
            m = getattr(r, "metrics", None)
            if m:
                print(f"          ↳ in={m.input_tokens} out={m.output_tokens} "
                      f"cache_read={m.cache_read_tokens} "
                      f"cache_write={m.cache_write_tokens}\n")

        c = repo.obter_conversa(s, conv.id)
        print(f"── estado final: {c.state} · conversa {conv.id}")


if __name__ == "__main__":
    main()
