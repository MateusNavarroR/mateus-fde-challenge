# AutoSeguro — agente de cotação de seguro de veículo

Um agente que conversa com o lead, qualifica, cota um plano contra uma API de cotação
instável e decide sozinho quando o caso deixa de ser dele. O centro do projeto não é a
conversa: é **o que o agente faz quando a `/quote` não responde** e **como ele nunca diz
um número que não veio da API**.

Este README é sobre as decisões e o porquê de cada uma. O mapa de módulos, os contratos
internos, os diagramas revisados contra o código e as invariantes de implementação
estão em `docs/ARQUITETURA.md`.

---

## Como rodar

```bash
cp .env.example .env      # e preencha ANTHROPIC_API_KEY — é a única obrigatória
docker compose up --build
```

Abra **http://127.0.0.1:8080**. Não há segundo passo, segundo comando nem porta
secundária: o frontend é servido pela mesma origem da API, e o banco e a API de cotação
sobem na rede interna do compose.

| Variável | Obrigatória | O que faz |
|---|---|---|
| `ANTHROPIC_API_KEY` | **sim** | credencial do modelo. Sem ela o boot falha **alto**, e não no meio de uma conversa. |
| `APP_LLM_MODEL` | não | model-string do Agno. Default `anthropic:claude-sonnet-5`; `ollama:qwen2.5:7b` também é validado. |
| `ADMIN_USER` + `ADMIN_PASSWORD` | não | ligam o login do `/admin`, com cookie `httpOnly` + `SameSite=Strict`. Ausentes, o admin abre direto. |
| `ADMIN_TOKEN` | não | protege o `/admin` por cabeçalho, para CI e `curl`. Ver a ressalva em *Limitações*. |
| `QUOTE_FAILURE_RATE`, `QUOTE_SLOW_RATE`, `QUOTE_SLOW_SECONDS`, `QUOTE_SEED` | não | a instabilidade simulada da `/quote`. Os defaults são os do desafio: 20% de falha, 10% lentas de 8 s. |

**Só a 8080 é publicada, e em `127.0.0.1`.** Banco e API de cotação ficam na rede
interna: nada de conflito com um Postgres já instalado, e nada alcançável da rede
local. Para depurar com as portas expostas: `docker compose --profile debug up`.

### Rodar os testes

```bash
uv sync
docker compose --profile debug up -d db-debug        # o Postgres na 5432
uv run pytest -q -m "not live"                       # sem rede e sem modelo
```

Os marcados `live` falam com a `/quote` de verdade e com o modelo; `serial` dependem da
seed da `/quote` e **não podem** rodar em paralelo (ver *Reprodutibilidade*).

### Gerar o log de execução completa

```bash
QUOTE_FAILURE_RATE=0 QUOTE_SLOW_RATE=0 docker compose up -d --build --wait
docker compose exec -T app python scripts/transcript.py --cenario feliz \
  > artifacts/transcript-feliz.md
```

O cabeçalho de cada artefato traz o comando exato que o reproduz, incluindo o cenário
degradado.

---

## O que está implementado

Cada linha aqui tem código rodando e teste que a sustenta. O que não tem está em
*Limitações assumidas e o que não foi testado*, e não nesta lista.

**O agente, de ponta a ponta**
- conversa, qualifica os cinco campos, cota e decide sozinho — `artifacts/transcript-feliz.md` mostra do «oi» à cotação;
- **o preço nunca vem do modelo**: a tool devolve um `quote_id`, o texto é renderizado por template, e três verificações no ponto de estrangulamento da persistência impedem que qualquer outro caminho escreva um número;
- prompt injection é caso de teste, determinístico e vivo (`tests/nucleo/test_injecao.py`).

**Quando a `/quote` falha** — *o critério que o enunciado chama de o que mais separa*
- read timeout de 12 s (maior que os 8 s da chamada lenta), 3 tentativas, backoff com full jitter, semáforo de 8 e circuit breaker;
- **a cotação é um job com estado**, porque o pior caso da política não cabe num turno: aviso ao lead aos 6 s, reforço aos 20 s, encaminhamento quando as tentativas se esgotam;
- `artifacts/transcript-degradado.md` mostra a sequência com o tempo em cada linha.

**Handoff**
- oito gatilhos como dados, com precedência declarada e um teste cada;
- a fila distingue **regra determinística** de **decisão do modelo**;
- recusa da `/quote` **não** vira handoff, e o motivo está no contrato.

**Rastreabilidade**
- cada mensagem com id, índice, autor, status e hora; cada cotação com id, status, prêmio e uma linha por tentativa HTTP;
- `/admin` com conversas, detalhe, status da integração e fila de handoff, recebendo em tempo real.

**Dados sensíveis**
- PII mascarada **na escrita**: não existe versão crua do lado do servidor;
- a varredura de PII roda na suíte, sobre tudo que é versionado e não é código, sem lista de exceções.

**Custo e cache**
- `turn_usage` por turno, com preço vindo de `config/model_pricing.yaml` com vigência;
- painel de custo no admin, por provider e por conversa.

---

## As decisões, e o porquê de cada uma

### 1. O preço nunca vem do modelo — e o mecanismo, não só a intenção

O LLM decide *quando* cotar e *como* conversar. Ele nunca decide *qual número escrever*.

Isso não é uma instrução no prompt. É estrutura:

- A resposta da cotação é **renderizada por template determinístico** a partir do JSON da
  `/quote`. O modelo não escreve o turno de cotação — o texto dele é descartado, e o
  bloco de preço é montado por código.
- **Nenhum valor monetário sai no texto sem um `quote_id` com status `ok`.** Não existe
  caminho no código em que um número apareça sem esse id.
- Os textos de espera, falha, recusa e encaminhamento (`docs/TEXTOS.md`) **não têm
  interpolação**: nenhum slot, nenhum nome, nenhum número. Isso torna possível a
  verificação final do guardrail — **comparação byte a byte** entre a mensagem
  persistida e o render esperado. Um preço alucinado não sobrevive a essa comparação,
  porque nenhum texto fixo tem lugar onde um número caiba.

