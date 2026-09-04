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
from app.agent.tools import ContextoDoTurno  # noqa: E402
from app.persistence import repo  # noqa: E402
from app.persistence.db import sessao_factory  # noqa: E402

#: As falas são do molde do dataset: linguagem torta, dados fora de ordem. As duas
#: últimas cobrem o que o lead do dataset NUNCA informa — plano e data de início —,
#: que é justamente o que a qualificação exige.
FALAS = [
    "Oi, queria fazer um seguro pro meu carro",
    "e um Onix 2019",
    "tenho 28 anos, cep 07145-200",
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
    t0 = time.monotonic()
    canal = CanalConsole(t0)
    fabrica = sessao_factory()
    with fabrica() as s:
        conv = repo.criar_conversa(s, channel="console", external_ref="manual")
        s.commit()
        ctx = ContextoDoTurno(sessao=s, conversation_id=conv.id)
        agente = construir_agente(ctx, canal)

        for fala in FALAS:
            ctx.texto_do_lead = fala
            print(f"[+{time.monotonic() - t0:5.1f}s] LEAD    │ {fala}\n")
            r = agente.run(fala)
            texto = (r.content or "").strip()
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
