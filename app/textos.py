"""Os textos determinísticos, cópia literal de `docs/TEXTOS.md`.

**Origem única.** Sem ela a verificação 3 do guardrail — conteúdo byte a byte igual ao
render — não teria contra o que comparar, e o texto enviado poderia derivar do texto
aprovado sem ninguém notar.

Três regras que valem para todos: sem interpolação (nenhum slot, nenhum número), não
afirmam o que não está acontecendo, e não prometem prazo nem retorno que ninguém fará.

O conjunto completo, com o racional de cada frase, está em `docs/TEXTOS.md`. A fatia 3
acrescenta os de cotação e recusa; aqui entram só os que a fatia 1 usa.
"""

from __future__ import annotations

#: ①b — 10 s, sem cotação em voo. Despachado pela camada de conversa.
#: Limiar mais alto que o da cotação porque a demora do modelo é anômala, não
#: projetada: 6,5 s ainda é latência plausível e avisar ali seria ruído.
AVISO_SEM_COTACAO = "Só um instante, tô demorando mais que o normal aqui. Já te respondo."

TODOS: dict[str, str] = {
    "AVISO_SEM_COTACAO": AVISO_SEM_COTACAO,
}
