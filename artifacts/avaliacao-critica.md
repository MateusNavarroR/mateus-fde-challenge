# Avaliação crítica — AutoSeguro (desafio FDE)

Avaliação feita como quem chega do zero: worktree isolado, `.env` copiado do
repositório principal, pilha própria via `docker compose -p avaliacao-critica`,
suíte de testes rodada de verdade, dois cenários (feliz/degradado) reproduzidos
contra a pilha isolada. Nenhum container ou porta da aplicação já em execução na
máquina foi derrubado ou recriado — **com uma exceção grave, admitida abaixo**.

---

## ⚠️ Incidente durante a avaliação (preciso admitir isto primeiro)

Ao investigar por que a suíte `not live` falhava com `relation "ai.agno_runs" does
not exist`, rodei um arquivo de teste isolado **sem exportar `APP_DATABASE_URL`**
para checar o comportamento default. `tests/conftest.py` tem como fallback
`postgresql+psycopg://postgres:postgres@127.0.0.1:55432/autoseguro` — e a porta
55432 é exatamente uma das que o enunciado desta avaliação me disse para **não
tocar**, por já estar em uso por uma instância real (`autoseguro-db`, container
`autoseguro-db` publicado em `127.0.0.1:55432`).

A fixture `sessao` desse conftest faz `TRUNCATE conversations, messages, handoffs,
quote_attempts, quotes, turn_usage ... CASCADE` no início de cada teste que a usa.
Rodei `uv run pytest tests/nucleo/test_traces.py` (4 testes, todos usam `sessao`)
contra esse banco por engano, e ele truncou essas seis tabelas nele. Confirmei
depois: `autoseguro-db` está com `conversations` e `messages` zeradas.

**O que não sei dizer:** se havia dado de valor nessas tabelas antes do meu comando
(o container está de pé desde 2026-09-04, um dia antes da minha sessão) — não tenho
como recuperar o estado anterior. **O que sei dizer:** o erro foi meu, por rodar um
comando sem isolar explicitamente o banco antes de entender o default; devo ter
exportado `APP_DATABASE_URL` para a minha própria pilha em toda invocação, e nas
primeiras vezes fiz isso — essa foi a exceção que não deveria ter acontecido.

**Isto também é um achado sobre o código, não só sobre mim**: o default de
`tests/conftest.py` aponta, sem confirmação, para "o Postgres do sistema que a
pessoa já tem instalado" — e o primeiro efeito colateral de rodar a suíte contra
ele é um `TRUNCATE CASCADE` sem aviso. Um default assim é perigoso para qualquer
avaliador ou desenvolvedor que rode `pytest` cru numa máquina com outro Postgres na
55432. Recomendo ao autor trocar esse fallback por algo que falhe alto (ou exija
`--confirm`) em vez de truncar silenciosamente o que encontrar.

A partir desse ponto, toda invocação de teste nesta avaliação usou explicitamente
`APP_DATABASE_URL` apontando para o meu próprio `db-debug` isolado (porta 25432),
e a pilha principal do desafio (`mateus-fde-challenge-*`, porta 8080) nunca foi
tocada — confirmei saúde dela (`/api/health` → `200 ok`) antes e depois da minha
sessão.

---

## Veredito

**Contrataria com ressalvas.**

O núcleo do desafio — o que a `/quote` faz sob falha — está genuinamente
implementado, medido e reproduzível: eu mesmo reproduzi os dois cenários (feliz e
degradado) contra uma pilha isolada e o comportamento bateu com o que o README
descreve, número por número. Isso é raro e pesa a favor. Mas o README também faz
afirmações fortes de "tudo testado e funcionando" que não resistem à checagem
literal: a suíte de testes descrita passo a passo no próprio README **não passa**
numa máquina que segue exatamente essas instruções (39 falhas reais, não
decorativas), e pelo menos um número de segurança publicado (34 commits varridos)
está desatualizado em relação ao repositório real (50 commits). Nenhum dos dois é
fatal sozinho, mas juntos mostram um padrão: o texto foi escrito antes do código
parar de se mover, e a verificação final "roda exatamente como documentado" não
foi refeita.

---

## Subir do zero — passo a passo real

```bash
cp /home/mateus/.../mateus-fde-challenge/.env .env   # conforme instruído
docker compose -p avaliacao-critica up -d --build
```