O mesmo descarte vale no **turno de recusa**, e ali o risco não é preço alucinado — não
há preço. É **promessa falsa**: "vou ver com o setor de exceções", "consigo uma
autorização especial". Abrir uma exceção no descarte para acomodar a recusa seria a
primeira entrada numa lista de exceções, que é onde guardrail morre. Os três motivos
reais de recusa têm três textos nossos, revisados; um deles carrega a oferta de
reenquadramento dentro do próprio template.

O template também garante o que é fácil omitir: a **carência de 30 dias** em roubo e
furto vem em 100 % das respostas 200 e entra numa linha isolada com marcador próprio; a
**franquia** aparece sempre; o **pro-rata do primeiro pagamento** aparece quando existe,
e quando não existe (início no dia 1) a mensagem diz que o primeiro mês já é integral —
porque a ausência do campo também é informação.

Foi por isso que a versão narrativa da cotação, em parágrafos corridos, foi descartada.
Ela soa mais como vendedor de verdade, mas só é possível se o modelo escrever o texto ao
redor dos números — e aí a garantia de que carência e pro-rata sempre aparecem passa a
depender do prompt em vez do template. Trocar uma garantia estrutural por uma
probabilística, para ganhar naturalidade, é o lado errado do trade-off aqui.

### 2. O catálogo entra no prompt sem valor monetário — e sem regra

O agente conhece os planos: nomes, coberturas, franquia, o que diferencia um do outro.
Ele precisa disso para conversar. O que ele **não** tem no prompt é qualquer número de
preço, qualquer multiplicador, e **qualquer regra de elegibilidade**.

Duas consequências, e ambas são deliberadas:

- **Preço.** Um modelo que sabe a base mensal e os multiplicadores consegue produzir um
  número plausível. Plausível é exatamente o pior resultado possível: passa
  despercebido. Sem os números no contexto, a única fonte de preço é a resposta da API.
- **Elegibilidade.** O catálogo não tem limite de idade nem de ano do veículo. **Quem
  decide se o lead é cotável é a `/quote`, exatamente como quem decide o preço.** O
  agente chama `quote_plan` também para o lead que será recusado — a recusa é o
  resultado da chamada, não uma pré-avaliação nossa.

Dito com as palavras que o contrato usa: **não perguntamos ao modelo se o lead é
elegível, do mesmo jeito que não perguntamos o preço.**

Isso tem uma consequência que a medição da API tornou obrigatória. O sorteio de
instabilidade acontece **antes** da regra de negócio: um lead de 80 anos, com
`FAILURE_RATE=1.0`, devolveu `502 503 502 500 502` — nunca um 422. Com o default de 20 %,
cerca de um em cada cinco leads incotáveis se apresenta primeiro como indisponibilidade.
Daí as duas proibições absolutas: **nunca concluir recusa a partir de um 5xx**, e **nunca
concluir indisponibilidade sem esgotar as tentativas**. É o retry que revela a recusa —
o mesmo mecanismo que existe para a resiliência é o que produz o diagnóstico correto.

Há ainda três campos que erram **sem status HTTP nenhum**, e por isso são validados e
normalizados antes da chamada: `plano_id` vazio cota `essencial` calado (string vazia é
falsy do outro lado), um CEP de sete dígitos (`"7000-000"`, zero à esquerda perdido —
erro de digitação corriqueiro em conversa) zera um agravo de 30 %, e `data_inicio` fora
do ISO vira um 400. Nenhum deles produz erro visível; todos produzem a cotação errada.

### 3. A cotação é um job com estado — por aritmética, não por preferência

O pior caso da política de resiliência é **3 tentativas × 12 s + backoff ≈ 37 s**.
Ninguém espera meio minuto por uma resposta de chat sem achar que o atendimento caiu.
Não cabe num turno. Logo:

> A cotação é um **job com estado** (`pending → ok | refused | failed`), e o agente
> **fala antes de ter o preço**.

O agente não segura o turno esperando o legado. Ele avisa, o job segue tentando, e o
valor chega **como mensagem nova** quando chegar.

| | |
|---|---|
| aviso de espera | **6 s**, contados da chegada da mensagem do lead |
| reforço | **~20 s**, do mesmo relógio |
| desfecho | o preço renderizado, ou handoff se o job terminar `failed` |

Dois detalhes que parecem menores e não são:

**O relógio é o do lead; o disparo é da tool.** A contagem começa quando o lead aperta
enviar, não quando a nossa tool começa a esperar — um turno gasta tempo antes da cotação
(a latência do modelo), e medir a partir do job faria o aviso chegar depois de o lead já
ter ficado 8 s no escuro. Mas o disparo sai **de dentro da tool de cotação**, não de um
watchdog genérico na camada de conversa: um watchdog genérico dispararia durante a
geração do modelo, e uma pergunta que levasse 6,5 s para ser respondida receberia "só um
instante" seguido da resposta 0,2 s depois. Dentro da tool, o aviso só existe quando há
de fato uma cotação em voo.

Fora do caminho da cotação existe um segundo relógio, na camada de conversa, com limiar
de **10 s** e texto próprio. O limiar mais alto é o que evita o ruído: a demora da
cotação é projetada — 8 s de sono, por construção do legado — e 6 s a pega antes; a do
modelo é anômala, e 6,5 s ainda é latência plausível, enquanto 10 s já é sintoma.

**Por tempo, não por tentativa.** Uma falha 5xx volta em ~2 ms e o retry responde ~250 ms
depois. Um aviso disparado por *falha de tentativa* cairia aí: "tô verificando…" seguido
do preço um quarto de segundo depois. Isso é ruído, não cuidado. O gatilho por tempo
ignora a falha rápida que o lead não percebe e pega exatamente os dois casos em que
existe espera de verdade — a chamada lenta de 8 s (10 % do tráfego, e que **dá certo**) e
o timeout de 12 s.

*Custo assumido:* no caso lento de 8 s, o aviso chega faltando 2 s para o preço.
Preferimos isso a avisar em situações que se resolveriam sozinhas.

As três mensagens desse caminho são **texto de template, não geradas** — elas são o
produto do comportamento sob falha e não podem variar com a temperatura do modelo.

