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

## Qual modelo produziu qual número

**Todos os números de avaliação deste repositório são de `anthropic:claude-opus-5`**, e
o relatório JSON grava o campo `modelo` em cada execução — a comparação entre providers
só é honesta assim.

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
python -m qa.replay --modo desfecho --conversas 30 --ano-corrente 2026 --rodar
```

Sem `--rodar`, o comando imprime a amostra, a estratificação e a estimativa de parede —
que é o que alguém quer ver antes de gastar os minutos.

---

## Módulos nativos do Agno

`ReliabilityEval` (`expected_tool_calls`, `expected_tool_call_arguments`) e
`AgentAsJudgeEval` gravam em `eval_runs`, no mesmo Postgres da aplicação. Harness
próprio existe só para o que é **cálculo** — a conferência de preço contra o conjunto
fechado de 72 prêmios.
