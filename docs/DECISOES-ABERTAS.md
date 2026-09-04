# As quatro decisões abertas — opções e trade-offs

> ## ⚠️ ESTAS DECISÕES ESTÃO FECHADAS
>
> O contrato é **`docs/DECISOES-FECHADAS.md`**. Este documento é mantido como registro
> do que foi considerado e do que foi descartado — inclusive as opções que **não**
> foram escolhidas, com o motivo. Ele existe porque a decisão só é defensável quando
> se sabe contra o que ela foi decidida.
>
> Onde este documento divergir do contrato, o contrato vence. Duas divergências
> conhecidas, ambas corrigidas durante a decisão e registradas lá:
> o gatilho "híbrido" do aviso de espera foi descartado por produzir aviso
> desnecessário na falha rápida, e o reenquadramento por troca de condutor principal
> foi cortado por ser instrução para declaração falsa.


O enunciado é explícito: *"Não existe 'formato de saída certo' definido de propósito.
Queremos ver a sua decisão de engenharia."* Estas quatro não têm resposta única, e são
onde a avaliação olha com mais atenção.

**Este documento não escolhe.** Ele apresenta as opções, o que cada uma custa, e os
números medidos que as tornam decidíveis. Depois de decididas, viram contrato, entram
no `CLAUDE.md` e não se reabrem.

Números que atravessam as quatro decisões:

| Fato | Valor | Fonte |
|---|---|---|
| chance de a `/quote` falhar numa tentativa | 20 % | default do `docker-compose` |
| chance de uma chamada demorar 8 s **e dar certo** | 10 % | §3.2 |
| chance de um job de 3 tentativas falhar por inteiro | **0,8 %** | §3.4 |
| chance de um job precisar de ≥ 2 tentativas | **20 %** | §3.4 |
| pior caso de um job | **~37 s** | §3 da política |
| leads incotáveis no dataset | **30 %** | §8.1 |
| leads incotáveis cuja 1ª resposta é 5xx, não 422 | **~20 % deles** (~6 % do total) | §3.6 |

---

## Decisão 1 — A tabela de gatilhos de handoff

**O que precisa ser decidido:** quais gatilhos existem, qual a precedência quando dois
disparam juntos, e o que o bot diz em cada um.

O eixo real não é "quais gatilhos", é **quanta autonomia o bot tem**. Os gatilhos caem
sozinhos depois que essa postura é escolhida.

### As três posturas

| | **A · Autonomia alta** | **B · Cobertura alta** | **C · Graduada por custo do erro** |
|---|---|---|---|
| encaminha quando | não há mais nada que o bot possa fazer | qualquer coisa sai do roteiro | o custo de o bot errar ali é alto |
| lead pede atendente | encaminha | encaminha | encaminha |
| job de cotação `failed` | encaminha | encaminha | encaminha |
| recusa 422 (30 % do tráfego) | **não** — explica e encerra | encaminha | encaminha **em segundo plano**: explica ao lead e cria o item sem prometer retorno |
| objeção de preço | **não** — responde e insiste | encaminha | encaminha só se o lead repetir a objeção |
| assunto sensível (sinistro, jurídico, saúde) | encaminha | encaminha | encaminha **imediato**, sem tentar responder |
| mídia sem texto (7 % das mensagens) | pede por texto | encaminha | pede por texto; encaminha na 2ª vez |
| extração falhou 2× no mesmo campo | encaminha | encaminha na 1ª | encaminha |
| prompt injection / abuso | encerra | encaminha | encerra e registra, sem encaminhar |
| **volume estimado na fila** | ~2 % dos leads | **~40 %** | ~12 % |

**Trade-offs.**

- **A** produz a fila menor e o bot mais impressionante — mas assume que uma recusa
  bem explicada não precisa de humano. Risco: 30 % dos leads recebem um "não" e vão
  embora sem ninguém saber. Num negócio de seguros isso é receita perdida silenciosa.
- **B** é a mais segura para o lead e a mais fácil de defender no README, mas 40 % de
  fila significa que **o bot não está resolvendo**, e o enunciado pede um agente que
  "resolve sozinho *ou* encaminha". Uma fila de 40 % lê como bot que desiste.
- **C** exige justificar o critério "custo do erro" — o que é mais trabalho de
  escrita, e é exatamente o tipo de critério que o enunciado chama de "defensável".
  Custo: é a mais complexa de testar, porque tem gatilhos com contador (2ª vez).

### A precedência — sub-decisão independente

Quando dois gatilhos disparam no mesmo turno (o lead pede atendente **e** a cotação
falhou), quem ganha?

