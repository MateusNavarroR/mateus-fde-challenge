# AutoSeguro — agente de cotação de seguro de veículo

Um agente que conversa com o lead, qualifica, cota um plano contra uma API de cotação
instável e decide sozinho quando o caso deixa de ser dele. O centro do projeto não é a
conversa: é **o que o agente faz quando a `/quote` não responde** e **como ele nunca diz
um número que não veio da API**.

Este README é sobre as decisões e o porquê de cada uma. O mapa de módulos, os contratos
internos e as invariantes de implementação estão em `docs/ARQUITETURA.md`.  ⚠️ *ainda não escrito — ver `<!-- PREENCHER NO FIM -->`*

---

## Como rodar

<!-- PREENCHER NO FIM -->

---

## O que está implementado

<!-- PREENCHER NO FIM -->

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

A porta está documentada em `docs/ARQUITETURA.md`. Um adaptador da Cloud API  ⚠️ *ainda não escrito — ver `<!-- PREENCHER NO FIM -->`*
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

Ele existe por um motivo só: `midia_sem_texto` é um dos sete gatilhos de handoff, e sem
uma forma de a mídia chegar o gatilho seria uma linha de tabela sem caminho de código —
o tipo de promessa que este repositório não faz. A alternativa era cair para seis
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
título e âncora próprios dentro de `/admin/status` — não uma quinta tela, porque são seis
números e uma rota nova para seis números é escopo por escopo.

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
| 5 | `extracao_falhou` | 2ª falha de extração no mesmo campo | médio | encaminha |
| 6 | `objecao_fora_da_alcada` | o lead **repete** a objeção de preço | baixo | encaminha na 2ª |
| 7 | `midia_sem_texto` | o lead **insiste** em mídia depois de pedirmos texto | baixo | encaminha na 2ª |

Fila estimada: **~8 % dos leads**.

**Não são gatilhos:** a recusa por regra de negócio, a falha isolada da `/quote` que o
retry resolveu, a primeira objeção de preço, a primeira mídia sem texto.

**Precedência:** lista fixa, na ordem da tabela, **primeiro que casa vence**. O handoff
grava também os gatilhos secundários que casaram no mesmo turno — a fila mostra **um**
gatilho, o que mantém a regra testável com um teste por linha, sem que o operador perca o
quadro completo ao assumir.

**Depois de encaminhar, o agente encerra a participação.** Avisa que um atendente vai
assumir e para de responder. O estado `encaminhado` é terminal de verdade, o que remove
qualquer ambiguidade sobre quem está falando.

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

<!-- PREENCHER NO FIM -->

---

## Onde está o resto

| Documento | O que tem |
|---|---|
| `docs/ARQUITETURA.md` | mapa de módulos, contratos internos, invariantes de implementação |  ⚠️ *ainda não escrito — ver `<!-- PREENCHER NO FIM -->`*
| `docs/API-COTACAO.md` | o mapeamento medido da `/quote`: bancada, taxonomia de erro, regras de preço, o dataset conferido contra elas |
| `docs/POLITICA-RESILIENCIA.md` | a política técnica completa, com a medição que justifica cada parâmetro |
| `docs/DECISOES-FECHADAS.md` | o contrato de comportamento |
| `docs/DECISOES-ABERTAS.md` | o registro do que foi considerado e descartado |
| `docs/TEXTOS.md` | os textos determinísticos, origem única |
| `docs/EVALS.md` | metodologia de avaliação, rubrica, e qual modelo produziu qual número |  ⚠️ *ainda não escrito — ver `<!-- PREENCHER NO FIM -->`*
| `artifacts/transcript-feliz.md` | **entregável nº 4** — uma execução completa, do «oi» à cotação: qualificação dos cinco campos, bloco de preço com carência, franquia e pro-rata, estado final `cotado` |
| `artifacts/transcript-degradado.md` | **entregável nº 4** — a mesma conversa com a `/quote` fora do ar: aviso aos 6 s, reforço aos 20 s, encaminhamento depois de esgotadas as três tentativas, e nenhum número inventado |
| `ai-logs/` | as conversas com IA durante o desafio |
