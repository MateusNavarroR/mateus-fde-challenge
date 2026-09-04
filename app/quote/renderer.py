"""O bloco da cotação — **a única origem de texto com valor monetário no sistema**.

Nenhum outro módulo formata dinheiro. É isso que torna possível a verificação 3 do
guardrail: uma mensagem com `quote_id` tem que ser **byte a byte** igual ao render
daquela cotação, e sem uma origem única não haveria contra o que comparar.

O formato é o do `docs/DECISOES-FECHADAS.md` §4: bloco compacto, uma mensagem, preço na
primeira linha, carência com marcador próprio.

Quatro escolhas, e o motivo de cada uma:

- **preço primeiro**: respeita o tempo do lead. "Vender antes do número" é o padrão do
  dataset, e o dataset não é referência de qualidade;
- **carência em linha isolada, com marcador**: é impossível pular sem ver, e é a
  ressalva que gera reclamação depois se passar batida;
- **franquia sempre**: é a objeção nº 2 do dataset; omitir só adia o atrito;
- **agravo de CEP nunca mencionado**: soaria como justificativa de preço alto sem o
  lead ter perguntado.

E quando a vigência começa no dia 1, a mensagem **diz** que o primeiro mês é integral
em vez de silenciar: a ausência do campo `primeiro_pagamento_pro_rata` é informação, e
silenciar gera a pergunta "e a proporcional?".
"""

from __future__ import annotations

import datetime as dt

from app.contracts.quote import QuotePayload

_COBERTURA_LEGIVEL = {
    "colisao": "colisão",
    "roubo": "roubo",
    "furto": "furto",
    "terceiros": "terceiros",
    "vidros": "vidros",
    "carro_reserva": "carro reserva",
    "assistencia_24h": "assistência 24h",
}


def brl(valor: float) -> str:
    """Formato brasileiro: ponto no milhar, vírgula no centavo."""
    inteiro, _, centavos = f"{valor:,.2f}".partition(".")
    return f"R$ {inteiro.replace(',', '.')},{centavos}"


def _lista(itens: list[str]) -> str:
    nomes = [_COBERTURA_LEGIVEL.get(c, c) for c in itens]
    if len(nomes) == 1:
        return nomes[0]
    return f"{', '.join(nomes[:-1])} e {nomes[-1]}"


def render(p: QuotePayload, data_inicio: dt.date | None = None) -> str:
    """Monta o bloco. Determinístico: mesmo payload, mesmo texto, sempre."""
    linhas = [
        "Fechei sua cotação 👇",
        "",
        f"*{p.plano_nome} — {brl(p.premio_mensal)}/mês*",
        f"Cobre {_lista(p.coberturas)}.",
        f"Franquia de {brl(p.franquia).replace(',00', '')}.",
        "",
    ]

    pr = p.primeiro_pagamento_pro_rata
    if pr is not None and data_inicio is not None:
        linhas += [
            f"Começando dia {data_inicio.day:02d}/{data_inicio.month:02d}, o primeiro "
            f"boleto sai proporcional: *{brl(pr.valor_primeiro_pagamento)}* "
            f"({pr.dias_cobrados} dos {pr.dias_no_mes} dias).",
            f"Do mês seguinte em diante, {brl(p.premio_mensal)} cheio.",
            "",
        ]
    else:
        # A ausência do campo É informação: o lead precisa saber que não haverá
        # proporcional, senão ele pergunta.
        linhas += [
            "Como a vigência começa no dia 1º, o primeiro mês já é integral — "
            "não tem valor proporcional.",
            "",
        ]

    car = p.carencia
    linhas += [
        f"⚠️ {_lista(car.coberturas).capitalize()} começam a valer {car.dias} dias "
        "depois do início da vigência.",
        "",
        "Quer que eu siga com a emissão?",
    ]
    return "\n".join(linhas)


def render_de_payload(payload: dict, data_inicio: dt.date | None = None) -> str:
    """Render a partir do JSON guardado em `quotes.payload`.

    É por aqui que o guardrail recalcula o texto canônico de uma cotação para a
    comparação byte a byte — inclusive sobre o histórico, anos depois.
    """
    di = data_inicio
    if di is None and isinstance(payload.get("_data_inicio"), str):
        di = dt.date.fromisoformat(payload["_data_inicio"])
    return render(QuotePayload.model_validate(payload), di)
