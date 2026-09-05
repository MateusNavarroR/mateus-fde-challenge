# Relatório — sistema de avaliação (evals) do Agno


> ## Estado deste relatório
>
> **Todos os achados abaixo foram corrigidos.** Este documento é mantido como está —
> com o veredito original e os achados na forma em que foram encontrados — porque um
> relatório de auditoria reescrito depois da correção deixa de ser auditoria e vira
> apresentação. O que ele registra é o que existia no momento em que foi escrito.
>
> O que mudou desde então está no histórico do Git (commits `465e162` e seguintes) e, para cada achado,
> num teste que o trava. Os evals passaram a rodar de verdade (`--evals`), gravam em `ai.eval_runs`, e o painel mostra o número. Medido na última execução: 30/30 de `ReliabilityEval` e 3/3 do `AgentAsJudgeEval`.


**Veredito: não funcional.** Os dois módulos existem como código testável em
isolamento (`qa/replay/assercoes.py`), mas nenhum dos dois roda no replay real, nenhum
dos dois grava no Postgres, a tabela que o painel lê (`ai.eval_runs`) não existe, e o
painel devolve `{"total": 0, "passaram": 0}` por captura silenciosa de exceção — não
porque não houve avaliação, mas porque a tabela nunca foi criada. `docs/EVALS.md` e
`docs/DECISOES-FECHADAS.md` afirmam algo que o repositório não faz.

Ambiente conferido: Agno **3.0.6** instalado em
`.venv/lib/python3.13/site-packages/agno/` (confirmado por
`python -c "import agno; print(agno.__version__)"`). Postgres da aplicação inspecionado
via `docker exec mateus-fde-challenge-db-1 psql -U postgres -d autoseguro`.

---

## 1. Implementado × executado × provado

| Item | Implementado | Executado (fora de teste) | Provado |
|---|---|---|---|
| `assercoes.montar_reliability()` (`qa/replay/assercoes.py:187`) | Sim | **Não** — `qa/replay/executor.py` nunca a importa nem chama | Parcial: `tests/dados/test_replay_assercoes.py:213-251,320` chama `.run()` de verdade sobre um `RunOutput` sintético (`_Run`), sem `db=`. Prova que a *lógica de casamento de tool calls* funciona (matching de `expected_tool_calls`/`expected_tool_call_arguments`); não prova nada sobre persistência, porque `db=None` em todos os usos de teste |
| `assercoes.montar_juiz_da_recusa()` (`qa/replay/assercoes.py:310`) | Sim | **Não** | **Não** — `tests/dados/test_replay_assercoes.py:299-307` só faz `isinstance(juiz, AgentAsJudgeEval)` e confere `scoring_strategy`/`threshold`. Nenhum teste chama `.run(input=..., output=...)`. Confirmado por grep: `montar_juiz_da_recusa` e `AgentAsJudgeEval` não aparecem em nenhum lugar do repo além dessa definição e desse teste de atributos |
| Persistência em `ai.eval_runs` | Não | Não | Não — tabela **não existe** no Postgres (`\dt ai.*` lista só `agno_runs`, `agno_sessions`, `agno_schema_versions`) |
| `app/api/consultas.py::_evals()` (linha 186) | Sim | Sim (roda a cada request do painel) | Prova o oposto do que promete: cai sempre no `except Exception` da linha 200-201 e devolve zeros. A query em si (`eval_data->>'eval_status' = 'PASSED'`) está **correta** contra o schema real do Agno (ver §4) — o problema não é a query, é que a tabela nunca foi populada |

**O que um teste que passa com `RunOutput` sintético prova, exatamente:** que
`ReliabilityEval` compara corretamente `ToolExecution` contra `expected_tool_calls` e
`expected_tool_call_arguments` — a mecânica de casamento de tools/argumentos do Agno,
que é código deles, não nosso. Não prova que o replay chama essa função, não prova que
o resultado chega ao Postgres, e não prova nada sobre `AgentAsJudgeEval` porque este
nunca roda nem sinteticamente.

---

