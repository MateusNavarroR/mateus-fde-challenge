# Avaliação — método, cobertura e quem produziu cada número

Este documento existe para que nenhum número deste repositório apareça sem dizer **de
onde veio, com qual modelo, sobre qual amostra**. Uma taxa sem denominador é decoração.

---

## As três camadas, e por que são três

| Camada | O que responde | Determinística? |
|---|---|---|
| **Suíte** (`tests/`) | o mecanismo faz o que promete | sim |
| **Replay do dataset** (`qa/replay/`) | o agente atende as conversas reais de ponta a ponta | não — o modelo varia |
| **Conferência de preço** (`tests/dados/test_preco_contra_api.py`) | o nosso entendimento das regras bate com a `/quote` | sim |

A separação é deliberada: **o que é cálculo nunca é avaliado por juiz de modelo.** A
conferência de preço compara contra o conjunto fechado de 72 prêmios possíveis, com
aritmética. Juiz de modelo aparece num lugar só — o tom da mensagem de recusa —, porque
ali não existe resposta certa computável.

---

## O replay do dataset

### O que ele injeta

**As falas reais do lead, extraídas do parquet, na ordem por `message_index`** — nunca
por `timestamp`, que está fora de ordem em 99,8% das conversas. Nada é roteirizado
exceto dois campos.

O valor do dataset é a linguagem bagunçada de verdade: *"e um Sandero 2022"*, CPF e CEP
soltos no meio da frase, idade informada junto com outra coisa. Nenhum roteiro escrito
por nós imitaria isso, e um roteiro limpo mediria o roteiro.

**O script cobre só dois buracos**, e eles são conhecidos: `data_inicio` e `plano_id`,
que o lead do dataset **nunca** informa e que a nossa qualificação exige. Sem alguém
para respondê-los, toda conversa morreria em `qualificando` e o caminho até `cotado`
nunca seria exercitado.

O respondedor casa a fala do agente **por intenção** e mantém um contador de *"não
entendi a pergunta"*. Acima de 20%, **a suíte reprova o harness, não o agente**: um
casador que erra em silêncio produz um relatório que passa medindo nada. Na execução
registrada: **2%**.

### A amostra é estratificada, não sorteada

Sortear 30 conversas e torcer produz, em metade das execuções, um relatório que não diz
nada sobre 11% do corpus. A amostragem garante presença de cada grupo, por cota, com
troca **dentro da mesma célula** `(estrato, outcome)` — garantir um eixo não pode
desequilibrar os outros.

| Eixo | Estratos |
|---|---|
| elegibilidade (disjunto) | `ambos`, `so_idade`, `so_veiculo`, `cotavel` |
| desfecho do dataset | `ganho`, `perdido`, `em_negociacao`, `sem_resposta` |
| transversal | mídia sem transcrição · objeção de preço |

`tests/dados/test_replay_amostra.py` exige que **todo grupo apareça em qualquer
semente** — cinco sementes no teste. É o que separa uma amostra estratificada de uma
amostra aleatória com nome bonito.

### O que cada grupo afirma

| Grupo | Asserção |
|---|---|
| `so_idade`, `so_veiculo`, `ambos` (**751 no corpus**: 280 idade, 531 veículo) | chamou `quote_plan`, recebeu `refused` **com o motivo certo**, entregou o texto do mapa fixo, e **não** escalou |
| `cotavel` (**1.749**) | os argumentos passados batem com o gabarito: idade, ano do veículo e **CEP** |
| mídia | pediu o dado por texto **ou** encaminhou |
| objeção | uma objeção **não** encaminha — o agente trata e segue |

**Por que o CEP em especial.** Ele é opcional no contrato da `/quote` e é o único cujo
erro produz um **número plausível e errado**: mandar `cep=None` quando o lead informou um
CEP de prefixo de risco devolve 200, com um prêmio 30% menor, sem nenhum sintoma. Idade e
ano errados tendem a produzir recusa ou um valor obviamente fora; o CEP produz silêncio.

### O que o dataset **não** consegue exercitar

**`OBJECAO_FORA_DA_ALCADA` é inalcançável a partir deste corpus.** O gatilho exige a
**segunda** objeção na mesma conversa — a primeira o agente trata. Medido: **628 das
2.500 conversas têm exatamente uma objeção, e nenhuma tem duas.**