O que o agente nunca faz, em nenhuma circunstância: não diz um preço que não veio de um
`quote_id` com status `ok`; não conclui recusa a partir de um 5xx; não promete prazo que
não pode cumprir; e não pede os dados de novo porque a **nossa** chamada falhou.

### 4. A recusa é um desfecho do bot, não uma exceção delegada

30 % dos leads do dataset são incotáveis: idade ≥ 76 ou veículo com mais de 20 anos. O
caminho de recusa é fluxo principal, não borda.

As duas regras de recusa **não dependem do plano** — trocar Premium por Essencial não
destrava nada. Qualquer oferta de "um plano mais barato" seria promessa falsa, e a
`/quote` a desmentiria na chamada seguinte. Então:

| Motivo da recusa | O agente oferece | Por quê |
|---|---|---|
| veículo com mais de 20 anos | cotar **outro veículo** da casa | a apólice é de um veículo específico; se há outro, é outra cotação, e é legítima |
| idade ≥ 76 (ou < 18) | **nada** — explica e registra | ver abaixo |

**Na recusa por idade, o agente nunca sugere trocar o condutor principal.** Se quem
dirige de fato tem 78 anos, declarar outra pessoa é declaração falsa — e a conta chega
como negativa de sinistro, no pior momento possível para o cliente. Se o lead disser
espontaneamente que quem dirige é outra pessoa, aí sim recotamos: registrar um fato que
o lead trouxe não é a mesma coisa que ensinar o caminho.

E a recusa **não cria handoff**. Um humano releria a mesma regra fixa e daria o mesmo
"não"; encaminhar 30 % do tráfego para isso encheria a fila com casos sem saída. O lead
recusado fica registrado e visível no admin, com perfil e motivo, **sem promessa de
contato futuro** — não há quem faça esse contato, e prometer seria a promessa vazia que
o resto do projeto recusa.

### 5. O canal: dois adaptadores, nenhum deles WhatsApp real

O agente é agnóstico de canal pela porta `ChannelAdapter`. Os dois adaptadores entregues
rodam **sem credencial nenhuma**:

- **`console`** — determinístico, gera o log de execução completa e roda no CI;
- **`web`** — uma interface que simula o WhatsApp, onde se conversa com o agente pelo
  navegador.

Não entreguei WhatsApp Cloud API nem Baileys, por três motivos: nenhum critério de
avaliação depende do canal; ambos exigiriam credenciais e webhook público que quem clona
o repositório não tem; e o tempo foi investido no que é avaliado — resiliência da
`/quote`, critério de encaminhamento e rastreabilidade.

A porta está documentada em `docs/ARQUITETURA.md` §7. Um adaptador da Cloud API
implementaria `send`/`receive` sobre webhook, com validação de assinatura, deduplicação
por id de mensagem e a janela de 24 horas. Um adaptador Baileys, sobre socket persistente
— este com a ressalva de ser não-oficial e fora dos termos de uso do WhatsApp.

#### O admin recebe em tempo real, e a pílula diz quando não recebe

A fila de handoff e a badge de pendentes entram sem recarregar a página: o backend
empurra `handoff.created` e `handoff.updated` por um WebSocket em `/api/events`, e a
tela **invalida e recarrega do endpoint** em vez de montar o item a partir do frame —
um item montado no cliente diverge do banco na primeira mudança de schema, e o admin
existe para dizer a verdade sobre o banco.

Isso importa para mais de um operador: sem o push, dois assumem o mesmo caso porque a
fila de cada um está parada no que era verdade quando a página abriu.

Quando o push cai, a pílula no cabeçalho passa de *"recebendo em tempo real"* para
*"sem conexão em tempo real"*. **Um admin que perdeu o push e não avisa é pior que um
admin sem push**, porque o operador passa a confiar numa fila parada.

#### O anexo do chat é sinalização, não upload

A tela de chat aceita anexo, e é preciso ser explícito sobre o que isso significa:
**os bytes não sobem**. O que trafega e o que fica gravado é o **nome do arquivo** e o
tipo (`image`, `audio`, `document`) na coluna `messages.tipo`. Nenhum conteúdo de mídia
é lido, transmitido ou armazenado em lugar nenhum.

Ele existe por um motivo só: `midia_sem_texto` é um dos oito gatilhos de handoff, e sem
uma forma de a mídia chegar o gatilho seria uma linha de tabela sem caminho de código —
o tipo de promessa que este repositório não faz. A alternativa era cair para sete
gatilhos e contradizer `docs/DECISOES-FECHADAS.md`.

A escolha cria a superfície do **gatilho** sem criar a superfície de **dado sensível**
que o projeto declara não ter: uma foto de CNH ou um áudio com o CPF falado seriam
exatamente o tipo de conteúdo que não deve existir num repositório público, nem no disco
de quem o clona. O agente é instruído a nunca afirmar que viu ou ouviu o arquivo, porque
ele não viu — recebe o nome, e mais nada.

### 6. Observabilidade e custo: na própria base, sem serviço externo

A instrumentação para uma plataforma externa de observabilidade estava prevista e foi
**descartada**; o painel de custo foi construído sobre a própria base de dados.

O Langfuse v3 (e v4) exige seis containers — web, worker, Postgres, ClickHouse, Redis e
armazenamento de objetos — cerca de **5,6 GB de imagens e 3,2 GB de RAM**, medidos numa
instância própria em produção. Não existe variante enxuta: a documentação do projeto
registra que a alternativa só-Postgres foi avaliada e recusada, por complexidade e custo
de manutenção.

Colocar isso no caminho padrão contradiria o requisito de subir com um comando. Deixar
como profile opcional resolveria o peso, mas não o essencial: **uma métrica que exige
5,6 GB de download para ser conferida é, na prática, uma alegação e não uma evidência.**

As métricas que importam já são obtidas nativamente. O consumo por turno — tokens de
entrada e saída, leitura e escrita de cache, latência — é gravado na tabela `turn_usage`
a partir das métricas que o próprio framework de agentes expõe, na granularidade de
**turno** e não de chamada (um turno com tool call faz várias chamadas ao modelo, e o
que interessa é o custo do turno). As avaliações de confiabilidade de chamada de
ferramenta e de qualidade por modelo-juiz persistem no mesmo Postgres da aplicação.