## 2. Implementado mas nunca executado em produção/replay

- `qa/replay/assercoes.py:187` `montar_reliability()` — construída em 5 testes, chamada
  zero vezes por `qa/replay/executor.py`.
- `qa/replay/assercoes.py:310` `montar_juiz_da_recusa()` — construída em 1 teste
  (só verificação de atributos), `.run()` nunca invocado em lugar nenhum do repositório.
- Nenhum dos dois recebe `db=` real em nenhum ponto do código versionado. O parâmetro
  `db` existe na assinatura das duas funções (`assercoes.py:191` e `:310`) mas todo
  chamador — que é só o teste — passa `db=None` implícito ou explícito.

Confirmado por:
```
grep -rn "montar_reliability\|montar_juiz_da_recusa" --include="*.py" .
```
que só retorna a própria definição em `assercoes.py` e os usos em
`tests/dados/test_replay_assercoes.py`.

---

## 3. O que `docs/EVALS.md` e `docs/DECISOES-FECHADAS.md` afirmam e não se sustenta

- **`docs/EVALS.md:180`**: *"`ReliabilityEval` (…) e `AgentAsJudgeEval` gravam em
  `eval_runs`, no mesmo Postgres da aplicação."* — Falso no estado atual. Nenhum dos
  dois é chamado fora de teste; a tabela `eval_runs` não existe no schema `ai` da
  aplicação (verificado por `\dt ai.*`).
- **`docs/DECISOES-FECHADAS.md:343`**: tabela que lista `ReliabilityEval` e
  `AgentAsJudgeEval` com coluna "Persiste" = `db=PostgresDb(db_url=..., eval_table="eval_runs")`
  para os dois. Essa é a assinatura *correta* da API do Agno (confirmada em §4), mas a
  afirmação implícita — de que isso é o que o repositório faz — não se sustenta: em
  nenhum ponto do código de produção ou do executor de replay um `PostgresDb` é
  instanciado e passado como `db=` para essas duas classes.
- **`CLAUDE.md:181` (invariante 27)**: *"ambos com `db=PostgresDb(..., eval_table="eval_runs")`
  no mesmo Postgres da aplicação"* — mesma afirmação, mesmo problema: descreve uma
  integração que não existe em `qa/replay/executor.py`.