Não é amostra pequena; é zero. O relatório imprime `AUSENTE` para o grupo em vez de uma
taxa, e `tests/dados/test_replay_amostra.py` guarda a medição — se o corpus mudar, o
teste falha e esta afirmação deixa de ser publicada.

### Regra de amostra pequena

Abaixo de **5 conversas completadas**, o relatório imprime a fração bruta e **se recusa a
converter em percentual**. "67%" sobre três casos é ruído com casas decimais, e o leitor
só descobre o denominador se for procurar.

---

## O incidente que atrasou a primeira taxa publicada

Esta seção fica como está — histórico, não estado atual. **A seção seguinte tem os
números válidos.**

A primeira execução completa reportou **36,7% (11/30)**, com `cotavel` em **0 de 14**:
`tools_chamadas: []`, `perguntas_do_agente: 0`, `falha: None`. Investigado com a
conversa inteira à vista, o padrão tinha uma fronteira de relógio exata — as 12
primeiras conversas rodaram limpas até 07:05:07, e as 18 seguintes, a partir de
07:05:40, gravaram **«Error code: 400 … Your credit balance is too low …» no lugar da
fala do agente**, a 2–3 s cada, sem latência de inferência.

A conta da Anthropic ficou sem crédito no meio da execução. O número media uma fatura.

**A hipótese concorrente foi descartada com dado**, e ela era plausível: o replay é
literal, então as falas do lead poderiam descarrilar a conversa. Mas desalinhamento
degrada gradualmente e espalhado pela amostra — não vira num instante de relógio, e não
produz zero pergunta com zero tool. A correlação com mídia também é acidental: mídia
está distribuída na amostra, então correlaciona com posição.

Dois defeitos foram corrigidos a partir disso — o produto entregava o erro do provider
ao lead, e o harness contava falha de infraestrutura como erro do agente (o Agno devolve
`RunOutput` com `status=ERROR` em vez de levantar).

---

## As taxas válidas

Duas execuções completas, mesma amostra estratificada de 30 conversas (a seed padrão do
replay, `amostragem.SEED_PADRAO`),
uma por modelo — o relatório grava o campo `modelo` em cada uma. Nenhuma reprova o
harness: `nao_entendi` ficou em 2%, dentro do limiar de 20% que reprovaria o casador de
falas, não o agente.

| | `anthropic:claude-sonnet-5` (default atual) | `anthropic:claude-opus-5` |
|---|---|---|
| relatório | `qa/_saida/replay/replay-sonnet.json` | `qa/_saida/replay/replay-desfecho.json` |
| desfecho correto | **30/30 (100%)** | 28/30 (93,3%) |
| preço exato (das 14 conversas com prêmio calculável) | **14/14** | não medido nesta bateria |
| extração — idade / veículo / CEP | **30/30 · 30/30 · 30/30** | não medido nesta bateria |
| mídia tratada (de 18 com anexo) | 16/18 | 14/18 |
| tool proibida chamada | 0 | 0 |
| turnos somados / tempo de parede somado | 213 / 698 s | 186 / 856 s |

Os dois relatórios ficam em `qa/_saida/replay/`, que **não é versionado** (ver
"Onde a evidência fica" abaixo) — reproduzível pelo comando desta seção, não pelo
commit do JSON.

**Os módulos nativos do Agno também rodaram, de verdade, nesta bateria** —
`qa/replay/evals.py`, ligado pelo executor com a flag `--evals` (e `--evals-db` para
outra URL de Postgres). Antes desta fatia, os dois módulos existiam como código
testável que nenhum caminho de produto chamava: a tabela `ai.eval_runs` nunca existia,
`_evals()` (`app/api/consultas.py`) caía no `except` e devolvia zeros, e o painel
mostrava um traço — indistinguível, para quem opera, de "avaliou e nada passou".
Medido: os **30 casos de `ReliabilityEval` passaram**; o `AgentAsJudgeEval` avaliou os
três textos de recusa (`docs/TEXTOS.md` ⑤⑥⑦) — uma vez por motivo, não por conversa,
porque o texto é sempre o mesmo mapa fixo — e **aprovou com nota 9**. O relatório conta
o que está de fato gravado no banco (`conferir_gravacao()`), não o que a chamada
afirmou ter gravado, porque o Agno engole falha de escrita em silêncio internamente.

