# Decisões fechadas

As opções e os trade-offs que levaram até aqui estão em `docs/DECISOES-ABERTAS.md`,
mantido como registro do que foi considerado e descartado. **Este documento é o
contrato.** O que está aqui não se reabre; o que mudar, muda por decisão nova e escrita.

---

## 1 · O que o agente faz quando a `/quote` não responde

> O critério que o enunciado diz que mais separa.

**Postura: avisa e continua em background.** O agente não segura o turno esperando o
legado. Ele avisa, o job segue tentando, e o valor chega **como mensagem nova** quando
chegar.

| | |
|---|---|
| gatilho do aviso | 6 s **contados da chegada da mensagem do lead**, despachado de dentro da tool de cotação |
| reforço | aos ~20 s do mesmo relógio |
| desfecho | o preço renderizado, ou handoff se o job terminar `failed` |
| handoff | só em `failed` — 0,8 % em produção, 100 % no cenário degradado |

### O relógio é o do lead; o disparo é da tool

Duas coisas separadas, e é fácil confundi-las.

**O relógio é o do lead.** Ele começa quando o lead aperta enviar, não quando a nossa
tool começa a esperar. Um turno gasta tempo antes da cotação — a latência do modelo — e
medir a partir do job faria o aviso chegar depois de o lead já ter ficado 8 s no escuro.
O ajuste é um parâmetro: o timestamp de chegada da mensagem entra na tool, e a contagem
sai de lá.

**O disparo é de dentro da tool**, pelo `ChannelAdapter`. Um watchdog genérico na camada
de conversa pareceria mais simples e seria pior: ele dispararia **durante a geração do
modelo**, e uma pergunta que levasse 6,5 s para ser respondida receberia "só um instante"
seguido da resposta 0,2 s depois. É exatamente o atrito inventado que descartamos no
gatilho por tentativa, só que em outro lugar. Dentro da tool, o aviso só existe quando há
de fato uma cotação em voo — que é o único caso em que a espera é longa por construção.

Fora do caminho da cotação há um **segundo relógio**, na camada de conversa, com
limiar de **10 s** e texto próprio (`docs/TEXTOS.md` ①b). O limiar mais alto é o que
evita o ruído: a demora da cotação é projetada — 8 s de sono, por construção — e 6 s a
pega antes; a do modelo é anômala, e 6,5 s ainda é latência plausível, enquanto 10 s já
é sintoma.

Os nove textos aprovados vivem em **`docs/TEXTOS.md`**, que é a origem única de onde a
implementação copia. O handoff é sempre **um prefixo opcional mais a despedida**, numa
tabela de quatro linhas — o que mantém o descarte do texto do modelo sem exceção em
todo caminho de encaminhamento.

### Por que por tempo, e não por tentativa

Uma falha 5xx volta em ~2 ms, e o retry responde ~250 ms depois. Um aviso disparado
por *falha de tentativa* cairia aí — o lead receberia "tô verificando…" seguido do
preço um quarto de segundo depois. Isso é ruído, não cuidado.

O gatilho por tempo ignora a falha rápida com retry rápido, que o lead não percebe, e
pega exatamente os dois casos em que existe espera de verdade: a chamada lenta de 8 s
(10 % do tráfego, e que **dá certo**) e o timeout de 12 s. Um parâmetro só, e o critério
é o que o lead sente, não o que acontece por dentro.

**Custo assumido do limiar de 6 s:** no caso lento de 8 s, o aviso chega faltando 2 s
para o preço. Preferimos isso a avisar em situações que se resolveriam sozinhas — o
silêncio de 6 s é curto o bastante para não parecer queda.

### A sequência do cenário degradado

```
+0.0s    lead pede a cotação
+6.0s    aviso de espera                                         ← da tool, relógio do lead
+20.0s   reforço                                                 ← da tool
+37.1s   handoff — o job terminou failed
```

O transcript entregue marca **tempo relativo por linha** (`[+6.2s]`), para o avaliador
ler a política funcionando com número em vez de acreditar na descrição.

São duas mensagens em 37 s: o ritmo de quem está realmente tentando. Sem elas, o
transcript degradado — que é o que o avaliador vai olhar — teria uma frase e um buraco
de 31 s.