O **preço por modelo vem de um arquivo de configuração** com data de vigência e fonte,
nunca embutido no código, e cada linha de `turn_usage` grava qual entrada de preço foi
usada — para que um custo histórico continue auditável depois que a tabela mudar. Calcular
do nosso lado não é preferência: o provider Anthropic não popula o campo de custo do
framework.

O resultado é que **custo por conversa, taxa de acerto do cache de prompt, confiabilidade
das chamadas de ferramenta e as notas do juiz aparecem no painel de administração** para
qualquer pessoa que rode a aplicação, sem serviço externo. O painel é uma seção com
título e âncora próprios dentro de `/status` — não uma quinta tela, porque são seis
números e uma rota nova para seis números é escopo por escopo.

Isso deixou de ser aspiracional: os módulos nativos do Agno (`ReliabilityEval`,
`AgentAsJudgeEval`) rodam de verdade dentro do replay (`qa/replay/evals.py`, flag
`--evals`, gravando em `ai.eval_runs`) — não são só código testável que nenhum caminho
chama. Medido: os 30 casos de `ReliabilityEval` passaram, e o `AgentAsJudgeEval` avaliou
os três textos de recusa (`docs/TEXTOS.md` ⑤⑥⑦) com **nota 9**. Detalhe de metodologia e
o histórico do defeito (a tabela nunca existia e o painel mostrava um traço em silêncio)
em `docs/EVALS.md`.

A rastreabilidade também ganhou granularidade de **chamada**, não só de turno: a aba
"Trace" do Histórico (`GET /api/conversations/{id}/traces`, lendo `ai.agno_runs`) mostra,
por resposta do agente, quais tools rodaram, com quais argumentos, o resultado e a
duração — além dos tokens daquele turno. É a única leitura que mascara PII **na leitura**
em vez de na escrita, porque `ai.agno_runs` é tabela do próprio Agno, fora das migrações
nossas.

Um detalhe de honestidade do painel: o Ollama não reporta leitura e escrita de cache, e
por isso as colunas são anuláveis e a tela mostra **"n/a"**, nunca "0 %". Um zero ali
diria "o cache não acertou" onde a verdade é "não existe cache neste caminho".

A instrumentação OpenTelemetry continua viável em poucas linhas e inerte sem chave, caso
alguém queira exportar os traces. Nada no caminho crítico depende dela.

### 7. Prompt caching: medido, não declarado

O prompt do sistema é mantido **integralmente estático**, e o conteúdo volátil (data e
hora, estado do lead) entra num bloco marcado como **não-cacheável**, em vez de
concatenado ao prompt.

A diferença importa porque a falha aqui é silenciosa: concatenar o conteúdo volátil
invalidaria o prefixo a cada turno, o cache nunca acertaria, e **não haveria erro nenhum**
— só uma conta mais cara.

#### O número

A prova está na tabela `turn_usage`, e não em prosa. Uma conversa completa de 6 turnos —
a mesma de `artifacts/transcript-feliz.md` — medida com `anthropic:claude-opus-5`:

| turno | tokens enviados | lidos do cache | escritos no cache |
|---|---|---|---|
| 1 | 155 | **0** | 2.591 |
| 2 | 534 | 5.182 | 0 |
| 3 | 877 | 5.182 | 0 |
| 4 | 667 | 2.591 | 0 |
| 5 | 2.178 | 5.182 | 0 |
| 6 | 4.076 | 7.773 | 0 |
| **total** | **8.487** | **25.910** | 2.591 |

**75,3 % do contexto veio do cache** — 25.910 tokens lidos contra 8.487 enviados
inteiros. O turno 1 escreve o prefixo e lê zero; **do 2º em diante a leitura nunca é
zero**, que é exatamente o invariante que a decisão de caching promete e a única forma
de saber que ele está funcionando: se o bloco volátil fosse concatenado ao prompt, esta
coluna seria zero em todas as linhas e nada acusaria.

Custo da conversa inteira: **US$ 0,1002**, calculado de `config/model_pricing.yaml` com
a vigência gravada em cada linha — a Anthropic não popula o campo `cost` do Agno, então
o cálculo é nosso.

#### O cache é por PREFIXO, não por conversa — e é por isso que a economia cresce

Numa amostra maior, **79 turnos** de várias conversas, todos com `anthropic:claude-opus-5`:

| | |
|---|---|
| lidos do cache | **346.723** |
| enviados inteiros | 101.132 |
| **do contexto veio do cache** | **77,4 %** |
| custo acumulado | US$ 1,16 |
| turnos que leram **zero** | **4 de 79** |

Os quatro que leram zero são os que aqueceram o prefixo. Os outros 75 acertaram —
**inclusive primeiros turnos de conversas novas**, o que só é possível porque o que está
em cache é o *prefixo do prompt*, e não o histórico de uma conversa.

A consequência é operacional e vale dizer explicitamente: o prefixo é o catálogo de
planos mais as instruções, é idêntico para todo lead, e sobrevive **entre** conversas
dentro da janela do provider. **Quanto mais tráfego, maior a fração que vem do cache** —
o custo por conversa cai com o volume em vez de escalar linearmente.

É exatamente por isso que o bloco volátil (data, estado do lead) vai num
`SystemPromptBlock` com `cache=False` em vez de concatenado ao prompt: concatenar
invalidaria o prefixo a cada turno **e a cada conversa**, a tabela acima seria toda de
zeros, e nenhum erro apareceria — só uma conta maior.

Para conferir na sua máquina, sem abrir o painel:

```sql
select count(*) as turnos, sum(tokens_in), sum(cache_read),
       round(100.0*sum(cache_read)/(sum(cache_read)+sum(tokens_in)),1) as pct_do_cache
from turn_usage where conversation_id = '<a conversa>';
```

O mesmo número aparece no painel de custo em `/admin/status`, por provider e por
conversa. Há também um teste negativo, que existe para que a fragilidade seja visível
em vez de silenciosa.

### 8. O dataset: tom, objeções e testes de extração — nunca exemplo de cotação

As mensagens de cotação do histórico têm plano e preço sorteados independentemente do
perfil do lead. Medido contra as regras reais da API:

- **100 % das cotações do dataset são matematicamente impossíveis.** O espaço fechado de
  prêmios alcançáveis tem 72 valores (3 planos × 4 faixas etárias × 3 faixas de idade do
  veículo × 2 regiões); nenhum dos preços do dataset pertence a ele.
- A **frase de cobertura é idêntica em todas as conversas** — sempre a do plano mais
  básico, mesmo quando anunciam o mais completo.
- **Nenhuma menciona a carência.** Nenhuma menciona a data de início ou o pro-rata.

Usar esse histórico como few-shot no turno de cotação ensinaria o modelo a escrever um
preço plausível em vez do preço calculado, a repetir a cobertura errada e a nunca citar a
carência — os três erros mais graves possíveis neste domínio.

O histórico foi usado para calibrar tom e ritmo, mapear a taxonomia de objeções, definir a
ordem das perguntas de qualificação, gerar casos de teste de extração e servir de corpus
de replay na avaliação. **A fonte de verdade de preço é a `/quote`**, e o gabarito de
qualquer verificação é o conjunto fechado de 72 valores — conferência de preço é
*cálculo*, nunca julgamento de modelo.

Duas observações sobre o dataset que moldaram o que foi medido:

- **A extração é avaliada em três campos: idade, ano do veículo e CEP.** Marca e modelo
  ficam de fora porque a coluna de gabarito contém informação que o lead nunca disse — ela
  diz "Renault Sandero 2022" onde a fala diz "e um Sandero 2022". Penalizar o agente por
  não extrair uma marca que ninguém pronunciou é medir o ruído do gabarito. O CEP entra
  porque aparece em 100 % das conversas, está na fala do lead, e errá-lo **subcota em
  30 %** nos prefixos de risco.
- **Toda a persistência passa por mascaramento de PII.** O histórico tem CPF e CEP em
  100 % das conversas, telefone e e-mail em 55 %, placa em 34 %. O módulo de mascaramento
  não é da camada de dados: ele existe desde a primeira mensagem persistida, porque toda
  mensagem passa por ele. E o corpo de erro de validação da API **ecoa o payload
  enviado** — idade e CEP do lead — então esse corpo nunca vai para log estruturado sem
  passar pelo mascaramento.

---

## Quando o agente passa para um humano

**O critério é o custo do erro.** Não "quantos casos cobrir", mas *quanto custa o agente
errar naquele ponto*. Custo alto encaminha na hora e sem tentar; custo baixo tenta uma
vez e encaminha na segunda.

| # | Gatilho | Dispara quando | Custo do erro | O que o bot faz |
|---|---|---|---|---|
| 1 | `assunto_sensivel` | sinistro, jurídico, saúde, reclamação formal | alto | encaminha **imediato**, sem tentar responder |
| 2 | `guardrail` | injeção de prompt, abuso | alto | encerra e registra |
| 3 | `lead_pediu` | o lead pede uma pessoa | — | encaminha |
| 4 | `cotacao_indisponivel` | o job de cotação terminou `failed` | alto | encaminha |
| 5 | `lead_aceitou_cotacao` | verbo de aceite **mais** cotação `ok` já entregue | — | encaminha para um consultor |
| 6 | `extracao_falhou` | 2ª falha de extração no mesmo campo | médio | encaminha |
| 7 | `objecao_fora_da_alcada` | o lead **repete** a objeção de preço | baixo | encaminha na 2ª |
| 8 | `midia_sem_texto` | o lead **insiste** em mídia depois de pedirmos texto | baixo | encaminha na 2ª |

Fila estimada: **~8 % dos leads**.

**O 5 é o único handoff que é boa notícia** (migração `db/migrations/0006`). Antes, o
lead que aceitava a cotação caía em `lead_pediu_atendente` — falso em duas direções: ele
não pediu atendente, e a resposta ("já passei sua conversa pra um atendente") respondia a
uma pergunta que não fez. A causa era o próprio template, que fechava com *"Quer que eu
siga com a emissão?"* — e emissão não existe nesta API legada (só `/health`, `/planos`,
`/quote`). O template passou a convidar para a **contratação**, e o gatilho passa o lead
para um consultor, dizendo por quê.

**Não são gatilhos:** a recusa por regra de negócio, a falha isolada da `/quote` que o
retry resolveu, a primeira objeção de preço, a primeira mídia sem texto.

**Precedência:** lista fixa, na ordem da tabela, **primeiro que casa vence**. O handoff
grava também os gatilhos secundários que casaram no mesmo turno — a fila mostra **um**
gatilho, o que mantém a regra testável com um teste por linha, sem que o operador perca o
quadro completo ao assumir.

**Depois de encaminhar, o agente encerra a participação — a conversa não trava.** Ele
avisa que vai passar para um humano e para de responder: `encaminhado` continua terminal
**para o agente**. Mas a conversa em si não fica num beco: a tela `/atendimento` deixa o
operador assumir o handoff e responder na conversa (`POST
/api/conversations/{id}/mensagens`, autor `operador`), e o lead recebe a resposta pelo
mesmo WebSocket, em tempo real. Antes de essa tela existir, travar a conversa inteira era
inofensivo porque não havia quem respondesse do outro lado; com atendimento humano,
travar teria transformado o handoff num beco.

*Consequência assumida, e ela é real:* na segunda objeção de preço o bot encerra no meio
de uma negociação. É defensável — a segunda objeção é sinal de que ele não vai fechar
sozinho — mas exige que a despedida seja boa o bastante para o lead não achar que foi
ignorado. Ela é de template, e é um dos textos que mais mereceram cuidado.

A mensagem de handoff é sempre **um prefixo opcional mais a despedida**, numa tabela de
quatro linhas. Isso mantém o descarte do texto do modelo **sem exceção** em todo caminho
de encaminhamento: o lead recebe uma composição de textos fixos, nunca uma frase gerada.
Assunto sensível tem dois prefixos e não um, porque "sinto muito" numa notificação
extrajudicial soa como admissão, e a ausência dele depois de "meu carro capotou ontem"
soa como frieza.

---

## Resiliência: timeout, retry e circuit breaker

