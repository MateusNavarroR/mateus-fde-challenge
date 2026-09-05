"""O guardrail de preço — mecanismo, não boa intenção.

A regra é "o preço nunca vem do modelo". O mecanismo é uma **fronteira** mais **três
verificações**, todas no mesmo ponto de estrangulamento: a função que grava uma mensagem.

**A fronteira** (implementada em `agent/tools.py`): `quote_plan` não devolve o
`QuotePayload` ao modelo. Não devolve prêmio, franquia nem valor de pro-rata — não
devolve número nenhum. Quem renderiza e envia é a própria tool. O modelo, portanto,
nunca teve o número em contexto: não é que ele seja instruído a não parafrasear, é que
**não tem o que parafrasear**. O catálogo no system prompt também entra sem valor
monetário, pelo mesmo motivo — é isso que torna a verificação 1 absoluta em vez de
heurística, sem lista de exceções.

**As três verificações**, aplicadas por `persistence.repo.gravar_mensagem`:

1. mensagem de autor `agente` (texto do modelo) com token monetário → rejeitada;
2. mensagem com `quote_id` → aquela cotação tem que estar em `status = ok`;
3. mensagem com `quote_id` → conteúdo **byte a byte** igual ao render daquela cotação.

A terceira é a que fecha o buraco: sem ela, uma paráfrase errada com um `quote_id`
válido colado passaria pelas duas primeiras.

Violação **não é corrigida pelo modelo** — isso vira laço. A mensagem é descartada, a
violação conta, e na segunda a conversa vai para handoff `guardrail`. Na suíte de
testes, qualquer violação reprova.
"""

from __future__ import annotations

import re


class GuardrailViolado(Exception):
    """Levantada na fronteira de escrita. Carrega o motivo para a linha de auditoria."""

    def __init__(self, motivo: str, trecho: str | None = None) -> None:
        self.motivo = motivo
        self.trecho = trecho
        super().__init__(motivo)


#: Padrões de valor monetário em português. O objetivo é pegar o modelo escrevendo
#: preço, não virar paranoia: "tenho 35 anos", "carro 2019" e "CEP 01XXX-XXX" passam,
#: e há teste para cada um. Se o regex reprovar esses, o agente não consegue conversar.
_MONETARIO: tuple[re.Pattern[str], ...] = (
    # R$ com ou sem espaço, com milhar e centavo opcionais
    re.compile(r"R\$\s*\d"),
    # "209,90 reais", "300 reais", "1.025,14 reais"
    re.compile(r"\b\d{1,3}(?:\.\d{3})*(?:,\d{2})?\s*reais\b", re.IGNORECASE),
    # "209,90 por mês", "392,25/mês" — valor com centavo seguido de periodicidade
    re.compile(r"\b\d+,\d{2}\s*(?:/|por\s+)m[êe]s\b", re.IGNORECASE),
    # "custa 209,90", "sai por 392,25" — verbo de preço seguido de decimal
    re.compile(
        r"\b(?:custa|sai\s+por|fica\s+em|fica\s+por|por)\s+\d{1,3}(?:\.\d{3})*,\d{2}\b",
        re.IGNORECASE,
    ),
)


def checar_texto_do_modelo(texto: str) -> None:
    """Verificação 1. Levanta `GuardrailViolado` se houver valor monetário.

    Só se aplica a texto de autor `agente`. Texto de autor `sistema` vem do renderer
    ou de `docs/TEXTOS.md` e é confiável por construção — a verificação 3 é quem
    responde por ele.
    """
    for padrao in _MONETARIO:
        m = padrao.search(texto or "")
        if m:
            raise GuardrailViolado(
                "valor monetário em texto do modelo", trecho=m.group(0)
            )


def checar_mensagem_de_cotacao(
    conteudo: str, *, quote_status: str | None, render_esperado: str | None
) -> None:
    """Verificações 2 e 3, para mensagens que carregam `quote_id`.

    `quote_status` e `render_esperado` vêm do banco, não do chamador — é o repo quem
    os busca, para que não haja como passar valores convenientes.
    """
    if quote_status != "ok":
        raise GuardrailViolado(
            f"mensagem aponta para cotação com status {quote_status!r}, não 'ok'"
        )
    if conteudo != render_esperado:
        raise GuardrailViolado(
            "conteúdo diverge do render daquela cotação — paráfrase com quote_id válido"
        )