**As três mensagens são texto de template, não geradas.** Elas são o produto do
comportamento sob falha, e não podem variar com a temperatura do modelo.

### O que o agente nunca faz, em nenhuma circunstância

1. não diz um preço que não veio de um `quote_id` com status `ok`;
2. não conclui recusa a partir de um 5xx (~6 % do tráfego cairia nessa armadilha);
3. não promete prazo que não pode cumprir;
4. não pede os dados de novo porque a **nossa** chamada falhou.

---

## 2 · O caminho de recusa (30 % do tráfego)

**Motivo real + reenquadramento + registro. Não cria handoff.**

### O fato que restringe tudo

As duas regras de recusa são sobre **idade do condutor** e **idade do veículo**, e
nenhuma delas depende do plano. Trocar Premium por Essencial não destrava nada.
Qualquer oferta de "um plano mais barato" seria promessa falsa, e a `/quote` a
desmentiria na chamada seguinte.

### O reenquadramento, e o seu limite

| Motivo da recusa | O agente oferece | Por quê |
|---|---|---|
| veículo com mais de 20 anos | cotar **outro veículo** da casa | a apólice é de um veículo específico; se há outro, é outra cotação, e é legítima |
| idade ≥ 76 (ou < 18) | **nada** — explica e registra | ver abaixo |

**Para a recusa por idade, o agente não sugere trocar o condutor principal.** Se quem
dirige de fato tem 78 anos, declarar outra pessoa como condutor principal é declaração
falsa — e a conta chega como negativa de sinistro, no pior momento possível para o
cliente. Um agente de vendas que ensina o caminho da declaração falsa cria um passivo
para a seguradora e um prejuízo para o lead.

**Se o lead disser espontaneamente que quem dirige é outra pessoa, aí sim recotamos.**
Registrar um fato que o lead trouxe é uma coisa; sugerir o caminho é outra. A diferença
não é de resultado — é de quem originou a informação, e é ela que separa qualificação
de instrução para fraudar.

### A oferta vem dentro do template, e o reenquadramento leva dois turnos

O template da recusa por veículo **já carrega a oferta**; os outros dois não. O modelo
não escreve nada no turno da recusa — vale a mesma regra de descarte que vale para a
cotação, sem exceção.

Isso não é rigidez gratuita. O risco de soltar o modelo num turno de recusa não é
alucinar preço — não há preço ali. É **promessa falsa**: "vou ver com o setor de
exceções", "consigo uma autorização especial". É o mesmo erro que já cortamos no
reenquadramento por condutor, e abrir uma exceção no descarte para acomodá-lo seria a
primeira entrada numa lista de exceções — que é onde guardrail morre.

O custo é pequeno porque o espaço é pequeno: são três textos, e só um ganha oferta.

O turno seguinte é livre. O lead reage à oferta, aquele turno **não tem resultado de
tool**, o modelo conversa normalmente e pode chamar `quote_plan` de novo com o outro
veículo. O reenquadramento acontece em dois turnos, sem nenhuma exceção na regra.

### O texto do motivo vem de um mapa fixo

Três motivos de recusa reais → três textos nossos, revisados. Não o texto cru da API
(escrito para sistema, sem acento) e **não o modelo parafraseando**: deixar o modelo
reescrever a recusa reintroduz no caminho de elegibilidade exatamente o risco que o
template determinístico elimina no caminho do preço — só que agora o modelo estaria
livre para inventar uma exceção que não existe.

### O registro

O lead recusado fica visível no admin, com o perfil e o motivo. **Não prometemos
contato futuro**, porque não há quem faça esse contato — prometer seria a promessa vazia
que a regra máxima proíbe. Dizemos que o registro existe, o que é verdade e é útil.

### Não cria handoff

Um humano releria a mesma regra fixa em `plans.json` e daria o mesmo "não". Encaminhar
30 % do tráfego para isso encheria a fila com casos sem saída. A recusa é um desfecho
que o bot resolve, não uma exceção que ele delega.

---

## 3 · A tabela de gatilhos de handoff

**Critério: custo do erro.** Não "quantos casos cobrir", mas *quanto custa o agente
errar naquele ponto*. Custo alto encaminha na hora e sem tentar; custo baixo tenta e
encaminha na segunda.