- **`app/api/consultas.py:186-187`**: o docstring de `_evals()` diz *"O que os módulos
  nativos do Agno gravaram em `ai.eval_runs`"* — pressupõe que algo grava lá. Nada grava.
  O comportamento do `except` (linhas 199-201) é deliberadamente silencioso ("Ausente a
  tabela, devolve zeros em silêncio: o painel não pode quebrar porque ninguém rodou
  avaliação ainda") — o que é uma decisão de robustez defensável, mas o painel mostrando
  `—`/zero é indistinguível, para quem opera, de "avaliação rodou e passou 0". O
  documento e o código não avisam essa ambiguidade ao usuário do painel.

Em suma: a regra máxima do `CLAUDE.md` ("tudo que o repositório promete tem que estar
testado e funcionando") é violada por três documentos (`docs/EVALS.md`,
`docs/DECISOES-FECHADAS.md`, `CLAUDE.md` mesmo) descrevendo uma integração fim-a-fim
que não existe — só as classes soltas, testadas isoladamente.

---

## 4. Caminho mínimo para os evals gravarem em `ai.eval_runs`

Confirmado por leitura direta do código instalado (`agno==3.0.6`,
`.venv/lib/python3.13/site-packages/agno/eval/reliability.py` e
`.../agent_as_judge.py`), com apoio da doc oficial via MCP `agno-docs`:

- **`ReliabilityEval`** (`agno/eval/reliability.py:78-116`) é um `@dataclass` com,
  entre outros, `agent_response: Optional[RunOutput]`, `expected_tool_calls`,
  `expected_tool_call_arguments`, `allow_additional_tool_calls: bool = False`,
  `db: Optional[Union[BaseDb, AsyncBaseDb]] = None`. `.run(self, *, print_results=False)`
  (linha 273) grava só se `self.db` é truthy (linha 314): monta
  `run_data=asdict(result)` (que inclui o campo `eval_status`, confirmando que a query
  do painel — `eval_data->>'eval_status'` — usa o **nome de chave correto**) e chama
  `log_eval_run(db=self.db, run_id=run_id, run_data=..., eval_type=EvalType.RELIABILITY, ...)`
  (`agno/eval/reliability.py:333`), que por sua vez chama `db.create_eval_run(EvalRunRecord(...))`
  (`agno/eval/utils.py:113-129`).
- **`AgentAsJudgeEval`** (`agno/eval/agent_as_judge.py:190-217`) tem `db` idêntico.
  `.run(self, *, input=None, output=None, cases=None, ...)` (linha 479) — **assinatura
  diferente de `ReliabilityEval`**: não recebe `agent_response`, recebe `input`/`output`
  como strings (single mode) ou `cases` (batch mode), confirmado pelos exemplos oficiais
  em `docs.agno.com/evals/agent-as-judge/overview` e
  `docs.agno.com/examples/evals/agent-as-judge/agent-as-judge-basic` via MCP `agno-docs`.
  Também grava condicionalmente a `self.db` (linhas 424, 457).
- **Persistência acontece dentro de `.run()`**, síncrona, no mesmo processo que chama —
  não há job separado nem flush posterior.
- **A tabela é criada sozinha.** `PostgresDb._get_table(table_type="evals")`
  (`agno/db/postgres/postgres.py:619-625`) chama `_get_or_create_table(table_name=self.eval_table_name, table_type="evals", create_table_if_not_found=...)` — não é preciso migração manual; o próprio `create_eval_run` aciona a criação na primeira escrita.
- **Nome real da tabela e schema**: `EVAL_TABLE_SCHEMA`
  (`agno/db/postgres/schemas.py:82-97`) define colunas `run_id` (PK), `eval_type`,
  `eval_data` (JSONB), `eval_input` (JSONB), `name`, `agent_id`, `team_id`,
  `workflow_id`, `model_id`, `model_provider`, `evaluated_component_name`, `user_id`,
  `created_at`, `updated_at`. O nome da tabela é `eval_table_name`, que por padrão
  (sem passar `eval_table=` no construtor do `PostgresDb`) monta um nome default — o
  código do próprio projeto em `app/agent/agente.py:58`
  (`_db = PostgresDb(db_url=get_settings().database_url)`) **não passa `eval_table="eval_runs"`**,
  então, mesmo se alguém reaproveitasse essa instância para os evals, o nome da tabela
  resultante não é necessariamente `eval_runs` a menos que seja passado explicitamente,
  como a documentação e `CLAUDE.md`/`DECISOES-FECHADAS.md` prescrevem. O schema-alvo é
  `ai` por padrão (`db_schema` default `"ai"`, `agno/db/postgres/postgres.py:213,245`),
  que bate com o que `_evals()` consulta (`from ai.eval_runs`).
- **`eval_data->>'eval_status'` existe com esse nome exato** — confirmado:
  `ReliabilityResult` (`agno/eval/reliability.py:27-34`) tem o campo `eval_status: str`,
  e `run_data=asdict(result)` grava o dataclass inteiro, incluindo essa chave, dentro de
  `eval_data` (JSONB). A query de `app/api/consultas.py:200-202` está correta contra o
  formato real — **não é aí que está o bug**.

**Passos mínimos para fechar o buraco:**
1. Em `qa/replay/executor.py`, instanciar um `PostgresDb(db_url=..., eval_table="eval_runs")`
   (ou reaproveitar `app.agent.agente._db_do_processo()` mas passando `eval_table="eval_runs"`
   explicitamente, já que o default não garante esse nome) e passá-lo como `db=` para
   `assercoes.montar_reliability(...)` a cada conversa com tool obrigatória.
2. Chamar `.run(print_results=False)` no resultado — hoje o `_conferir()` do executor
   já calcula `expectativa`/`chamadas` via `assercoes.conferir_tools`, mas descarta a
   oportunidade de também rodar o `ReliabilityEval` de verdade com persistência.
3. Para o juiz: montar `montar_juiz_da_recusa(model=..., db=...)` **uma vez por motivo
   de recusa** (conforme o próprio docstring de `assercoes.py:310-322` já planeja) e
   chamar `.run(input=<motivo>, output=app.textos.POR_MOTIVO[motivo])` — não uma vez por
   conversa.
4. Link da doc oficial usada para confirmar as assinaturas:
   `https://docs.agno.com/reference/evals/reliability`,
   `https://docs.agno.com/reference/evals/agent-as-judge`, e os exemplos em
   `https://docs.agno.com/examples/evals/agent-as-judge/agent-as-judge-basic` (via MCP
   `agno-docs`, `query_docs_filesystem_agno` sobre `/reference/evals/*.mdx` e
   `/evals/**/*.mdx`).

Nada disso foi implementado por este relatório — é o caminho, não a correção.

---

## 5. Custo estimado em chamadas de modelo

- **Hoje: zero.** `AgentAsJudgeEval` nunca é `.run()`-ado em lugar nenhum do
  repositório (nem em teste, nem em replay), então o custo atual desse módulo é
  literalmente zero chamadas.
- **Se implementado como o próprio código já planeja** (`assercoes.py:317-320`: *"roda
  uma vez por motivo, não uma vez por conversa"*): `MotivoRecusa` tem exatamente
  **3 valores** (`IDADE_ACIMA`, `IDADE_ABAIXO`, `VEICULO_ANTIGO` —
  `app/contracts/quote.py:183-185`), e o texto de recusa vem de um mapa fixo de 3
  entradas (`app/textos.py:105-109`, `POR_MOTIVO`). Logo um replay completo, rodado
  como desenhado, chamaria o modelo-juiz **3 vezes no total**, independentemente do
  tamanho da amostra — porque o alvo é a nossa redação fixa, não a fala do agente.
- **Risco se implementado errado** (uma chamada por conversa recusada em vez de uma por
  motivo): o corpus tem 751 conversas nos estratos `so_idade`/`so_veiculo`/`ambos`
  (`docs/EVALS.md`: 280 idade + 531 veículo = 811, valor citado como 751 no documento —
  discrepância aritmética não investigada aqui, sinalizada como "não verificado"). Uma
  amostra de replay de 30 conversas, se mal implementada, chamaria o juiz até uma vez
  por conversa recusada da amostra (tipicamente uma fração pequena de 30) — ainda
  barato, mas não é o desenho documentado.
- `ReliabilityEval` **não chama modelo nenhum** — é comparação estrutural de
  `ToolExecution` contra listas esperadas, sem custo de inferência. Confirmado lendo
  `agno/eval/reliability.py:_evaluate` — não há chamada a `Model`/`Agent` ali.

---

## 6. Tracing nativo do Agno (`setup_tracing`)

**Disponível na 3.0.6, mas inoperante neste repositório por dependência ausente.**

- `agno.tracing.setup_tracing(db, batch_processing=False, max_queue_size=2048, max_export_batch_size=512, schedule_delay_millis=5000)`
  existe e está implementado em
  `.venv/lib/python3.13/site-packages/agno/tracing/setup.py:24-30`. Assinatura exata
  confirmada por leitura direta do arquivo.
- O import de `openinference.instrumentation.agno.AgnoInstrumentor` e dos módulos
  `opentelemetry.*` está dentro de um `try/except ImportError` no topo do módulo
  (`agno/tracing/setup.py:12-20`), que seta `OPENTELEMETRY_AVAILABLE = False` se
  faltarem. **Confirmado que faltam**: `pip show openinference-instrumentation-agno`
  retorna `WARNING: Package(s) not found`. Chamar `setup_tracing()` hoje levantaria
  `ImportError: OpenTelemetry packages are required for tracing. Install with: pip
  install opentelemetry-api opentelemetry-sdk openinference-instrumentation-agno`
  (mensagem exata do código, linha 67-69).
- **Não está em `pyproject.toml`** — confirmado por leitura integral do arquivo: a
  lista de `dependencies` (linhas 6-27) não cita `opentelemetry` nem `openinference`
  em nenhuma forma.
- **Tabelas `agno_traces`/`agno_spans`**: não confirmado que existam esses nomes
  exatos no schema instalado — o grep por `agno_traces`/`agno_spans` neste relatório
  não encontrou ocorrência literal desses nomes de tabela no código instalado nem no
  Postgres da aplicação (`\dt` do schema `ai` lista só `agno_runs`, `agno_sessions`,
  `agno_schema_versions` — sem tabela de traces). Como a exportação usa
  `DatabaseSpanExporter(db=db)` (`agno/tracing/setup.py`, import de
  `agno.tracing.exporter`), o nome real da tabela de destino não foi lido linha a
  linha neste relatório — **não verificado** o nome exato da tabela de spans no
  código-fonte de `agno/tracing/exporter.py` nem em `agno/db/postgres/schemas.py`
  além do que já foi listado (`EVAL_TABLE_SCHEMA`); recomenda-se essa leitura antes de
  qualquer decisão de adoção.
- **O que o tracing daria que `turn_usage` não dá hoje**: `turn_usage` é granularidade
  de **turno** (um `RunMetrics` por resposta do agente ao lead — `CLAUDE.md` §25),
  sem visibilidade por *chamada individual* de tool ou de modelo dentro do turno.
  O tracing nativo, segundo o docstring de `setup_tracing`
  (`agno/tracing/setup.py:32-38`), captura spans para `agent.run`/`arun`,
  `model.response`, execuções de tool e coordenação de team — ou seja, decompor um
  turno com múltiplas tool calls (ex.: `qualify_lead` seguido de `quote_plan` no mesmo
  turno) em spans individuais com duração e (conforme convenção OpenInference) tokens
  por chamada, algo que `turn_usage` (agregado por turno) não permite reconstruir.

**Veredito de viabilidade:** tecnicamente disponível na versão instalada, mas
**não plugável sem trabalho**: exige adicionar `opentelemetry-api`,
`opentelemetry-sdk` e `openinference-instrumentation-agno` como dependências novas
(hoje ausentes de `pyproject.toml`), decidir sobre custo de armazenamento por
span (potencialmente muito mais linhas que `turn_usage`), e verificar se as tabelas
resultantes cabem na promessa do item 17 do `CLAUDE.md` ("nenhuma observabilidade é
dependência") — como é armazenamento no próprio Postgres da aplicação (não um serviço
externo), a leitura mais provável é que isso não viola o item 17, mas isso é uma
interpretação, não uma verificação de código, e fica marcada como tal.

---

## Notas de verificação

- Comandos usados para todas as afirmações de banco:
  `docker exec mateus-fde-challenge-db-1 psql -U postgres -d autoseguro -c "\dt ai.*"` e
  `-c "\dt"`.
- Comando para confirmar a versão instalada:
  `.venv/bin/python -c "import agno; print(agno.__version__)"` → `3.0.6`.
- Suíte `tests/dados/test_replay_assercoes.py` rodada isoladamente:
  `.venv/bin/python -m pytest tests/dados/test_replay_assercoes.py -q` → **30 passed**.
  Todos os 30 testes passam hoje; isso prova a lógica de `assercoes.py` isoladamente,
  não a integração com o Postgres nem com o replay real.
- Pontos marcados "não verificado" neste relatório: (a) a discrepância aritmética
  751 vs. 280+531=811 em `docs/EVALS.md`; (b) o nome exato das tabelas de tracing
  (`agno_traces`/`agno_spans`) no código-fonte de `agno/tracing/exporter.py` e no
  schema Postgres correspondente; (c) se o item 17 do `CLAUDE.md` seria tecnicamente
  violado ao adotar `openinference-instrumentation-agno` — isso depende de leitura da
  definição de "dependência" que o time já usa para outros itens do checklist de
  segurança/escopo, não conferida aqui.