| | como funciona | consequência |
|---|---|---|
| **lista fixa** | ordem declarada; o primeiro que casa vence | previsível e trivial de testar; a fila mostra um gatilho só |
| **severidade** | cada gatilho tem peso; o mais grave vence | melhor para o operador priorizar; mais um campo para justificar |
| **acumulativo** | um handoff, todos os gatilhos que casaram | o operador vê o quadro inteiro; a UI e os testes ficam mais pesados |

### O que o bot faz depois de encaminhar — sub-decisão independente

| | comportamento | trade-off |
|---|---|---|
| **encerra** | avisa e para de responder | honesto; se o humano demorar, o lead fica no vácuo |
| **continua limitado** | segue conversando, mas não cota nem promete nada | melhor experiência; risco de o bot dizer algo que o humano vai ter que desdizer |
| **continua e cancela** | se o problema se resolver (breaker fechou), retoma e o handoff é resolvido automaticamente | o mais sofisticado; precisa de um caminho de "handoff obsoleto" que dá trabalho e não é avaliado |

**Minha leitura:** o item avaliado é *"o critério é explícito e defensável"* — não *"o
critério é generoso"* nem *"é econômico"*. Qualquer das três posturas passa **se** a
tabela estiver escrita, testada uma linha por gatilho, e visível na fila. O que reprova
é o gatilho implícito, espalhado em `if` pelo código.

---

## Decisão 2 — O que o agente faz enquanto a `/quote` falha

O critério que o enunciado diz que **mais separa**.

A aritmética que restringe as opções: o pior caso do job é ~37 s, e ninguém espera
meio minuto por uma resposta de WhatsApp sem achar que o atendimento caiu. Mas 99,2 %
dos jobs terminam bem, e 80 % terminam na primeira tentativa em ~2 ms.

### As quatro posturas

| | **A · Espera calada** | **B · Avisa e continua em background** | **C · Avisa e usa a espera** | **D · Encaminha na primeira falha** |
|---|---|---|---|---|
| o que o lead vê | "digitando…" até o valor sair | aviso de espera, depois o valor como mensagem nova | aviso + uma pergunta útil, depois o valor | "vou chamar alguém" |
| silêncio máximo | **~37 s** | ~3 s | ~3 s | ~12 s |
| handoff quando | job `failed` (0,8 %) | job `failed` (0,8 %) | job `failed` (0,8 %) | **1ª falha (20 %)** |
| complexidade | baixa | média (job assíncrono + push) | alta (o modelo precisa ter o que perguntar) | baixa |
| o que demonstra | nada de especial | o tratamento da degradação, visível | idem, e aproveita o tempo | prudência, e pouco mais |

**Trade-offs.**

- **A** é indefensável nos 0,8 % piores e desconfortável nos 20 % que retentam. Mas em
  80 % dos casos é a melhor experiência possível: resposta instantânea, sem ruído.
- **B** é o comportamento que o enunciado chama de "elegante", e é o que a tela `/chat`
  consegue mostrar. Custa a arquitetura de job com push — que já é necessária de
  qualquer forma pela aritmética dos 37 s.
- **C** é B com uma pergunta a mais. Só funciona se ainda **houver** o que perguntar:
  como cotamos depois de ter os cinco campos, normalmente não há. Sobra perguntar algo
  secundário — o que pode soar como enrolação. Alternativa honesta: usar a espera para
  antecipar a carência ("enquanto isso: roubo e furto têm 30 dias de carência").
- **D** transforma um problema de 20 % de probabilidade num handoff, quando 96 % desses
  casos se resolveriam sozinhos na 2ª tentativa. Enche a fila humana com nada.

### O gatilho do aviso — a sub-decisão que muda o resultado

Quando o bot manda o aviso de espera?

| | dispara em | efeito colateral |
|---|---|---|
| **por tentativa** (depois da 1ª falha) | ~20 % dos jobs | a chamada lenta de 8 s **não** aciona o aviso: o lead fica 8 s no vácuo em 10 % dos casos, e esses são justamente os que dão certo |
| **por tempo** (ex.: 3 s sem resposta) | ~30 % dos jobs (20 % retry + 10 % lenta) | cobre a lentidão, mas avisa em 10 % de casos que iam responder bem em 8 s de qualquer jeito |
| **híbrido** (o que vier primeiro) | ~30 % | cobre os dois; um parâmetro a mais para explicar |

O por-tempo é o único que cobre o caso lento — que é 10 % do tráfego e é *sucesso*.
Vale notar que "avisar à toa" tem custo baixo (uma frase) e "sumir por 8 s" tem custo
alto (o lead reenvia, ou desiste).

### Quantas tentativas antes de mudar de postura