Todo número abaixo é **medido**, não estimado. As medições completas, com a bancada de
sete instâncias configuradas para isolar cada comportamento, estão em `docs/API-COTACAO.md`.

| Parâmetro | Valor | A medição que o justifica |
|---|---|---|
| `connect_timeout` | 2 s | o legado responde em ~2 ms quando responde |
| **`read_timeout`** | **12 s** | a chamada lenta **dorme 8,004 s e devolve 200 correto** — ver abaixo |
| `max_attempts` | **3** | 0,20³ = 0,8 % de falha residual; a 4ª compra 0,64 pp |
| `backoff_base` | 250 ms | não há `Retry-After` no legado para respeitar |
| `backoff_fator` / `teto` | 2,0 / 2 s | 250 ms → 500 ms → 1 s, com full jitter |
| `max_concorrencia` | **8** | acima de 40 chamadas lentas simultâneas o legado serializa |
| `breaker_limiar` | 5 falhas consecutivas | com p=0,20, cinco seguidas por acaso tem 0,032 % de chance |
| `breaker_cooldown` | 20 s | uma sonda por conversa nova, sem martelar o legado |

### Por que 12 s, e não 5 s

**A lentidão do legado não é uma falha.** Medido, três chamadas na instância lenta:
**8,004 s · 8,005 s · 8,004 s**, todas **200**, com o corpo correto e completo. E, na
mesma instância, com a mesma requisição:

| Timeout do cliente | Resultado |
|---|---|
| 5 s | timeout — **um 200 correto destruído pelo cliente** |
| 12 s | **200 em 8,00 s** |

Um timeout menor que 8 s não protege nada: ele converte 10 % de sucessos em falhas
artificiais e, pior, em falhas que o retry **reproduz**, porque o próximo sorteio pode
cair de novo na faixa lenta. A margem de 4 s existe porque a duração da lentidão é
configurável e porque a rede não é instantânea.

*Custo assumido:* quando a falha é de rede de verdade, esperamos 12 s para descobrir. É o
preço de não destruir os 10 % de chamadas lentas legítimas — a lentidão é 10 % do tráfego,
a queda de rede é rara.

### Por que 3 tentativas

Cada tentativa é um sorteio independente, verificado empiricamente: em 200 grupos de 3
tentativas com o mesmo payload contra uma instância com 90 % de falha, as três falharam em
**0,720** dos grupos, contra **0,729** teóricos. Com o default de 20 %:

| Tentativas | Falha residual | Ganho da última |
|---|---|---|
| 1 | 20 % | — |
| 2 | 4 % | 16 pp |
| **3** | **0,8 %** | 3,2 pp |
| 4 | 0,16 % | 0,64 pp |

A quarta tentativa compra 0,64 ponto percentual e pode custar mais 12 s. **O critério que
fecha a conta é o orçamento de tempo, não a taxa.**

### Por que limitar a concorrência em 8

O handler da `/quote` é síncrono, então roda no threadpool do framework, cujo limite é 40.
Com 60 chamadas lentas simultâneas: 40 terminaram em ~8,8 s e **20 enfileiraram para
~16,6 s** — acima do nosso read timeout de 12 s.

Sem limitar a concorrência, o dimensionamento do timeout deixa de valer exatamente quando
há mais leads, e o modo de falha é o pior possível: falha artificial em massa sob carga.
Um semáforo de 8 mantém margem larga. A espera no semáforo não conta contra o read timeout
(é fila nossa, não latência do legado), mas conta contra o orçamento do turno — por isso é
registrada separadamente em cada tentativa.

### O que retenta, e o que nunca retenta

A decisão **não sai do status HTTP sozinho**. O 422 carrega dois erros de naturezas
opostas, distinguíveis pela forma do corpo — e dentro da recusa há casos que são bug nosso
disfarçado de recusa. São cinco desfechos porque são cinco ações distintas:

| Desfecho | Reconhecido por | Retenta? | O que acontece |
|---|---|---|---|
| `ok` | 200 | — | renderiza por template e responde |
| `transient` | 500 · 502 · 503 | **sim** | backoff exponencial com jitter |
| `timeout` | sem resposta em 12 s, erro de conexão | **sim** | idem |
| `refused` | 422 com corpo de recusa **e** motivo de recusa real | **não** | o lead ouve o motivo, de um mapa fixo nosso |
| `bad_request` | 400 · 422 de validação · 422 "recusa" que é dado nosso errado · 404 · 405 | **não** | bug nosso; o lead nunca vê o erro |

Os únicos três motivos que contam como recusa real são idade acima do limite de aceitação,
idade abaixo do mínimo, e veículo com mais de 20 anos. A API rotula como recusa outros dois
casos que **não** são: veículo com ano no futuro (o lead não é inelegível — o dado está
errado, e é para reperguntar) e plano inexistente (nenhum lead digita um id de plano; fomos
nós que escolhemos). E um motivo desconhecido cai em `bad_request` de propósito: **na
dúvida, não afirmamos ao lead que ele foi recusado.**

### O circuit breaker

Três estados, com transição por sonda: **fechado** → 5 falhas consecutivas → **aberto** →
cooldown de 20 s → **meia-abertura** → uma sonda ok → fechado; sonda falha → aberto, com o
cooldown reiniciado.

A sonda **não é uma requisição sintética**: é a próxima cotação de verdade, que assim não é
desperdiçada.

**Só `transient` e `timeout` contam para o breaker.** Uma recusa de negócio é a API
funcionando perfeitamente — contá-la abriria o circuito num dia de muitos leads idosos. Um
`bad_request` é defeito nosso — contá-lo esconderia o bug atrás de um "legado fora".

Com o breaker aberto, o job nasce `failed` **sem nenhuma tentativa**, e com a marca de
circuito aberto. A tela de status distingue isso de "tentamos 3 vezes e falhou": são
situações diferentes para quem opera.

O breaker é **global por processo**, não por conversa: a instabilidade é do legado, e
descobri-la numa conversa deve poupar as outras.

### O que é retentável é seguro de retentar

