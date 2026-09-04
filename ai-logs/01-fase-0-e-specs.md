# Fase 0 e as specs — o que a IA errou, e o que eu errei

Registro da segunda etapa: mapeamento da API por execução, contratos, as quatro decisões
abertas, e as três specs de frente. Anterior à primeira linha de código de aplicação.

Complementa `00-preparacao.md`, que cobriu a leitura do desafio e as decisões de
arquitetura. O log cru desta sessão está em `sessions/`.

---

## Por que este arquivo existe

O enunciado diz que as conversas com IA entram na avaliação junto com o código. A parte
fácil de entregar é o log cru — ele está em `sessions/`. A parte que vale alguma coisa é
a que não se fabrica depois: **onde o processo pegou um erro**.

Das dez decisões de desenho que fecharam nesta etapa, **quatro foram correções de
afirmações feitas com confiança** — três minhas e uma do modelo. Nenhuma delas teria
aparecido se a spec fosse escrita direto em código: todas foram pegas no momento em que
alguém teve de justificar uma escolha por escrito, antes de existir arquivo para
justificá-la.

Um log em que o humano nunca erra é um log em que ninguém acredita. Então as quatro
estão aqui com a autoria.

---

## As quatro correções

### 1 · O gatilho híbrido do aviso de espera — **erro do modelo, pego ao escrever a opção**

Quando a `/quote` demora, o agente avisa o lead. A questão era o que dispara esse aviso.
Eu havia documentado três opções e recomendado a "híbrida": avisa por tempo **ou** na
primeira falha de tentativa, o que vier primeiro.

Ao escrever as opções para decisão, o número desmontou a recomendação. Uma falha 5xx da
`/quote` volta em **~2 ms**, e o retry responde **~250 ms** depois. Um aviso disparado
por falha de tentativa cairia nessa janela: o lead receberia *"tô verificando…"* seguido
do preço um quarto de segundo depois. Isso é ruído, não cuidado — e é exatamente o
atrito inventado que a decisão inteira existia para evitar.

O gatilho correto é só por tempo real de espera: ele ignora a falha rápida, que o lead
não percebe, e pega os dois casos de espera de verdade — a chamada lenta de 8 s e o
timeout de 12 s.

**O que isso ensina sobre o método:** a recomendação estava escrita antes de a medição
da latência de falha existir. Escrever a opção com o número ao lado foi o que a derrubou.

Houve um segundo round no mesmo ponto, e é ele que mostra que o erro não é raro: mais
tarde eu movi o disparo para um watchdog genérico na camada de conversa, achando que
simplificava. O usuário reverteu observando que ele dispararia **durante a geração do
modelo** — e uma pergunta simples respondida em 6,5 s receberia "só um instante" seguido
da resposta 0,2 s depois. O mesmo erro, em outro lugar, cometido por quem tinha acabado
de argumentar contra ele.

### 2 · Os 42 % do dataset — **erro meu, corrigido por medição**

A análise de preparação afirmava que 42 % das cotações do dataset eram matematicamente
impossíveis para o plano anunciado. O número saiu de um teste de **intervalo**: o preço
cai entre o valor base e o valor base vezes todos os multiplicadores?

O teste está errado, e o modelo refez a conta. O intervalo é contínuo, mas o conjunto de
prêmios alcançáveis é **discreto**: 3 planos × 4 faixas etárias × 3 faixas de veículo ×
2 regiões = **72 valores possíveis**, de R$ 119,90 a R$ 1.025,14. O teste correto é
pertinência ao conjunto, não ao intervalo.

Nenhum dos 8 preços que o dataset usa está no conjunto. **2.500 de 2.500 = 100 %
impossíveis.** Os 58 % que "caíam na faixa" eram coincidência de intervalo, não cálculo.

A conclusão original ficou mais forte, não mais fraca — mas por pouco: um número
subestimado que confirma a sua tese é o tipo de erro que ninguém procura.

### 3 · O reenquadramento por condutor — **erro do modelo, pego por mim**

Trinta por cento dos leads do dataset são incotáveis: idade acima de 75, ou veículo com
mais de 20 anos. A decisão era como recusar sem queimar o lead.

O modelo propôs oferecer reenquadramento nos dois casos: cotar para outro veículo da
casa, **ou para outro condutor principal**. Escreveu que era "como seguro funciona".

Para o veículo, é. Para o condutor, não: se quem dirige de fato tem 78 anos, declarar
outra pessoa como condutor principal é **declaração falsa**, e a conta chega como
negativa de sinistro — no pior momento possível para o cliente. Um agente de vendas que
ensina esse caminho cria passivo para a seguradora e prejuízo para o lead.