## Qual modelo produziu qual número

O relatório JSON grava o campo `modelo` em cada execução — a comparação entre providers
só é honesta assim. **As taxas de acerto do replay** (seção acima) foram medidas com os
dois modelos que este repositório valida, `anthropic:claude-sonnet-5` (default atual) e
`anthropic:claude-opus-5`.

⚠️ **Nem todo número deste repositório foi remedido.** O default da aplicação mudou
para Sonnet depois de várias medições — em especial as de **cache de prompt e custo**
(README §§6–7), que continuam nomeando `claude-opus-5` porque não foram refeitas. Um
número medido com um modelo não vira número de outro por edição de texto: quem quiser
os valores de cache/custo do default atual roda o replay de novo — é uma linha, e o
campo `modelo` do relatório dirá qual foi.

O Ollama (`ollama:qwen2.5:7b`) foi validado por **smoke test de uma conversa completa**,
e **não** foi submetido ao replay nem à suíte `live` inteira. Onde este repositório diz
"validado" para o Ollama, é isso que quer dizer.

---

## Reprodutibilidade

Um cenário da `/quote` é a tripla **(seed, processo reiniciado, sequência exata de
requisições)** — a seed sozinha não basta, porque o RNG do legado é um fluxo global e
contínuo do processo: uma falha consome dois valores, um sucesso consome um, e um 422 do
Pydantic não consome nenhum.

⇒ As suítes marcadas `serial` **não podem** rodar em paralelo, e o replay reinicia a
instância da `/quote` antes de começar.

O replay roda contra a instância **realista** (20% de falha, 10% lentas), não a limpa. A
falha de infraestrutura é classificada à parte (`indisponivel`) e **não conta contra o
agente**: somá-la produziria uma taxa de acerto que cai quando o legado piora.

```bash
# banco PRÓPRIO da avaliação, com volume nomeado: `down` não leva a evidência junto,
# e a suíte (que dá TRUNCATE nas fixtures) não pode matar a execução no meio.
docker compose --profile avaliacao up -d replay-db

APP_DATABASE_URL=postgresql+psycopg://<usuario>:<senha>@127.0.0.1:55433/autoseguro_replay \
APP_QUOTE_API_URL=http://localhost:8004 \
  python -m qa.replay --modo desfecho --conversas 30 --ano-corrente 2026 --rodar \
  --evals --evals-db postgresql+psycopg://<usuario>:<senha>@127.0.0.1:55433/autoseguro_replay
```

`--evals` liga `ReliabilityEval`/`AgentAsJudgeEval` de verdade (seção "As taxas
válidas"); sem a flag, o replay mede só desfecho/preço/extração e não grava em
`ai.eval_runs`. `--evals-db` aceita outra URL quando a avaliação deve gravar num banco
diferente do da execução — por padrão usa o mesmo `APP_DATABASE_URL`.

### Onde a evidência fica

| Artefato | Onde | Sobrevive a `docker compose down`? |
|---|---|---|
| relatório JSON (veredito por conversa) | `qa/_saida/replay/*.json` | é arquivo — sim |
| **transcripts** (as mensagens) | `qa/_saida/replay/transcripts/*.md` | é arquivo — sim |
| linhas do banco | `replay-db`, volume `replaydata` | sim, só `down -v` apaga |

Os transcripts existem porque o JSON carrega o **veredito** e não o **porquê**. Antes
deles, as mensagens ficavam só no contêiner: uma execução de avaliação cuja evidência
desaparece ao parar o contêiner não é evidência reproduzível — e foi olhando as
mensagens que se descobriu que os 36,7% mediam uma conta sem crédito.

`qa/_saida/` não é versionado: é derivado do dataset, e o dataset não é nosso para
redistribuir, nem mascarado. O que torna a execução reproduzível é o comando com a
seed, não o commit do resultado.

Sem `--rodar`, o comando imprime a amostra, a estratificação e a estimativa de parede —
que é o que alguém quer ver antes de gastar os minutos.

---

## Módulos nativos do Agno

`ReliabilityEval` (`expected_tool_calls`, `expected_tool_call_arguments`) e
`AgentAsJudgeEval` gravam em `eval_runs`, no mesmo Postgres da aplicação. Harness
próprio existe só para o que é **cálculo** — a conferência de preço contra o conjunto
fechado de 72 prêmios.