`POST /quote` é função pura: sem estado, sem escrita, sem cobrança. Retentar é seguro por
construção, e não é preciso chave de idempotência do lado deles. Do nosso lado, **cada
tentativa vira uma linha** com número da tentativa, status HTTP, latência e desfecho — e a
tentativa é gravada **mesmo quando o job inteiro falha**, que é justamente o caso em que a
linha do tempo importa.

Uma observação para quem for olhar a tela de status: o p95 vai mostrar ~8 s sempre que
houver chamada lenta na janela. **Isso é o comportamento correto sendo exibido, não um
defeito** — e a tela diz isso explicitamente. Pelo mesmo motivo, `/admin/status` não é
redundante com o `/health` do legado: o `/health` responde 200 mesmo com 100 % das cotações
falhando, porque ele não passa pelo sorteio de instabilidade. Um monitor que só olhe para
ele reporta "tudo bem" enquanto nada funciona.

### O transcript que mostra isso acontecendo

`artifacts/transcript-degradado.md` é a política acima rodando, com tempo relativo em
cada linha:

```
[ +20.7s]           lead     pode começar dia 17 de outubro
[ +26.7s]  Δ +6.0s  sistema  Tô buscando o valor no sistema e ele tá lento agora. Já te trago, tá?
[ +40.7s]  Δ+20.0s  sistema  Ainda tô aqui, viu? O sistema não me devolveu ainda. Assim que sair eu te mando.
[ +61.1s]  Δ+40.4s  sistema  Não consegui confirmar o valor agora: o sistema de cotação não respondeu.
                             Não vou te passar um número sem ter certeza dele.
```

Três tentativas de 12 s, job `failed`, handoff `cotacao_indisponivel` disparado **pela
regra** — e nenhum valor monetário em lugar nenhum, porque nenhuma tentativa devolveu
preço. O cabeçalho do arquivo traz o comando exato que o reproduz.

`tests/nucleo/test_transcripts.py` confere os dois artefatos contra o código a cada
execução da suíte: os textos byte a byte com `app/textos.py`, os Δ contra os limiares
de `Settings`, e o número de tentativas contra `quote_max_attempts`. Um artefato que
envelhecesse em silêncio seria pior do que nenhum.

### Reprodutibilidade

Um cenário reproduzível da `/quote` é a tripla **(seed, processo reiniciado, sequência
exata de requisições)** — não a seed sozinha. O gerador de aleatoriedade do legado é um
fluxo global e contínuo do processo: uma falha consome dois valores, um sucesso consome um,
e uma requisição rejeitada na validação não consome nenhum. Em paralelo, o conjunto de
desfechos se preserva mas a atribuição a cada requisição embaralha.

Por isso as suítes que dependem de seed rodam **em série, com restart do container antes**,
e o transcript entregue fixa o cenário inteiro.

---

## Escopo: o que ficou de fora, e por decisão

Estes itens não são pendências. São decisões, com o motivo declarado.

| Fora do escopo | Por quê |
|---|---|
| **WhatsApp Cloud API** | exigiria credenciais e webhook público que quem clona o repositório não tem; nenhum critério de avaliação depende do canal. A porta `ChannelAdapter` existe e o desenho do adaptador está descrito. |
| **Baileys** | além do mesmo motivo acima, é uma biblioteca não-oficial e fora dos termos de uso do WhatsApp. Não é uma dependência que eu recomendaria numa entrega. |
| **Langfuse** | seis containers, ~5,6 GB de imagens e ~3,2 GB de RAM, sem variante enxuta. Contradiz "sobe com um comando", e uma métrica que exige 5,6 GB para ser conferida é alegação, não evidência. O que ele daria está em `turn_usage` e no painel de custo. |
| **Camada gold do dataset** | a camada silver é o que responde pelo replay de avaliação, e ele não depende de gold — lê de silver com a elegibilidade calculada em memória. Gold seria estrutura sem consumidor. |
| **Upload de mídia de verdade** | o chat aceita anexo, mas registra apenas nome e tipo — os bytes não sobem. Guardar mídia criaria a superfície de dado sensível que o projeto declara não ter (foto de CNH, áudio com CPF falado), num repositório público. O que o produto precisa saber é que chegou mídia em vez de texto, e é isso que ele guarda. |
| **Vídeo da demo** | não é entregável nem critério de avaliação. A tela de chat e o transcript já mostram o comportamento. |

Sobre providers de modelo: a seleção é por model-string, então trocar de provider é trocar
uma variável de ambiente. **Só Anthropic e Ollama são validados por smoke test.** Os demais
providers funcionam pela mesma model-string, mas **não foram testados** — e este README não
diz "suporta X" sem um teste que prove.

---

## Limitações assumidas e o que não foi testado

Esta seção existe porque a alternativa é o leitor descobrir sozinho — e descobrir
sozinho custa a confiança em tudo o mais que o README afirma.

### O que não foi testado

| Item | Situação |
|---|---|
| **Providers além de Anthropic e Ollama** | funcionam pela mesma model-string do Agno, e **não foram testados**. Não digo "suporta X" sem um smoke test que prove. |
| **Ollama** | validado por smoke test de uma conversa completa; **não** foi submetido ao replay do dataset nem à suíte `live` inteira. |
| **O default é `claude-sonnet-5`; a maioria dos números de cache e custo publicados aqui é de `claude-opus-5`** | o agente conversacional passou a rodar em Sonnet 5, que é o porte certo para esta tarefa e custa 2,5× menos. As medições de cache, custo e avaliação das seções acima foram feitas **antes** dessa troca, com Opus 5, e **não foram refeitas** — elas continuam válidas como o que são: uma medição daquele modelo, com o modelo nomeado em cada tabela. Reescrevê-las com outro nome seria falsificar evidência. O replay de desfecho **foi** refeito com o default atual — ver a comparação logo abaixo — porque essa execução é recente o bastante para caber na sessão que atualizou esta documentação. |
| **Concorrência real de leads** | o semáforo de 8 e o teto de 40 chamadas lentas da `/quote` estão medidos, mas nunca houve mais de uma conversa simultânea de verdade. |
| **Réplicas** | o rate limit é em memória, no processo. Com mais de uma réplica cada uma tem o seu contador, e o limite efetivo multiplica. |
| **Navegadores** | Chromium, via Playwright. Firefox e Safari não foram abertos. |
| **`OBJECAO_FORA_DA_ALCADA` contra o dataset** | o gatilho exige a **segunda** objeção na mesma conversa. Medido: 628 das 2.500 conversas têm exatamente uma objeção e **nenhuma tem duas** — o dataset não consegue exercitá-lo. Coberto por teste unitário; não por replay. |