A distinção que ficou no contrato não é de resultado, é de origem: **se o lead disser
espontaneamente que quem dirige é outra pessoa, recotamos.** Registrar um fato que ele
trouxe é uma coisa; sugerir o caminho é outra.

Esse mesmo raciocínio voltou depois num terceiro lugar, e por isso vale registrar: ao
desenhar o guardrail, o modelo quis abrir uma exceção para deixar o LLM falar livremente
num turno de recusa, argumentando que "ali não há preço a alucinar". Verdade, e
irrelevante — o risco na recusa não é preço, é **promessa falsa**: *"vou ver com o setor
de exceções"*. Era a mesma classe de erro, três parágrafos depois de o próprio modelo ter
escrito que lista de exceções é onde guardrail morre.

### 4 · A asserção invertida do replay — **erro meu, corrigido pelo modelo**

Ao especificar a avaliação, escrevi a asserção que o replay do dataset deveria checar:

> *"lead incotável chamou `escalate_to_human` e não chamou `quote_plan`"*

Está errada em dois pontos, e os dois são consequência de decisões que eu mesmo tinha
fechado antes.

**Um:** fechamos que recusa **não cria handoff** — um humano releria a mesma regra fixa
em `plans.json` e daria o mesmo "não". Chamar `escalate_to_human` num lead incotável é o
defeito, não o acerto.

**Dois, e mais fundo:** o agente **não tem como saber** que o lead é incotável. O
catálogo de planos que vai no system prompt tem nomes e coberturas e **nenhuma regra** —
nem limite de idade, nem de ano do veículo, nem valor monetário. Foi desenhado assim de
propósito. Quem decide elegibilidade é a API, exatamente como quem decide preço.

A asserção correta é a inversa: **o lead incotável chama `quote_plan`, recebe `refused`,
entrega o texto de recusa e não escala.**

Vale a formulação que saiu daí, porque ela resume a arquitetura inteira numa linha:
**não perguntamos ao modelo se o lead é elegível, do mesmo jeito que não perguntamos o
preço.**

---

## O que o método produziu, além das quatro

Três achados sobre a API que não estavam em nenhuma hipótese, e que só apareceram porque
o mapeamento foi feito **executando** em vez de lendo:

- **A falha mascara a recusa.** O sorteio de instabilidade roda antes da regra de
  negócio. Um lead de 80 anos com `FAILURE_RATE=1.0` devolveu `502 503 502 500 502` —
  nunca 422. Na primeira chamada é impossível distinguir "lead inelegível" de "legado
  caiu", e ~20 % dos leads incotáveis se apresentam primeiro como indisponibilidade.
- **Teto de 40 chamadas lentas concorrentes.** Com 60 simultâneas, 40 terminaram em
  ~8,8 s e 20 enfileiraram para ~16,6 s — acima de qualquer timeout razoável.
- **`plano_id: ""` cota `essencial` com status 200.** Uma falha de extração vira cotação
  errada silenciosa, sem sinal HTTP nenhum.

E uma correção de taxonomia: o `422` da API carrega **dois erros de naturezas opostas**
sob o mesmo status — regra de negócio (`{"error":"cotacao_recusada"}`) e bug nosso
(`{"detail":[...]}`, a validação do Pydantic). Dentro do primeiro, ainda há dois casos
que são bug nosso vestido de recusa. A regra "422 nunca retenta" continua; o que muda é
o que se diz ao lead.

---

## Como a IA foi usada

Uma sessão de orquestração, com o modelo produzindo e o humano decidindo. O processo que
pegou os quatro erros tem três partes, e nenhuma delas é sobre a IA ser boa ou ruim:

1. **Medir antes de projetar.** Sete instâncias da API de cotação, configuradas para
   isolar cada efeito da instabilidade. Todo número no repositório saiu de uma execução,
   e é por isso que os três achados acima existem.
2. **Opções com trade-off, não recomendações.** As quatro decisões conversacionais
   vieram como opções numeradas com o custo de cada uma. Foi ao escrever o custo que o
   gatilho híbrido caiu.
3. **Spec antes de plano, plano antes de código.** Uma página por frente, com uma seção
   obrigatória de dúvidas. Três das quatro correções aconteceram nessa seção — que é
   barata, porque ali não existe código escrito para defender.

O custo do processo é real: nada rodou até a Fase 0 fechar. A aposta é que quatro erros
pegos em prosa custam menos que quatro erros pegos em produção — e dois deles
(a declaração falsa e a asserção invertida) não seriam pegos em produção nunca, porque
ambos produzem um sistema que funciona e está errado.
