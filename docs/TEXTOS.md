# Os textos determinísticos

Doze frases (a migração 0006 acrescentou a ⑫, do oitavo gatilho — `lead_aceitou_cotacao`).
São elas que o lead lê nos momentos em que o agente **não** pode improvisar: espera,
falha, recusa e encaminhamento.

**Esta é a origem única.** A implementação copia daqui literalmente, e a terceira
verificação do guardrail — comparação byte a byte entre a mensagem persistida e o render
— só funciona porque existe um lugar só de onde o texto sai.

Três regras que valem para todas:

1. **Sem interpolação.** Nenhum slot, nenhum nome, nenhum número. Isso mantém a
   comparação byte a byte trivial e garante que **nenhum valor monetário existe fora do
   bloco da cotação**.
2. **Não afirmam o que não está acontecendo.** É a mesma disciplina que impede o modelo
   de inventar preço, aplicada ao texto que nós mesmos escrevemos.
3. **Não prometem prazo**, nem retorno que ninguém fará.

---

## Espera

O relógio conta a partir da **chegada da mensagem do lead**, não de quando a tool
começou — se ele ficou 8 s no escuro, o aviso chegou tarde.

### ① Aviso — 6 s, com cotação em voo

> Tô buscando o valor no sistema e ele tá lento agora. Já te trago, tá?

Despachado **de dentro da tool de cotação**, pelo `ChannelAdapter`.

"Buscando", não "confirmando": aos 6 s o valor ainda não existe, e afirmar que existe
seria inventar. É a primeira frase que o lead lê numa degradação.

### ①b Aviso — 10 s, sem cotação em voo

> Só um instante, tô demorando mais que o normal aqui. Já te respondo.

Despachado pela camada de conversa, e cobre a demora do próprio modelo.

**Por que 10 s e não 6 s.** As duas demoras têm naturezas diferentes. A da cotação é
projetada — 8 s de sono, por construção do legado — e 6 s a pega antes. A do modelo é
anômala: 6,5 s ainda é latência plausível, e avisar ali produziria "só um instante"
seguido da resposta 0,2 s depois, que é o atrito inventado que este projeto evita em
todos os outros pontos. 10 s já é sintoma, não variação.

### ② Reforço — ~20 s

> Ainda tô aqui, viu? O sistema não me devolveu ainda. Assim que sair eu te mando.

---

## Falha

### ③ Indisponibilidade — o job de cotação terminou `failed`

> Não consegui confirmar o valor agora: o sistema de cotação não respondeu. Não vou te
> passar um número sem ter certeza dele.

A segunda frase é deliberada: ela diz a arquitetura dentro do produto. O invariante
"o preço nunca vem do modelo" deixa de ser uma linha de README e vira algo que o lead
ouve exatamente no momento em que ele importa.

---

## Assunto sensível

Um prefixo, escolhido pelo assunto, antes do ④. Nenhum dos dois entra no mérito:
reconhecem e param, que é o comportamento que um gatilho de custo alto pede.

### ⑧a Sinistro ou saúde

> Sinto muito por isso. Esse assunto precisa de uma pessoa da equipe olhando com
> atenção — não é algo pra eu resolver por aqui.

### ⑧b Jurídico ou reclamação formal

> Entendi. Esse é um assunto que precisa de uma pessoa da equipe olhando, e não é algo
> que eu deva tratar por aqui.

**Por que dois e não um.** Tentei um prefixo único e não fecha: "sinto muito" numa
notificação extrajudicial soa como admissão, e a ausência dele depois de "meu carro
capotou ontem" soa como frieza. O registro emocional é incompatível, e este é o gatilho
onde o custo do erro é o mais alto.

---

## Encaminhamento

### ⑪ Falha técnica nossa

Quando a chamada ao modelo falha, o lead recebe isto — nunca o erro.

> Tive um problema técnico aqui do meu lado — não foi nada que você fez. Já estou chamando alguém da equipe pra te atender.

Duas coisas que ele nunca faz: expor o erro e sugerir que o lead fez algo errado. O
Agno **não levanta** nesse caso — devolve `RunOutput` com `status=ERROR` e o texto do
erro em `content` —, então sem este caminho a mensagem de erro do provider seguiria o
fluxo normal e chegaria ao lead como fala do agente.

### ④ Despedida

> Já passei sua conversa pra um atendente da equipe, com tudo que a gente conversou.
> A equipe assume daqui.

"A equipe", não "ele": no próprio dataset os vendedores são Camila, Rodrigo, Patricia e
Marcos, e presumir o gênero de quem vai atender erra em metade dos casos.

Sem prazo. E "assume daqui" sinaliza que o agente parou de responder — que é o estado
terminal `encaminhado` que fechamos.

