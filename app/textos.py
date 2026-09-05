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

# ① — 6 s, com cotação em voo. Despachado de dentro da tool, com o relógio do LEAD:
# conta da chegada da mensagem dele, não de quando a tool começou.
# "Buscando", não "confirmando": aos 6 s o valor ainda não existe.
AVISO_ESPERA = "Tô buscando o valor no sistema e ele tá lento agora. Já te trago, tá?"

# ② — reforço aos ~20 s.
REFORCO = "Ainda tô aqui, viu? O sistema não me devolveu ainda. Assim que sair eu te mando."

# ③ — o job de cotação terminou `failed`. A segunda frase é deliberada: ela diz a
# arquitetura dentro do produto, no momento em que ela importa para o lead.
INDISPONIBILIDADE = (
    "Não consegui confirmar o valor agora: o sistema de cotação não respondeu. "
    "Não vou te passar um número sem ter certeza dele."
)

# ④ — despedida do encaminhamento. "A equipe", não "ele": presumir o gênero de quem
# vai atender erra em metade dos casos. Sem prazo.
DESPEDIDA = (
    "Já passei sua conversa pra um atendente da equipe, com tudo que a gente conversou. "
    "A equipe assume daqui."
)

# ⑫ — o lead aceitou a cotação. **O único prefixo de handoff que é boa notícia.**
#
# Todos os outros encaminham porque algo saiu do lugar; este encaminha porque deu certo,
# e o texto precisa soar assim. Antes o aceite caía na despedida crua ("já passei sua
# conversa pra um atendente"), que responde a um pedido de socorro que o lead não fez —
# e é a última coisa que ele lê quando tudo funcionou.
#
# "Consultor", e não "atendente": quem fecha contratação faz outra coisa. E nenhuma
# promessa de prazo, pela mesma razão de sempre — ninguém aqui controla a agenda dele.
ACEITE_DA_COTACAO = (
    "Boa! Pra fechar a contratação eu passo você pra um consultor da equipe: "
    "a emissão da apólice precisa de uma pessoa pra confirmar os dados e o pagamento."
)

# ⑪ — falha técnica nossa. Duas coisas que ele NUNCA faz: expor o erro e sugerir que
# o lead fez algo errado.
#
# Existe porque o Agno **não levanta** quando a chamada ao provider falha: devolve um
# `RunOutput` com `status=ERROR` e o texto do erro em `content`. Medido no replay, com
# a conta sem crédito: 14 conversas gravaram «Error code: 400 … Your credit balance is
# too low …» como fala do agente. O guardrail não pega — não há valor monetário no
# texto — e o lead leria a mensagem de cobrança da nossa conta.
FALHA_TECNICA = (
    "Tive um problema técnico aqui do meu lado — não foi nada que você fez. Já estou chamando alguém da equipe pra te atender."
)

# ⑧a / ⑧b — prefixos de assunto sensível. Dois, e não um: "sinto muito" numa
# notificação extrajudicial soa como admissão, e a ausência dele depois de "meu carro
# capotou ontem" soa como frieza.
SENSIVEL_SINISTRO = (
    "Sinto muito por isso. Esse assunto precisa de uma pessoa da equipe olhando com "
    "atenção — não é algo pra eu resolver por aqui."
)
SENSIVEL_JURIDICO = (
    "Entendi. Esse é um assunto que precisa de uma pessoa da equipe olhando, e não é "
    "algo que eu deva tratar por aqui."
)

# ⑤⑥⑦ — as três recusas. Só a de veículo tem oferta, e ela vem DENTRO do template:
# o texto do modelo é descartado no turno da recusa, sem exceção, porque o risco ali
# não é preço alucinado e sim promessa falsa ("vou ver com o setor de exceções").
RECUSA_IDADE_ACIMA = (
    "Infelizmente não consigo seguir com essa cotação: a nossa aceitação vai até 75 anos "
    "de idade do condutor. Acima disso a apólice não é emitida, e não é algo que eu "
    "consiga contornar por aqui. Deixei seu cadastro registrado do nosso lado. "
    "Sinto muito não poder ajudar dessa vez."
)
RECUSA_IDADE_ABAIXO = (
    "Pra contratar o seguro é preciso ter no mínimo 18 anos, então não consigo emitir a "
    "cotação agora. Quando chegar lá, é só me chamar que a gente resolve rápido."
)
RECUSA_VEICULO = (
    "Esse carro tem mais de 20 anos, e a nossa aceitação vai até 20 anos de uso — então "
    "não consigo cotar ele. Mas se tiver outro carro na casa que seja mais novo, me manda "
    "o modelo e o ano que eu faço a cotação dele agora."
)

RECUSAS = (RECUSA_IDADE_ACIMA, RECUSA_IDADE_ABAIXO, RECUSA_VEICULO)

TODOS: dict[str, str] = {
    "AVISO_SEM_COTACAO": AVISO_SEM_COTACAO,
    "AVISO_ESPERA": AVISO_ESPERA,
    "REFORCO": REFORCO,
    "INDISPONIBILIDADE": INDISPONIBILIDADE,
    "DESPEDIDA": DESPEDIDA,
    "FALHA_TECNICA": FALHA_TECNICA,
    "SENSIVEL_SINISTRO": SENSIVEL_SINISTRO,
    "SENSIVEL_JURIDICO": SENSIVEL_JURIDICO,
    "RECUSA_IDADE_ACIMA": RECUSA_IDADE_ACIMA,
    "RECUSA_IDADE_ABAIXO": RECUSA_IDADE_ABAIXO,
    "RECUSA_VEICULO": RECUSA_VEICULO,
    "ACEITE_DA_COTACAO": ACEITE_DA_COTACAO,
}

#: Motivo de recusa normalizado → texto. Só estes três viram mensagem de recusa; os
#: casos que a API chama de recusa mas são dado nosso errado (ano futuro, plano
#: inexistente) caem em `bad_request` e nunca chegam aqui.
POR_MOTIVO: dict[str, str] = {
    "idade_acima_do_limite": RECUSA_IDADE_ACIMA,
    "idade_abaixo_do_minimo": RECUSA_IDADE_ABAIXO,
    "veiculo_acima_de_20_anos": RECUSA_VEICULO,
}


def compor_handoff(trigger: str, *, assunto: str | None = None) -> str:
    """O handoff é sempre **um prefixo opcional mais a despedida**.

    Tabela de cinco linhas, determinística — o que mantém o descarte do texto do
    modelo sem exceção em todo caminho de encaminhamento.
    """
    if trigger == "cotacao_indisponivel":
        return f"{INDISPONIBILIDADE}\n\n{DESPEDIDA}"
    if trigger == "assunto_sensivel":
        prefixo = SENSIVEL_SINISTRO if assunto in ("sinistro", "saude") else SENSIVEL_JURIDICO
        return f"{prefixo}\n\n{DESPEDIDA}"
    if trigger == "lead_aceitou_cotacao":
        # O único caminho que NÃO termina na despedida: ela diz "a equipe assume
        # daqui", que no aceite soaria como se algo tivesse dado errado. Aqui o texto
        # já nomeia o próximo passo, e é o passo que o lead pediu.
        return ACEITE_DA_COTACAO
    return DESPEDIDA