#### Sonnet 5 contra Opus 5, mesma amostra de 30 conversas

Replay de desfecho, seed padrão do replay (`amostragem.SEED_PADRAO`), `--conversas 30`,
com o modelo no relatório JSON:

| | `claude-sonnet-5` (default atual) | `claude-opus-5` |
|---|---|---|
| desfecho correto | 30/30 (100 %) | 28/30 (93,3 %) |
| preço exato (14 conversas com prêmio calculável) | 14/14 | não medido nesta bateria |
| extração — idade / veículo / CEP | 30/30 · 30/30 · 30/30 | não medido nesta bateria |
| mídia tratada | 16/18 | 14/18 |
| tool proibida chamada | 0 | 0 |
| turnos / tempo total | 213 / 698 s | 186 / 856 s |

Ambos os relatórios estão em `qa/_saida/replay/` (`replay-sonnet.json` e
`replay-desfecho.json`) — não versionados (ver `docs/EVALS.md`), reproduzíveis com o
comando de `docs/EVALS.md` § Reprodutibilidade. Uma amostra de 30 não prova nada sobre a
cauda; prova que a troca de modelo não regrediu o comportamento medido.

### Riscos aceitos, com o motivo

**`ADMIN_TOKEN` no armazenamento do navegador.** Quando a instalação define
`ADMIN_TOKEN` e alguém o cola na tela de 401, ele fica em `sessionStorage` — legível por
qualquer XSS na página. É a credencial *mais forte* do sistema (o backend a aceita mesmo
com login configurado) guardada no lugar *menos* protegido.

Mitigado, não resolvido: era `localStorage` e passou a `sessionStorage`, então morre com
a aba em vez de ficar em disco. A saída de verdade seria trocá-lo por um cookie
`httpOnly`, como a sessão de login já faz — não foi feito porque a sessão é assinada com
chave derivada da credencial, e no modo só-token não existe credencial de onde derivá-la.
**Recomendação: use `ADMIN_USER`/`ADMIN_PASSWORD` em qualquer instalação que abra o
navegador**, e reserve `ADMIN_TOKEN` para CI e `curl`.

**O id da conversa é uma capacidade.** O WebSocket do chat não autentica: quem tem o id
lê a conversa inteira. O id tem 64 bits de aleatoriedade, então adivinhar é inviável — o
risco é vazamento (navegador compartilhado, captura de tela). É consequência direta de o
chat ser anônimo, que é o desenho do produto: um lead não faz login para pedir cotação.

**PII sintética no histórico do Git.** Commits antigos contêm CEPs de exemplo
(um deles é o da Avenida Paulista, endereço público) e um CPF placeholder inválido. Nenhum dado de
pessoa real, em nenhum commit — o histórico inteiro foi varrido por chave, token e PII.
O HEAD está limpo pela regra estrita (nenhum literal, nem sintético); reescrever 34
commits para remover endereços públicos seria desproporcional, e invalidaria todas as
referências de commit deste README.

**Sem antivírus de conteúdo no anexo.** O chat aceita anexo mas **não transporta bytes**
— só nome e tipo. Não há upload, logo não há arquivo para varrer; a contrapartida é que
também não há visualização de mídia.

### Correções recentes que vale nomear

Três, porque ficariam invisíveis atrás de "fix" no log do git e mudam o que este README
promete:

- **A sessão de login sobrevive a um restart do serviço** (`app/auth.py`). Antes, a chave
  que assina o cookie vinha de um salt sorteado a cada boot, e todo `docker compose up`
  derrubava sessões abertas como efeito colateral não intencional. Agora a chave deriva
  de `usuario|senha` — **trocar a credencial** invalida sessões, reiniciar o processo
  não.
- **Uma corrida na criação de conversa deixou de devolver 500** (`app/persistence/repo.py`).
  Duas requisições de criação quase simultâneas para o mesmo `(channel, external_ref)`
  colidiam na `UNIQUE`; a segunda agora lê a linha que a primeira gravou, em vez de
  propagar o erro do banco para o lead.
- **`/simulador` saiu de trás do login.** O backend já servia essa rota sem exigir
  autenticação (é o chat anônimo, por desenho — ver a seção 5); a proteção estava só na
  navegação do front, que escondia um link para uma URL que sempre respondeu.

---

## Onde está o resto

| Documento | O que tem |
|---|---|
| `docs/ARQUITETURA.md` | mapa de módulos, contratos internos, invariantes de implementação, e os cinco diagramas Mermaid revisados contra o código |
| `docs/API-COTACAO.md` | o mapeamento medido da `/quote`: bancada, taxonomia de erro, regras de preço, o dataset conferido contra elas |
| `docs/POLITICA-RESILIENCIA.md` | a política técnica completa, com a medição que justifica cada parâmetro |
| `docs/DECISOES-FECHADAS.md` | o contrato de comportamento |
| `docs/DECISOES-ABERTAS.md` | o registro do que foi considerado e descartado |
| `docs/SEGURANCA.md` | o passe de segurança: achados, correções, riscos aceitos e **os falsos positivos** |
| `docs/TEXTOS.md` | os textos determinísticos, origem única |
| `docs/EVALS.md` | metodologia de avaliação, cobertura por grupo, e qual modelo produziu qual número |
| `artifacts/transcript-feliz.md` | **entregável nº 4** — uma execução completa, do «oi» à cotação: qualificação dos cinco campos, bloco de preço com carência, franquia e pro-rata, estado final `cotado` |
| `artifacts/transcript-degradado.md` | **entregável nº 4** — a mesma conversa com a `/quote` fora do ar: aviso aos 6 s, reforço aos 20 s, encaminhamento depois de esgotadas as três tentativas, e nenhum número inventado |
| `ai-logs/` | as conversas com IA durante o desafio |