| # | Gatilho | Dispara quando | Custo do erro | Ação |
|---|---|---|---|---|
| 1 | `assunto_sensivel` | sinistro, jurídico, saúde, reclamação formal | alto | encaminha **imediato**, sem tentar responder |
| 2 | `guardrail` | injeção de prompt, abuso | alto | encerra e registra |
| 3 | `lead_pediu` | o lead pede uma pessoa | — | encaminha |
| 4 | `cotacao_indisponivel` | job de cotação terminou `failed` | alto | encaminha |
| 5 | `extracao_falhou` | 2ª falha de extração no mesmo campo | médio | encaminha |
| 6 | `objecao_fora_da_alcada` | o lead **repete** a objeção de preço | baixo | encaminha na 2ª |
| 7 | `midia_sem_texto` | o lead **insiste** em mídia depois de pedirmos texto | baixo | encaminha na 2ª |

Fila estimada: **~8 %** dos leads.

**Não são gatilhos:** recusa 422 (§2), falha isolada da `/quote` que o retry resolveu,
primeira objeção de preço, primeira mídia.

### Precedência

Lista fixa, na ordem da tabela, **primeiro que casa vence**. O handoff grava também os
gatilhos secundários que casaram no mesmo turno, então a fila mostra **um** gatilho — o
que mantém a regra testável, uma linha por gatilho — sem que o operador perca o quadro
completo ao assumir.

### Depois de encaminhar, o agente encerra a participação

Avisa que um atendente vai assumir e para de responder. O estado `encaminhado` é
terminal de verdade, o que remove qualquer ambiguidade sobre quem está falando e é o
mais simples de testar.

**Consequência assumida, e ela é real:** na segunda objeção de preço o bot encerra no
meio de uma negociação. É defensável — a 2ª objeção é sinal de que ele não vai fechar
sozinho — mas exige que o texto de despedida seja bom o bastante para o lead não achar
que foi ignorado. O texto é de template, e é um dos que mais merecem cuidado.

---

## 4 · O formato da cotação

**Bloco compacto. Uma mensagem. Todo o texto sai do template.**

```
Fechei sua cotação 👇

*Completo — R$ 392,25/mês*
Cobre colisão, roubo, furto, terceiros e vidros.
Franquia de R$ 3.000.

Começando dia 17/10, o primeiro boleto sai proporcional: *R$ 189,80* (15 dos 31 dias).
Do mês seguinte em diante, R$ 392,25 cheio.

⚠️ Roubo e furto começam a valer 30 dias depois do início da vigência.

Quer que eu siga com a emissão?
```

Os números do exemplo são reais, vindos da `/quote`: Completo, 28 anos, veículo 2019,
CEP `07145-200`, início em 17/10/2026.

| Sub-decisão | Escolha | Por quê |
|---|---|---|
| ordem | preço na primeira linha | respeita o tempo do lead; "vender antes do número" é o padrão do dataset, que não é referência de qualidade |
| carência | marcador próprio, linha isolada | é impossível pular sem ver, e é a ressalva que gera reclamação depois se passar batida |
| franquia | **sempre** | é a objeção nº 2 do dataset; omitir só adia o atrito |
| agravo de CEP | **não mencionar** | soaria como justificativa de preço alto sem o lead ter perguntado |
| pro-rata no dia 1 | dizer "o primeiro mês já é integral" | a ausência do campo **é** informação; silenciar gera a pergunta |
| nº de mensagens | uma | o transcript fica legível, e a mensagem precisa funcionar sozinha — em 10 % dos casos ela chega depois de um aviso de espera |

### Por que não a narrativa

A versão em parágrafos corridos soa mais como vendedor de verdade, e o dataset mostra
que esse é o registro do canal. Ela foi descartada por um motivo específico: só é
possível se o modelo escrever o texto ao redor dos números. Isso não violaria o
invariante do preço — ele continuaria vindo do JSON — mas a garantia de que **carência
e pro-rata sempre aparecem** passaria a depender do prompt em vez do template. Trocar
uma garantia estrutural por uma probabilística, para ganhar naturalidade, é o lado
errado do trade-off nesta entrega.

---

## 5 · Observabilidade: `turn_usage` em vez de Langfuse