**Fricção nº 1 — porta fixa, sem variável de ambiente.** Falhou de cara:
`Bind for 127.0.0.1:8080 failed: port is already allocated`. `docker-compose.yml`
publica `"127.0.0.1:8080:8080"` **hardcoded**, sem interpolar variável nenhuma —
diferente de `ANTHROPIC_API_KEY`, `ADMIN_TOKEN` etc., que são `${VAR:-default}`. O
enunciado desta avaliação já avisava que a porta 8080 estaria ocupada; um
avaliador real, com a máquina livre, não bateria nisso, mas quem quiser rodar
**duas instâncias** do produto na mesma máquina (dev + staging, por exemplo) tem
que editar o `docker-compose.yml` ou escrever um override — não há
`APP_PORT:-8080}` pronto. Contornei com um override (`ports: !override -
"127.0.0.1:18080:8080"`) via `-f`.

Com o override, a pilha sobe limpa e saudável:

```
Container avaliacao-critica-app-1 Healthy
$ curl -s http://127.0.0.1:18080/api/health
{"status":"ok","db":"ok"}
```

**Fricção nº 2 — o mesmo problema no perfil `debug`.** `docker-compose.yml` publica
`db-debug` em `127.0.0.1:5432:5432`, também hardcoded. A porta 5432 já estava
ocupada nesta máquina (Postgres de outra instância). Precisei do mesmo truque de
override para rodar os testes que dependem de banco. Isso é o **exato** cenário
que o README descreve resolver para a porta 8080 ("nada de conflito com um
Postgres já instalado") — só que a solução não foi replicada para `db-debug`.

**Fricção nº 3 — o default de `conftest.py` não bate com o `docker-compose.yml`.**
`tests/conftest.py` conecta por default em `127.0.0.1:55432`; o `db-debug` que o
README manda subir publica em `127.0.0.1:5432`. Ou seja: seguindo o README à
risca (`docker compose --profile debug up -d db-debug` seguido de
`uv run pytest -q -m "not live"`), em uma máquina **sem** nada na porta 55432, a
suíte inteira que depende de banco (`pytestmark = pytest.mark.db`) tentaria
conectar em `55432` — onde nada está escutando — e a fixture `engine_teste` daria
`pytest.skip("Postgres indisponível...")` **silenciosamente**, para TODOS os
testes de banco, sem que isso apareça como falha. É o inverso do incidente acima:
lá o default matou dado alheio; aqui, numa máquina limpa, o mesmo default faz a
suíte parecer "verde" enquanto pula a maior parte da cobertura real. Nenhum dos
dois comportamentos é o que o README promete ("comece por `docker compose
--profile debug up -d db-debug`... rode a suíte").

### Rodando a suíte

```bash
uv sync
uv run pytest -q -m "not live"     # com APP_DATABASE_URL apontando pro meu db-debug isolado
```

```
39 failed, 529 passed, 43 skipped, 131 deselected, 4 warnings in 27.28s
```

97% passa — mas as 39 falhas **não são ruído**, são três causas raiz reais e
reproduzíveis:

1. **34 testes em `tests/dados/*`** (`test_replay_casos.py`,
   `test_replay_resiliencia.py`, `test_replay_respondedor.py`, `test_silver.py`)
   falham com `FileNotFoundError` procurando
   `.../namastex-fde-challenge/quote-service/data/plans.json`. O código
   (`qa/dataset/caminhos.py`) assume que o repositório original do desafio existe
   como **diretório irmão** do clone — decisão razoável (evita caminho absoluto
   hardcoded, é sobrescrevível por `DATASET_PLANS_JSON`/`DATASET_BRONZE_PARQUET`) —
   mas essa exigência **não aparece em lugar nenhum do README nem dos docs**. Quem
   clona o repositório público, sem o repositório do desafio ao lado, roda o
   comando exato do README e recebe 34 tracebacks, não 34 skips. Verifiquei com
   `grep` em README e `docs/*.md`: zero menções a essa dependência.

2. **3 testes em `test_traces.py`** falham com
   `relation "ai.agno_runs" does not exist`. Essa tabela é criada pelo Agno em
   tempo de execução, na primeira sessão real do agente contra aquele banco — não
   por nenhuma migração em `db/migrations/`. Como `db-debug` é um Postgres **nunca
   tocado pela aplicação** (a app usa o serviço `db`, não `db-debug`), o schema
   `ai` fica com só `agno_schema_versions`, sem `agno_runs`/`agno_sessions`.
   Confirmei via `docker exec ... psql -c '\dt ai.*'`. Não há passo no README que
   diga "rode uma conversa contra o banco de debug antes dos testes de trace".

3. **1 teste real, `test_as_rotas_escondidas_do_schema_sao_exatamente_as_declaradas`**,
   falha por um motivo genuíno de código: `app/main.py` só registra
   `@app.get("/{caminho:path}")` (o catch-all do SPA) **se** `web/dist` existir.
   Se não existir — que é exatamente o estado de qualquer `git clone` fresco antes
   de `npm run build`, e exatamente o estado em que o README manda rodar
   `uv run pytest` (sem build de frontend) — o código cai no ramo `else` e registra
   um `@app.get("/")` **diferente**, que o teste de "contrato congelado" da
   superfície da API não conhece. Ou seja: **seguir o README ao pé da letra faz o
   próprio teste de anti-deriva da aplicação acusar deriva.** Confirmei isolando o
   teste e inspecionando `app/main.py:349-372`.

Nenhuma dessas 39 é um teste decorativo — todas testam algo real. O problema é que
o comando publicado como "rode os testes" não os passa, e as causas reais nunca
aparecem no README nem em `docs/`.

---

## C2 — o que acontece quando a `/quote` falha (reproduzido de verdade)

Este é o critério que mais pesa, e é o ponto mais forte da entrega.

Reproduzi os dois cenários do README contra a minha pilha isolada, com as mesmas
variáveis publicadas:

**Cenário degradado** (`QUOTE_SLOW_RATE=1 QUOTE_SLOW_SECONDS=13 QUOTE_FAILURE_RATE=0`):

```
[ +17.1s]           lead     pode começar dia 17 de outubro
[ +23.1s]  Δ +6.0s  sistema  Tô buscando o valor no sistema e ele tá lento agora. Já te trago, tá?
[ +37.1s]  Δ+20.0s  sistema  Ainda tô aqui, viu? O sistema não me devolveu ainda. Assim que sair eu te mando.
[ +55.7s]  Δ+38.6s  sistema  Não consegui confirmar o valor agora: o sistema de cotação não respondeu.
                             Não vou te passar um número sem ter certeza dele.
                             Já passei sua conversa pra um atendente da equipe...
```

Estado final `encaminhado`, 3 tentativas de ~12s cada registradas em
`quote_attempts`, handoff `cotacao_indisponivel` disparado por **regra** (não pelo
modelo), **nenhum valor monetário em lugar nenhum**. Bate exatamente com o que
`artifacts/transcript-degradado.md` publica.

**Cenário feliz** (`QUOTE_FAILURE_RATE=0 QUOTE_SLOW_RATE=0`):

```
[ +19.0s]  Δ +2.5s  sistema  Fechei sua cotação 👇
                             *Completo — R$ 392,25/mês*
                             ...
                             Começando dia 17/10, o primeiro boleto sai proporcional: *R$ 189,80* (15 dos 31 dias).
                             ⚠️ Roubo e furto começam a valer 30 dias depois do início da vigência.
```

`quote_id` presente com status `ok`, carência citada, franquia citada, pro-rata
calculado corretamente para início dia 17. As duas invariantes centrais do
projeto (preço nunca vem do modelo, carência sempre citada) se sustentaram nos
dois cenários que eu mesmo rodei — não apenas nos artefatos que vieram prontos no
repositório.

O que eu **não** verifiquei de forma independente: os números de timeout (12s),
retry (3 tentativas) e concorrência (semáforo 8) contra a bancada de sete
instâncias que `docs/API-COTACAO.md` descreve — isso exigiria reconstruir a
bancada, fora do orçamento desta avaliação. Aceitei a metodologia como descrita,
mas não a raiz-quadrada dela.

---

## Nota por critério

### C1 — funciona ponta a ponta: **bom, com atrito documentado acima**
A aplicação sobe, o health check passa, o chat responde, cota e persiste. Mas o
"comando único" tem duas portas hardcoded que colidem em qualquer máquina com algo
já rodando nas portas padrão do Postgres/8080 — o próprio README reconhece o
problema para a 8080 e não resolve para a 5432 do `db-debug`. E o comando de teste
publicado não passa limpo num clone fresco (39 falhas, causas reais, não
documentadas).

### C2 — comportamento sob falha da `/quote`: **muito bom**
Reproduzido de ponta a ponta, duas vezes, com resultado idêntico ao publicado.
Job com estado, avisos temporizados a partir do relógio do lead, handoff correto,
zero preço alucinado. É a parte mais sólida da entrega e a que recebeu mais
cuidado de engenharia visível (retry com jitter, circuit breaker, distinção
`refused`/`bad_request`/`transient`/`timeout`).

### C3 — critérios de handoff: **bom**
Tabela de gatilhos explícita, precedência por lista fixa declarada, e
`test_um_teste_por_gatilho` parametrizado por gatilho em `tests/nucleo/test_handoff.py`
(28 testes no arquivo). A recusa de negócio corretamente não vira handoff — e o
código distingue isso do 5xx, que também não deveria.

### C4 — rastreabilidade: **presente, mas parcialmente não verificável nesta sessão**
Esquema de mensagens/cotações/tentativas com ids e status existe, e a leitura do
trace por resposta com mascaramento de CEP (`test_o_CEP_dos_argumentos_NAO_sai_em_claro`)
é uma ideia boa e específica. Não consegui rodar essa suíte com sucesso porque as
tabelas do Agno (`ai.agno_runs`) não existem num banco de debug que nunca recebeu
uma conversa real — acidente de setup, não necessariamente falha de projeto, mas
significa que não presenciei essa parte funcionando, só o código dela.

### C5 — dados sensíveis: **bom, com uma alegação desatualizada**
`grep` por segredo (`sk-ant-`, `AKIA`, chaves privadas) e por CPF em formato
`###.###.###-##` no código e docs: nada encontrado. A suíte de mascaramento usa
gerador semeado, não literal, como o README promete. `tests/nucleo/test_repo_publico.py`
passa (9 passed, 2 skipped). **Porém**: `docs/SEGURANCA.md` e o README afirmam,
com número específico, que "o histórico inteiro (**34 commits**) foi varrido por
chave, token e PII" — `git log --oneline | wc -l` no HEAD atual devolve **50
commits**. Ou a claim está desatualizada (a varredura foi feita num ponto do
histórico e nunca refeita depois de mais 16 commits) ou a contagem estava errada
desde o início. De qualquer forma, uma alegação de segurança com número
verificável que não bate no `git log` é exatamente o tipo de achado que este
exercício pede para caçar.

### C6 — qualidade de código: **acima da média, com um bug real de auto-consistência**
Módulos pequenos, nomes de teste que descrevem intenção (não implementação),
comentários que explicam o "porquê" e não o "o quê". `qa/dataset/caminhos.py` é um
bom exemplo de decisão defensável (sem caminho absoluto, tudo sobrescrevível por
env var) mal comunicada (dependência não documentada). E existe pelo menos um bug
real, não cosmético: o teste de contrato congelado da API falha no próprio modo
como o README manda rodar a suíte, porque o código tem dois caminhos de registro
de rota (`web/dist` existe vs. não existe) e só um deles foi contemplado pelo
teste "anti-deriva".

### C7 — uso de IA: **genuíno**
`ai-logs/` tem 22 arquivos, ~53 mil linhas, 2,3 MB — não é enfeite. Abri uma sessão
ao acaso (`10-construcao-05.md`): é uma revisão de segurança real, com diffs
unificados de arquivos reais do repositório (`web/package.json`,
`app/agent/catalogo.py`) e instruções específicas ("Review this change for
security vulnerabilities"). Os nomes dos arquivos batem com decisões que aparecem
no histórico do Git (ex.: commit sobre remover dependência "morta" do OpenAI SDK
que na verdade era necessária — `tests/nucleo/test_dependencias.py` documenta essa
reversão, e ela aparece coerente entre código, teste e comentário no
`pyproject.toml`).

---

## Os cinco problemas mais graves, em ordem

1. **O comando de teste do README não passa num clone fresco.** 39 falhas reais
   (não flaky, não decorativas), com três causas nunca documentadas: dependência
   de um repositório irmão não mencionada em lugar nenhum, uma tabela do Agno que
   só existe depois de uma conversa real rodar contra aquele banco, e um teste de
   contrato que quebra exatamente no modo "sem frontend buildado" que o próprio
   README instrui. Viola diretamente a regra máxima do próprio `CLAUDE.md`
   ("tudo que o repositório promete tem que estar testado e funcionando").

2. **Números de infraestrutura hardcoded sem variável de ambiente**, quando o
   restante do compose segue rigorosamente o padrão `${VAR:-default}`. A porta
   `8080` do `app` e a `5432` do `db-debug` são as duas exceções, e são
   justamente as que mais provavelmente colidem numa máquina com outro projeto
   rodando — o cenário que este próprio desafio simula ao avisar sobre portas
   ocupadas.

3. **O default de conexão de teste (`conftest.py`, porta 55432) não bate com o
   `docker-compose.yml` (porta 5432 no `db-debug`)**, e o efeito colateral de errar
   esse acoplamento é grave nos dois sentidos: numa máquina limpa, os testes de
   banco são pulados em silêncio (suíte "verde" com metade da cobertura real
   ausente); numa máquina com outro Postgres relevante na 55432, a fixture faz
   `TRUNCATE CASCADE` nele sem confirmação — o que aconteceu comigo durante esta
   avaliação, por engano meu, mas habilitado por esse design.

4. **Alegação de segurança com número que não bate**: "histórico inteiro, 34
   commits, varrido" quando o HEAD atual tem 50. Não é um erro grave em si — não
   há segredo real vazado em nenhum commit que verifiquei — mas é exatamente o
   tipo de "número publicado que não se sustenta" que este exercício pede para
   caçar, e mina a credibilidade dos outros números do README que eu não tive
   como reverificar (custo por conversa, % de cache).

5. **Dependência crítica não declarada do repositório do desafio como diretório
   irmão** (`qa/dataset/caminhos.py`). Trinta e quatro dos 39 testes falhos vêm
   daqui. A decisão de design é defensável; a ausência total de menção no README
   ou em qualquer doc não é — é exatamente o tipo de "passo manual escondido" que
   o item 14 do próprio `CLAUDE.md` promete não ter.

---

## O que eu perguntaria numa entrevista

- "Rodei `uv run pytest -q -m 'not live'` num clone limpo, sem o repositório do
  desafio ao lado, e tomei 34 `FileNotFoundError`. O README não menciona essa
  dependência. Por que ela não está lá, e por que os testes não fazem `skip`
  gracioso quando o dataset não existe, do jeito que `engine_teste` faz com o
  banco?"
- "`docs/SEGURANCA.md` diz 34 commits varridos; o HEAD tem 50. Quando foi a última
  vez que essa varredura rodou de verdade, e por que o número não foi atualizado
  nos ~16 commits seguintes?"
- "O teste `test_as_rotas_escondidas_do_schema_sao_exatamente_as_declaradas` só
  passa se `web/dist` existir. Isso foi percebido durante o desenvolvimento? Se
  sim, por que o README manda rodar a suíte sem antes buildar o frontend?"
- "Por que `db-debug` está hardcoded em `5432:5432` enquanto toda outra variável
  do compose segue `${VAR:-default}`? O que te fez tratar a porta do app como
  problema a resolver e a porta do banco de debug como não?"
- "O fallback de `APP_DATABASE_URL` nos testes aponta para `127.0.0.1:55432`, que
  o comentário do próprio `conftest.py` descreve como 'o Postgres do sistema que a
  pessoa já tem instalado'. Você considerou o risco de rodar `TRUNCATE ... CASCADE`
  contra o banco de outra coisa que por acaso esteja escutando ali?"
- "As medições de cache e custo do README foram feitas com `claude-opus-5`, mas o
  default agora é `claude-sonnet-5`, e o README admite que não foram refeitas.
  Dado isso, o que te faria confiar que o comportamento de cache (leitura nunca
  zero a partir do 2º turno) se mantém igual num modelo diferente?"

---

## O que eu não consegui verificar

- **Os números da bancada de resiliência** (`docs/API-COTACAO.md`): 8,004s de
  chamada lenta, 0,8% de falha residual em 3 tentativas, serialização acima de 40
  chamadas simultâneas. Reconstruir a bancada de sete instâncias estava fora do
  orçamento desta avaliação; aceitei a metodologia descrita sem repetir a medição.
- **O painel de custo e cache no `/admin`** (agora atrás de rotas novas segundo o
  `CLAUDE.md` deste worktree — `/painel`, `/status`): não cliquei na UI; só
  confirmei por `curl` que as rotas administrativas exigem sessão (401/sessão
  ausente), o que é consistente com o README.
- **Providers além de Anthropic**: o README já admite que só Anthropic e Ollama
  foram validados; não testei nenhum.
- **O comportamento sob concorrência real** (múltiplos leads simultâneos): o
  próprio README admite que isso nunca foi testado de verdade; eu também não
  testei.
- **O conteúdo anterior de `autoseguro-db` (porta 55432)**, truncado por engano
  durante esta avaliação — não tenho como saber o que havia lá antes do meu
  comando. Ver a seção de incidente no topo deste documento.