A política técnica fixa **3 tentativas** por aritmética (§1.2). O que está aberto é se a
*postura conversacional* muda antes disso — por exemplo, avisar depois da 1ª, reforçar
("ainda estou tentando") depois da 2ª, e encaminhar depois da 3ª. Duas mensagens de
espera em ~25 s pode ser atencioso ou pode ser barulho; é uma escolha de tom.

### O que o bot **nunca** faz, em qualquer postura

Isto não está aberto — é invariante e sai de medição, não de gosto:

1. não diz um preço que não veio de um `quote_id` com status `ok`;
2. não diz "você foi recusado" a partir de um 5xx (§3.6 — ~6 % do tráfego total cairia
   nessa armadilha);
3. não promete prazo que não pode cumprir ("em 1 minuto");
4. não pede os dados de novo porque a **nossa** chamada falhou.

---

## Decisão 3 — O caminho de recusa (os 30 %)

**Um fato que restringe tudo, e que precisa estar claro antes de escolher:** as duas
regras de recusa são sobre **idade do condutor** e **idade do veículo**. Nenhuma delas
depende do plano. Portanto **não existe alternativa dentro do catálogo** — trocar
Premium por Essencial não destrava nada. Qualquer opção que "ofereça outro plano" seria
uma promessa falsa, e a `/quote` a desmentiria na chamada seguinte.

O que sobra de honesto:

- registrar o lead para contato futuro (se a regra mudar, ou por outro produto);
- cotar para **outro** condutor ou **outro** veículo, se o lead tiver;
- passar a um humano que possa ter alçada de exceção — se é que tem;
- explicar e encerrar.

### As quatro posturas

| | **A · Recusa seca** | **B · Recusa + reenquadramento** | **C · Recusa + captura** | **D · Recusa via humano** |
|---|---|---|---|---|
| diz o motivo real? | sim | sim | sim | sim |
| oferece alternativa | não | sim: outro condutor ou outro veículo | não | o humano decide |
| registra para futuro | não | sim | sim, e diz que registrou | sim |
| cria handoff | não | não | opcional | **sempre** |
| fila humana | 0 % | 0 % | 0 % | **+30 %** |
| risco | lead vai embora sem rastro | soar como insistência | prometer contato que ninguém fará | fila cheia de casos sem saída |

**Trade-offs.**

- **A** é a mais honesta e a mais fria. Defensável: um "não" claro respeita o tempo do
  lead. Mas 30 % do tráfego sai sem nenhum registro de negócio — e o dataset mostra
  que esses leads existem em volume.
- **B** é a que mais parece vendas de verdade, e o reenquadramento é legítimo (a apólice
  é do condutor principal e do veículo; ambos podem ser outros). Risco: precisa de
  cuidado no texto para não soar como sugestão de burlar a regra.
- **C** é barata e sincera, **desde que exista de fato o registro** — prometer contato
  futuro sem uma tabela por trás é a promessa vazia que a regra máxima proíbe. Como o
  banco já tem `conversations` com o perfil, o registro é praticamente de graça.
- **D** é a mais cara e a menos útil: o humano vai reler a mesma regra e dar o mesmo
  "não". Só faz sentido se houver alçada de exceção — e não há indicação disso.

### Sub-decisão: o texto do motivo

A API devolve motivos escritos para sistema, não para pessoa:
`"Idade acima do limite de aceitacao (75 anos)."`

| | como fica | trade-off |
|---|---|---|
| **cru da API** | repassa o texto | rastreável e literalmente verdadeiro; frio, e sem acento |
| **mapa fixo nosso** | 3 motivos → 3 textos nossos, revisados | determinístico e humano; um mapa a manter |
| **modelo reescreve** | o LLM parafraseia o motivo | mais natural; **abre a porta para o modelo inventar exceção** ("mas posso ver um caso especial") |

A terceira opção reintroduz no caminho de recusa exatamente o risco que o template
determinístico elimina no caminho da cotação — só que agora sobre elegibilidade em vez
de preço.

### Sub-decisão: os casos que **parecem** recusa e não são

Três motivos vêm rotulados `cotacao_recusada` mas não são recusa do lead (§7.1):
veículo com ano futuro e `plano_id` inexistente. Aqui o caminho é reperguntar, não
recusar — mas **o texto de repergunta ainda precisa ser escrito**, e ele não pode
expor o erro interno ("o sistema não reconheceu o plano").

---

## Decisão 4 — O formato de saída da cotação

Todos os números abaixo são **reais**, vindos da `/quote`. O caso: Completo, 28 anos,
veículo 2019, CEP `07145-200` (alto risco), início em 17/10/2026 →
`premio_mensal 392.25` · `franquia 3000` · `carencia 30 dias (roubo, furto)` ·
`pro_rata 15/31 dias = R$ 189,80`.