O Langfuse **não é o primeiro item da lista de cortes — está fora do escopo**, e o que
entra no lugar é melhor para o que precisamos provar.

### Por que o Langfuse sai

Langfuse v3 e v4 exigem seis componentes: containers `web` e `worker`, PostgreSQL,
ClickHouse, Redis e S3/blob storage. Cerca de 5,6 GB de imagens e 3,2 GB de RAM, medidos
numa instância real. Não existe variante enxuta, e isso não é um detalhe de configuração
— é decisão de projeto, registrada na própria documentação deles:

> *"We explored building a multi-database adapter to support Postgres for smaller
> self-hosted deployments. After talking to engineers and reviewing some of PostHog's
> Clickhouse implementation, we decided against this path due to its complexity and
> maintenance overhead."*
> — [Migrate Langfuse v2 to v3](https://langfuse.com/self-hosting/upgrade/upgrade-guides/upgrade-v2-to-v3)

E o guia de migração para v4 confirma que a arquitetura continua a mesma:
*"The infrastructure is identical to v3 (web/worker, PostgreSQL, ClickHouse, Redis, S3)."*

**Uma métrica que exige 5,6 GB de download para ser conferida é alegação, não
evidência.** O critério nº 1 do desafio é "funciona", e o comando é `docker compose up`.

### O que entra no lugar

**A tabela `turn_usage`** (`db/migrations/0002_turn_usage.sql`), preenchida a cada turno
a partir de `response.metrics` do Agno — um `RunMetrics`, que é a granularidade certa:
um turno com tool call faz várias chamadas ao modelo, e o que interessa é o custo do
turno, não o de cada chamada.

Ela sustenta duas coisas que de outro modo seriam frases no README:

1. **O prompt caching funciona.** `cache_read > 0` a partir do segundo turno é a prova,
   em número, na nossa própria base.
2. **Quanto custa uma conversa.** Painel de custo no admin: custo por conversa,
   acumulado, taxa de acerto de cache, Anthropic e Ollama lado a lado.

**O preço vem de `config/model_pricing.yaml`**, com vigência e fonte, nunca embutido no
código. E `turn_usage.pricing_vigencia` grava qual entrada foi usada, para que um custo
histórico continue auditável depois que a tabela de preços mudar.

Duas descobertas da documentação do Agno que moldaram o desenho:

- **A Anthropic não popula o campo `cost`** do Agno (só OpenAI Chat e Meta Llama-OpenAI
  populam). Calcular do nosso lado não é preferência — é a única opção.
- **O Ollama não popula `cache_read`/`cache_write`.** Por isso essas colunas são
  anuláveis e o painel mostra **"n/a"**, não "0 %": um zero ali diria "o cache não
  acertou" onde a verdade é "não existe cache neste caminho".

### O que fica disponível se sobrar tempo

A instrumentação OpenTelemetry continua sendo poucas linhas e inerte sem chave. Se
sobrar tempo no fim, ela entra atrás de um profile — mas nada no caminho crítico
depende dela, e o painel de custo não depende dela de forma alguma.

---

## 6 · Avaliação: módulos nativos do Agno antes de harness próprio

Confirmado na documentação oficial via MCP `agno-docs`:

| Módulo | Import | O que faz | Persiste |
|---|---|---|---|
| `ReliabilityEval` | `agno.eval.reliability` | assere que as tools esperadas foram chamadas, com os argumentos esperados (`expected_tool_calls`, `expected_tool_call_arguments`) | `db=PostgresDb(db_url=..., eval_table="eval_runs")` |
| `AgentAsJudgeEval` | `agno.eval.*` | juiz por modelo, com `criteria`, `scoring_strategy` (`numeric` 1–10 ou `binary`) e `threshold` | idem |

> ⚠️ A classe é **`AgentAsJudgeEval`**, não `AgentAsJudge`.

Ambos gravam no **mesmo Postgres da aplicação**, o que significa que o resultado da
avaliação fica disponível para quem rodar o projeto, sem serviço externo — a mesma
lógica que motivou o §5.

Isso cobre as asserções mais importantes do replay do dataset:

- lead **incotável** → chamou `escalate_to_human`, **não** chamou `quote_plan`;
- lead **cotável** → chamou `quote_plan` com a idade e o ano corretos, extraídos do
  texto livre.

O harness próprio fica reservado para o que os módulos nativos não cobrem: a
verificação de preço, que é **cálculo**, não julgamento. Preço se confere contra o
conjunto fechado de 72 prêmios possíveis e contra a própria `/quote` — nunca por juiz
de modelo, e nunca contra as falas do vendedor no dataset, que são 100 % inválidas.

---

## 7 · O recorte das frentes

Seis frentes viraram **três, mais dois passes**. Backend e AI Engineer disputam os
mesmos arquivos nas fatias 1 a 6 e não se separam de verdade.

| Frente | Entrega | Depende de | Quando |
|---|---|---|---|
| **Núcleo** | agente, tools, `QuoteClient`, renderer, canal console, persistência, handoff, recusa, `turn_usage` | contratos da Fase 0 | fatias 1–6, sequencial, uma sessão por fatia |
| **Frontend** | as quatro telas + painel de custo, evidência Playwright | `openapi.yaml` congelado + estado real no banco | abre na **fatia 4** |
| **Dados/QA** | bronze → silver → gold, replay com os evals nativos, suítes de degradação | módulo de PII (nasce na fatia 1) | fatia 9 |
| passe: documentação | README, `ARQUITETURA.md`, diagramas Mermaid | tudo pronto | fatia 10 |
| passe: segurança | plugins Trail of Bits, checklist de repo público | tudo pronto | fatia 10, antes do push |

Duas frentes ativas no máximo, em arquivos disjuntos (`web/` vs `app/`).

**Por que o Frontend abre na fatia 4 e não antes:** a evidência de UI exige estado real,
gerado pelo sistema — screenshot com dado de exemplo não vale. Antes da fatia 4 não
existe degradação, breaker nem tentativa falha para a tela mostrar.

**O módulo de mascaramento de PII não pertence à frente de Dados.** Ele nasce na fatia 1,
porque toda mensagem persistida passa por ele desde a primeira. A frente de Dados
reutiliza o mesmo módulo no pipeline.

O Frontend usa `/frontend-design` na criação das telas e `/impeccable` na revisão.

### Ordem de corte, se o dia 3 apertar

1. camada gold do dataset
2. vídeo
3. detalhe de `/admin/status` — ficam `/health` e taxa de sucesso, saem p50/p95
4. adaptador `web` — fica só o console, com o motivo declarado no README

**Nunca cortar:** `QuoteClient` inteiro · tabela de handoff com um teste por gatilho ·
persistência com id e status · README de decisões · o transcript reproduzível ·
`ai-logs/`.

---

## 8 · Decisões da frente de Frontend

**Painel de custo: seção de `/admin/status`, não quinta tela.** São seis números, e uma
rota nova para seis números é escopo por escopo. O leitor é um só — o avaliador — e ele
já vai a `/admin/status`, porque é lá que o circuit breaker aparece. Custo sentado ali é
visto sem procurar. Duas condições: **bloco com título próprio e âncora**, não um rodapé;
e **nomeado no README**, porque é a parte que quase ninguém faz num take-home e não pode
depender de o avaliador tropeçar nela.

**Exposição: `127.0.0.1` mais `ADMIN_TOKEN` opcional.** O controle que de fato importa é
o bind — uma linha no compose, e a superfície administrativa fica inalcançável da rede
independente de autenticação. Sobre ele, um token exigido quando definido e ausente por
padrão. Não é uma coisa ou outra: o bind é a segurança, o token é a resposta pronta ao
achado do passe de segurança da fatia 10.

**Navegação assimétrica: `chat → admin` sim, `admin → chat` não.** O link de "ver esta
conversa no admin" é a demonstração inteira da rastreabilidade, e chegar lá no segundo
seguinte, enquanto o avaliador ainda lembra o que digitou, é o que a torna vívida. O
inverso não existe: por ele o avaliador assumiria o lugar do lead numa conversa que já
tem handoff, e isso não tem resposta boa.

**`/chat` retoma a sessão corrente ao carregar.** Sessão em cookie ou `localStorage`,
mais um botão explícito de **nova conversa**. Sempre-nova é o comportamento certo do
botão, não do carregamento: um F5 no meio da conversa destruiria a demonstração.