### A regra de composição

O handoff é **sempre um prefixo opcional mais o ④**. Determinístico, quatro linhas:

| Gatilho | Prefixo |
|---|---|
| `cotacao_indisponivel` | ③ |
| `assunto_sensivel` (sinistro, saúde) | ⑧a |
| `assunto_sensivel` (jurídico, reclamação) | ⑧b |
| `lead_aceitou_cotacao` | ⑫ — e **sem** o ④ (ver abaixo) |
| `lead_pediu`, `extracao_falhou`, `objecao_fora_da_alcada`, `midia_sem_texto`, `guardrail` | nenhum |

### ⑫ O lead aceitou a cotação — o único encaminhamento que é boa notícia

> Boa! Pra fechar a contratação eu passo você pra um consultor da equipe: a emissão da
> apólice precisa de uma pessoa pra confirmar os dados e o pagamento.

**É o único caminho que não termina no ④.** A despedida diz "a equipe assume daqui",
que no aceite soaria como se algo tivesse dado errado — e esta é a última mensagem de
uma conversa que funcionou do começo ao fim.

"Consultor", e não "atendente": quem fecha contratação faz outra coisa. Sem prazo, pela
mesma razão de sempre.

Isso mantém o descarte do texto do modelo **sem exceção**: o lead recebe uma composição
de textos fixos, nunca uma frase gerada, em todo caminho de encaminhamento.

---

## Recusa

Três motivos reais, três textos. O modelo não escreve nada no turno da recusa — vale o
mesmo descarte que vale para a cotação, e pelo mesmo motivo, que aqui não é preço
alucinado e sim **promessa falsa**: um modelo solto num turno de recusa oferece "vou ver
com o setor de exceções".

### ⑤ Idade acima do limite de aceitação

> Infelizmente não consigo seguir com essa cotação: a nossa aceitação vai até 75 anos de
> idade do condutor. Acima disso a apólice não é emitida, e não é algo que eu consiga
> contornar por aqui. Sinto muito não poder ajudar dessa vez.

"Não é algo que eu consiga contornar por aqui" fecha, no texto, a porta que o modelo
abriria sozinho.

**A frase «Deixei seu cadastro registrado do nosso lado» saiu, e quem a derrubou foi o
juiz.** Este documento justificava a frase pelo oposto — "é verdade, e não promete
retorno de ninguém". O `AgentAsJudgeEval` deu nota 7 de 10, abaixo do limiar, com o
motivo: *«pode ser interpretada como promessa implícita de acompanhamento futuro ou
retorno, o que vai de encontro à regra de não prometer retorno de atendente»*.

Ele estava certo, e a distinção é entre INTENÇÃO e LEITURA. A frase era verdadeira — a
conversa está no banco e aparece no admin. Mas um lead que acaba de ouvir "não" e lê
"deixei seu cadastro registrado" entende que alguém vai olhar aquilo depois, e ninguém
vai. É a mesma promessa vazia que o resto do texto se esforça para não fazer, entrando
pela porta dos fundos.

Vale registrar como achado de método: **este é o tipo de defeito que só um juiz de
texto encontra.** Nenhum teste determinístico o pegaria — a frase não tem valor
monetário, não promete prazo, não sugere trocar o condutor. Ela falha na leitura, e ler
é o que o juiz faz.

**Sem oferta de reenquadramento.** O agente nunca sugere trocar o condutor principal:
se quem dirige de fato tem 78 anos, declarar outra pessoa é declaração falsa, e a conta
chega como negativa de sinistro. Se o lead disser espontaneamente que quem dirige é
outra pessoa, aí sim recotamos — registrar um fato que ele trouxe não é a mesma coisa
que sugerir o caminho.

### ⑥ Idade abaixo do mínimo

> Pra contratar o seguro é preciso ter no mínimo 18 anos, então não consigo emitir a
> cotação agora. Quando chegar lá, é só me chamar que a gente resolve rápido.

Convite, não promessa: quem age é o lead.

### ⑦ Veículo com mais de 20 anos — o único com oferta

> Esse carro tem mais de 20 anos, e a nossa aceitação vai até 20 anos de uso — então não
> consigo cotar ele. Mas se tiver outro carro na casa que seja mais novo, me manda o
> modelo e o ano que eu faço a cotação dele agora.

A oferta vem **dentro do template**, e não de uma exceção no descarte. A apólice é de um
veículo específico, então cotar outro é outra cotação, e é legítima.

O turno seguinte é livre: o lead reage, aquele turno **não tem resultado de tool**, o
modelo conversa normalmente e pode chamar `quote_plan` de novo com o outro veículo.
**O reenquadramento acontece em dois turnos, sem exceção nenhuma na regra.**