### **A · Bloco compacto** — preço primeiro, 5 linhas

```
Fechei sua cotação, Marina 👇

*Completo — R$ 392,25/mês*
Cobre colisão, roubo, furto, terceiros e vidros. Franquia de R$ 3.000.

Começando dia 17/10, o primeiro boleto sai proporcional: *R$ 189,80* (15 dias).
Do mês seguinte em diante, R$ 392,25 cheio.

⚠️ Roubo e furto começam a valer 30 dias depois do início da vigência.

Quer que eu siga com a emissão?
```

### **B · Narrativa** — conversa, sem formatação de sistema

```
Consegui aqui: o Completo fica R$ 392,25 por mês pro seu perfil, com franquia de
R$ 3.000 — cobre colisão, roubo, furto, terceiros e vidros.

Como você quer começar dia 17/10, o primeiro pagamento é proporcional aos 15 dias
que faltam do mês: R$ 189,80. A partir de novembro entra o valor cheio.

Só um ponto importante pra não ter surpresa: roubo e furto têm 30 dias de carência,
contados do início da vigência. Colisão vale desde o primeiro dia.

Faz sentido pra você?
```

### **C · Ficha estruturada** — rótulos alinhados

```
📋 *Cotação — Plano Completo*

Mensalidade ....... R$ 392,25
1º pagamento ...... R$ 189,80  (17/10 a 31/10, 15 de 31 dias)
Franquia .......... R$ 3.000
Coberturas ........ colisão · roubo · furto · terceiros · vidros
Carência .......... 30 dias para roubo e furto

Posso seguir com a emissão?
```

### O que distingue as três

| | **A** | **B** | **C** |
|---|---|---|---|
| preço encontrado em | 1ª linha | meio do 1º parágrafo | linha rotulada |
| lido no celular sem esforço | sim | exige leitura | sim |
| soa como WhatsApp de vendedor | quase | **sim** | não — parece PDF |
| carência dá para pular sem ler | não (destacada) | **sim** (no meio do texto) | não |
| todo texto vem do template | sim | **não** — a narrativa pede geração | sim |
| renderizar em Markdown de WhatsApp | fácil | fácil | quebra em fonte proporcional |

O item mais pesado é o penúltimo: **B só é possível se o modelo escrever o texto ao
redor dos números.** Isso não viola o invariante (o preço continua vindo do JSON), mas
enfraquece a garantia de que carência e pro-rata **sempre** aparecem — passa a depender
do prompt em vez do template. Um meio-termo possível: parágrafo do modelo para o tom,
seguido de um bloco fixo com preço, carência e pro-rata. Custa uma mensagem mais longa.

### Sub-decisões

| | opções | trade-off |
|---|---|---|
| **preço primeiro ou último** | primeiro / depois do valor da cobertura | primeiro respeita o tempo do lead; por último "vende" antes do número — e é o padrão do dataset, que não é referência de qualidade |
| **carência: onde** | destacada / no meio / em mensagem separada | destacar reduz a chance de reclamação depois; separar dá peso demais a uma ressalva de 30 dias |
| **pro-rata quando o dia é 1** | silenciar / dizer "o primeiro mês já é integral" | silenciar é mais curto; dizer evita a pergunta "e a proporcional?" — e a ausência do campo **é** informação |
| **franquia** | sempre / só se perguntarem | é a objeção nº2 do dataset ("a franquia tá alta"); omitir adia o atrito |
| **agravo de CEP** | não mencionar / mencionar | mencionar é transparente e pode soar como justificativa de preço alto; não mencionar deixa o lead sem entender por que ficou caro |
| **quantas mensagens** | uma / duas (valor, depois detalhes) | duas imitam o ritmo do WhatsApp real; uma é mais fácil de testar e de mostrar no transcript |

---

## Como isto foi fechado

As quatro se cruzam em dois pontos, e decidir na ordem abaixo evita retrabalho:

1. **Decisão 2 primeiro** — ela define se existe mensagem de espera, e portanto se a
   cotação chega como mensagem nova. Isso muda o formato da decisão 4 (uma mensagem ou
   duas) e o gatilho `cotacao_indisponivel` da decisão 1.
2. **Decisão 3 em seguida** — ela define se a recusa cria handoff, o que muda uma linha
   da tabela da decisão 1 e ~28 pontos percentuais do volume da fila.
3. **Decisão 1** — a tabela, já com as duas linhas acima resolvidas.
4. **Decisão 4** — o formato, que é a única que não restringe as outras.

Sugiro rodar `/brainstorming` sobre as quatro nessa ordem, e depois sobre o recorte das
frentes.
