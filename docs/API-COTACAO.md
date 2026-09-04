# A API de cotação — mapeamento por execução

> **Método.** Este documento não foi escrito lendo o enunciado. Foi escrito lendo
> `quote-service/app/main.py`, `quote_logic.py` e `data/plans.json` linha a linha e,
> em seguida, **batendo na API** com sete instâncias configuradas de propósito para
> isolar cada comportamento. Todo número aqui é medido; onde uma medição contradiz
> uma hipótese anterior, a contradição está registrada na §9.
>
> **Data de referência das medições:** 2026-09-04 (a API usa `date.today()` — ver §4.2).

---

## 1. Bancada de medição

Sete containers da mesma imagem, cada um com uma configuração de instabilidade, para
que cada efeito possa ser observado isolado dos outros:

| Porta | Instância | `FAILURE_RATE` | `SLOW_RATE` | `SLOW_SECONDS` | `SEED` | Para quê |
|---|---|---|---|---|---|---|
| 8001 | `lab-clean` | 0 | 0 | — | — | contrato, regras de preço, taxonomia de erro sem ruído |
| 8002 | `lab-fail` | 1.0 | 0 | — | — | forma da falha e precedência |
| 8003 | `lab-slow` | 0 | 1.0 | 8 | — | latência e timeout |
| 8004 | `lab-seed` | 0.20 | 0.10 | 8 | 42 | reprodutibilidade |
| 8005 | `lab-mix` | 0.5 | 0.5 | 0.4 | — | ciclos rápidos |
| 8006 | `lab-over` | 0.9 | 0.2 | 0.4 | — | independência entre tentativas |
| 8007 | `lab-seedfast` | 0.20 | 0.10 | 0.6 | 42 | séries seed longas sem esperar 8s |
| 8000 | default | 0.20 | 0.10 | 8 | — | o que o `docker-compose.yml` do desafio sobe |

---

## 2. Endpoints

| Método | Rota | Sujeito ao sorteio de instabilidade? | Medição |
|---|---|---|---|
| `GET` | `/health` | **não** | 30/30 = 200 em `lab-fail`; 3 ms em `lab-slow` |
| `GET` | `/planos` | **não** | 30/30 = 200 em `lab-fail`; resposta byte a byte igual a `plans.json` |
| `POST` | `/quote` | **sim** | ver §3 |

Consequências de engenharia:

- `/health` **não mede a saúde da `/quote`.** Ele responde 200 mesmo com
  `FAILURE_RATE=1.0`. Um monitor que só olha `/health` reporta "tudo bem" enquanto
  100% das cotações falham. A tela de status precisa mostrar a taxa de sucesso real
  das últimas tentativas de `/quote`, não só o health check — este é o motivo pelo
  qual `/admin/status` não é redundante com `/health`.
- `GET /planos` é estável e barato → é a fonte legítima para a tabela de planos e
  regras exibida ao lead (`fetch_plans`), sem depender do caminho instável.
- `GET /planos` == `plans.json`, verificado por comparação de objeto JSON: **True**.

Rotas e métodos fora do contrato: `GET /quote` → **405**; `POST /cotacao` → **404**;
`POST /quote` com corpo form-encoded → **422**.

O legado expõe `/docs` e `/openapi.json` abertos (200). É o serviço deles, não o nosso;
registrado aqui apenas porque o nosso backend **não** deve repetir esse default.

---

## 3. A instabilidade — mecânica exata

O sorteio acontece **antes** de qualquer validação de negócio, dentro do handler:

```python
roll = _rng.random()
if roll < FAILURE_RATE:                 # 0.20 default
    kind = _rng.choice(["500","502","503"])
    return JSONResponse(status_code=int(kind), content={...})
if roll < FAILURE_RATE + SLOW_RATE:     # 0.20..0.30
    time.sleep(SLOW_SECONDS)            # 8s — e DEPOIS calcula normalmente
return cotar(...)
```

### 3.1 A falha

Corpo idêntico nos três códigos, sem cabeçalho de retry:

```
HTTP/1.1 500 | 502 | 503
content-type: application/json

{"error":"upstream_unavailable",
 "message":"Servico de cotacao temporariamente indisponivel. Tente novamente."}
```

Distribuição medida em 90 chamadas a `lab-fail`: **500 → 31 · 502 → 31 · 503 → 28**
(uniforme, como o `choice` sugere).

**Não existe `Retry-After`.** O backoff é 100% responsabilidade do cliente — não há
nada para respeitar vindo do servidor.

### 3.2 A lentidão **não é uma falha**

`lab-slow`, três chamadas: **8,004s · 8,005s · 8,004s**, todas **200**, com o corpo
correto e completo (inclusive `primeiro_pagamento_pro_rata`).

Prova direta do custo de errar o timeout, mesma instância, mesma requisição:

| Timeout do cliente | Resultado |
|---|---|
| `-m 5` | erro 28 (timeout), status 000 — **um sucesso destruído pelo cliente** |
| `-m 12` | **200 em 8,00s** |

→ **O read timeout tem que ser maior que `SLOW_SECONDS`.** Com o default de 8s, um
timeout de 12–15s. Um timeout menor converte 10% de sucessos em falhas artificiais e,
pior, converte-os em falhas que o retry vai reproduzir — porque o próximo sorteio pode
cair de novo na faixa lenta.

### 3.3 Teto de concorrência: 40 chamadas lentas simultâneas

O handler é `def` (síncrono) → o FastAPI o executa no threadpool do AnyIO, cujo limite
default é **40 threads**. `time.sleep(8)` ocupa uma thread inteira.

60 chamadas concorrentes a `lab-slow`:

| Duração observada | Quantidade |
|---|---|
| ~8,1 – 8,9 s | 40 |
| ~16,3 – 16,7 s | 20 |

As 20 excedentes **enfileiraram** e levaram o dobro. Uma chamada lenta não bloqueia as
outras até 40; a partir daí o tempo dobra e **um timeout de 12–15s expira**.

→ O nosso cliente precisa **limitar a concorrência contra a `/quote`** (semáforo bem
abaixo de 40). Sem isso, o dimensionamento do timeout deixa de valer sob carga —
e o modo de falha é o pior possível: falha artificial em massa, exatamente quando há
mais leads.

### 3.4 Cada tentativa é um sorteio independente

O sorteio não depende do payload nem de tentativa anterior. Verificação empírica em
`lab-over` (`FAILURE_RATE=0.9`), 200 grupos de 3 tentativas com o mesmo payload:

| Medição | Valor | Esperado se independente |
|---|---|---|
| 1ª tentativa falhou | 178/200 = 0,890 | 0,900 |
| **as 3 falharam** | **144/200 = 0,720** | **0,9³ = 0,729** |

Independência confirmada. Logo, com o default `FAILURE_RATE=0.20`:

| Tentativas | Falha residual |
|---|---|
| 1 | 20 % |
| 2 | 4 % |
| **3** | **0,8 %** |
| 4 | 0,16 % |

**3 tentativas é o ponto de retorno decrescente.** A 4ª compra 0,64 ponto percentual e
custa mais um ciclo de espera — que pode ser 8s se cair na faixa lenta. O orçamento de
tempo é o critério, não a taxa.

### 3.5 `QUOTE_SEED` é reprodutível — com duas condições

`lab-seed` (SEED=42), 25 chamadas idênticas em série, com `docker restart` entre as
rodadas:

```
rodada A: 200 502 200 500 200 200 502 500 200 200 500 200 200 200 200 200 200 200 502 200 502 502 502 200 200
rodada B: 200 502 200 500 200 200 502 500 200 200 500 200 200 200 200 200 200 200 502 200 502 502 502 200 200
→ idênticas
```

Sem restart, continuando a mesma série:

```
rodada C: 200 200 200 200 200 200 200 200 200 200 500 200 200 200 200 200 200 200 502 200 200 200 200 200 503
→ diferente
```

O RNG é **um fluxo global e contínuo do processo**, não um sorteio indexado por
requisição. Portanto:

1. **Condição 1 — reiniciar o processo** antes de cada teste que depende da série.
   `QUOTE_SEED` fixa o início do fluxo, não cada chamada.
2. **Condição 2 — chamadas sequenciais.** Mesma bancada, 20 chamadas com `SEED=42`:

   | Modo | rodada 1 | rodada 2 | reprodutível |
   |---|---|---|---|
   | sequencial | `200 502 200 500 200 200 502 500 200 200 500 200 ...` | idêntica | **sim** |
   | paralelo (20 threads) | `200 502 200 500 200 200 502 200 500 200 500 200 ...` | `200 500 502 200 200 200 502 500 200 200 200 500 ...` | **não** |

   Em paralelo o *multiset* de desfechos se preserva, mas a atribuição a cada
   requisição embaralha, porque as threads consomem o RNG global em ordem de chegada.

Há ainda um terceiro efeito, que vem da leitura do código: **uma falha consome dois
valores do RNG** (`random()` e `choice()`) e um sucesso consome um. E uma requisição
rejeitada pela validação do Pydantic **não consome nenhum** (§4.1). Logo a série
depende do número *e da forma* das requisições anteriores. Na prática:

> Um cenário reproduzível é a tripla **(seed, processo reiniciado, sequência exata de
> requisições)** — não a seed sozinha.

É por isso que o transcript entregue (entregável nº4) precisa fixar o cenário inteiro,
e a suíte que depende de seed roda em série, nunca em paralelo.

### 3.6 A falha vence a regra de negócio

Este é o achado mais importante desta seção, e não estava previsto.

Em `lab-fail` (`FAILURE_RATE=1.0`), um lead **incotável** (idade 80 — uma recusa de
negócio certa):

```
idade 80, 5 chamadas -> 502 503 502 500 502
```

Nenhum 422. O sorteio acontece antes de `cotar()`, então **um 5xx mascara a recusa**.

Já um payload que o Pydantic rejeita nunca chega ao handler:

```
sem idade/veiculo_ano, 5 chamadas -> 422 422 422 422 422
```

Consequência direta para o agente: **na primeira chamada é impossível distinguir
"este lead é inelegível" de "o legado caiu".** Com o default de 20%, um em cada cinco
leads recusados apresenta-se primeiro como indisponibilidade. É o retry que revela a
recusa — o mesmo mecanismo que existe para a resiliência é o que produz o
diagnóstico correto do caminho de recusa (que é 30% do tráfego, §7).

→ O agente **nunca** pode concluir "não consigo te atender" a partir de um 5xx, e
**nunca** pode concluir "o sistema está fora" sem ter esgotado as tentativas.

---

## 4. Contrato de entrada

```json
{
  "plano_id":    "essencial | completo | premium",   // opcional, default "essencial"
  "idade":       35,                                  // obrigatório, int, 0..200
  "veiculo_ano": 2022,                                // obrigatório, int, 1950..2100
  "cep":         "01XXX-XXX",                         // opcional, string|null
  "data_inicio": "2026-07-15"                         // opcional, "YYYY-MM-DD"|null
}
```

### 4.1 Coerções e defaults silenciosos — as armadilhas

Medidas em `lab-clean`:

| Entrada | Resultado | Por que importa |
|---|---|---|
| `"idade": "35"` | **200** — Pydantic coage para int | tolerante; não conte com isso para validar |
| `"plano_id": "COMPLETO"` | **200**, `plano_id: "completo"` | `.lower()` no handler |
| `"plano_id": ""` | **200 — cota `essencial`** | `payload.get("plano_id") or "essencial"`: string vazia é falsy. **Uma falha de extração vira uma cotação errada silenciosa, não um erro.** |
| `"plano_id"` ausente | 200, `essencial` | mesmo caminho |
| `"plano_id": null` | 422 Pydantic (`string_type`) | `None` é rejeitado antes; `""` não |
| `"cep": ""` | 200, `regiao: 1.0` | falsy → sem agravo |
| `"cep": "7000-000"` (sem zero à esquerda) | 200, **`regiao: 1.0`** | o prefixo lido é `"70"`, não `"07"`. **Subcotação silenciosa** de 30% — ver §5.3 |
| `"data_inicio": "2020-03-10"` (passado) | 200, com pro-rata calculado | a API **não valida** data no passado |

> **Invariante que isto impõe ao nosso lado:** `plano_id` e `cep` têm de ser validados e
> normalizados **antes** da chamada. A API não erra quando recebemos lixo nesses dois
> campos — ela cota outra coisa. É um erro que não aparece em nenhum status HTTP.

### 4.2 A data de hoje é a do servidor da cotação

`_idade_veiculo_mult` usa `dt.date.today()` **do processo da API**, não uma data no
payload. Confirmado no container: `2026-09-04`.

→ A fronteira de aceitação do veículo se move sozinha na virada do ano. Em 2026,
`veiculo_ano >= 2006` é aceito e `<= 2005` é recusado; em 2027 a linha anda para 2007.
Nenhum teste nosso pode fixar "2005 é recusado" como constante — tem de derivar de
`ano_corrente - 20`. Verificado nas duas bordas: **2006 → 200** (mult 1.45),
**2005 → 422** (recusa).

---

## 5. Regras de preço — verificadas por cálculo à mão

```
premio_mensal = round(base_mensal × mult_faixa_etaria × mult_idade_veiculo × mult_regiao, 2)
```

Um único `round` no fim; os multiplicadores não são arredondados entre si.

### 5.1 Bases

| `plano_id` | Nome | `base_mensal` | Franquia | Coberturas |
|---|---|---|---|---|
| `essencial` | Essencial | 119,90 | 4.500 | colisão, roubo, furto |
| `completo` | Completo | 209,90 | 3.000 | + terceiros, vidros |
| `premium` | Premium | 339,90 | 1.500 | + carro reserva, assistência 24h |

### 5.2 Multiplicadores

| Faixa etária | Mult | | Idade do veículo (`ano_hoje − veiculo_ano`) | Mult |
|---|---|---|---|---|
| 18–24 | 1,60 | | 0–5 | 1,00 |
| 25–29 | 1,25 | | 6–10 | 1,15 |
| 30–59 | 1,00 | | 11–20 | 1,45 |
| 60–75 | 1,40 | | ≥ 21 | **recusa** |
| ≥ 76 | **recusa** | | | |
| < 18 | **recusa** (não casa faixa) | | negativo (ano futuro) | **recusa** (não casa faixa) |

### 5.3 Região

Agravo de **1,30** quando os **dois primeiros dígitos** do CEP, após remover hífens,
estão em `07 · 08 · 21 · 26 · 59`. Sem CEP, CEP vazio ou prefixo fora da lista: 1,00.

Medido: `07XXX-XXX`, `08XXXXXX` (sem hífen), `21XXX-XXX`, `26XXX-XXX`, `59XXX-XXX` →
todos 155,87 (essencial × 1,30). `01XXX-XXX` → 119,90.

**A omissão do CEP subcota em até 30%.** E `"7000-000"` — CEP de 7 dígitos, um erro de
digitação plausível — **também** subcota, sem nenhum sinal de erro. Perguntar o CEP e
normalizá-lo para 8 dígitos é requisito de correção, não de conforto.

### 5.4 Conferência à mão

Cinco casos calculados manualmente e conferidos contra a resposta da API:

| Caso | Conta | Manual | API |
|---|---|---|---|
| premium, 22a, 2015, `08XXX-XXX` | 339,90 × 1,60 × 1,45 × 1,30 | 1.025,14 | **1.025,14** |
| essencial, 65a, 2018, `01XXX-XXX` | 119,90 × 1,40 × 1,15 × 1,00 | 193,04 | **193,04** |
| completo, 28a, 2012, `21XXX-XXX` | 209,90 × 1,25 × 1,45 × 1,30 | 494,58 | **494,58** |
| premium, 30a, 2026, sem CEP | 339,90 × 1,00 × 1,00 × 1,00 | 339,90 | **339,90** |
| essencial, 75a, 2006, `59XXX-XXX` | 119,90 × 1,40 × 1,45 × 1,30 | 316,42 | **316,42** |

O espaço inteiro de preços possíveis são **72 valores** (3 planos × 4 faixas etárias ×
3 faixas de veículo × 2 regiões), de **R$ 119,90** a **R$ 1.025,14**. Este conjunto
fechado é o gabarito de qualquer verificação de preço — e é o que prova, na §8, que
nenhuma cotação do dataset é válida.

---

## 6. Campos condicionais da resposta

### 6.1 `carencia` — **sempre presente**

```json
"carencia": {
  "coberturas": ["roubo","furto"],
  "dias": 30,
  "observacao": "Coberturas de roubo e furto so passam a valer apos a carencia, contada da data de inicio da vigencia."
}
```

Vem em **todas** as respostas 200, nos três planos (é a interseção entre as coberturas
do plano e `["roubo","furto"]`, e os três planos cobrem ambas). Não é condicional —
é condicional só na hora de escrever a mensagem, e omiti-la é vender uma cobertura que
ainda não vale. Por isso ela entra no template determinístico, não no texto do modelo.

### 6.2 `primeiro_pagamento_pro_rata` — condicional, e some se não perguntarmos

Aparece **se e somente se** `data_inicio` foi enviado **e** `data_inicio.day != 1`.

```
dias_cobrados = dias_do_mes − dia_de_inicio + 1        (inclui o dia de início)
valor         = round(premio_mensal × dias_cobrados / dias_do_mes, 2)
```

Medições (essencial, prêmio 119,90):

| `data_inicio` | Resultado |
|---|---|
| `2026-10-01` | **campo ausente** |
| `2026-10-02` | 31 dias, 30 cobrados, R$ 116,03 |
| `2026-10-31` | 31 dias, **1 cobrado**, R$ 3,87 |
| `2026-02-15` | **28 dias** (não bissexto), 14 cobrados, R$ 59,95 |
| `2028-02-29` | **29 dias** (bissexto), 1 cobrado, R$ 4,13 |
| `2020-03-10` (passado) | 31 dias, 22 cobrados, R$ 85,09 — **aceito sem reclamar** |
| omitido | campo ausente |

Dois pontos:

- **Se o agente não perguntar a data de início, este bloco nunca existe** e o lead
  recebe só a mensalidade cheia — omitindo o valor que vai ser efetivamente cobrado na
  primeira fatura. Perguntar `data_inicio` é parte da qualificação, não um extra.
- Em 30/31 dos dias do mês o campo aparece; em 1/31 (dia 1) não aparece **por
  correção**, e a mensagem tem de dizer isso ("o primeiro mês já é integral"), não
  silenciar.

---

## 7. Taxonomia de erro — o que retenta e o que não

O ponto que separa: **há quatro classes, não três.** O status 422 é ambíguo — carrega
dois erros de naturezas opostas, distinguíveis pela **forma do corpo**.

| Classe | Status | Corpo | Causa | Retenta? | Ação |
|---|---|---|---|---|---|
| **transitório** | 500 · 502 · 503 | `{"error":"upstream_unavailable","message":…}` | sorteio de instabilidade | **sim** | backoff + jitter, até 3 tentativas |
| **transitório** | — (timeout do cliente) | — | rede, ou nosso timeout menor que 8s | **sim** | idem — e revisar o timeout |
| **recusa de negócio** | 422 | `{"error":"cotacao_recusada","motivo":"…"}` | idade ou veículo fora das faixas | **não** | explicar o motivo ao lead, registrar, encaminhar |
| **defeito nosso** | 422 | `{"detail":[{"type":…,"loc":…}]}` | validação do Pydantic: campo faltando, tipo errado, fora do range | **não** | corrigir extração; não expor ao lead |
| **defeito nosso** | 400 | `{"error":"payload_invalido","detalhe":"…"}` | `KeyError`/`ValueError`/`TypeError` dentro de `cotar()` | **não** | idem |

> **Não basta olhar o status.** `422` com `error` é um "não" legítimo do negócio, que o
> lead precisa ouvir com o motivo real. `422` com `detail` é bug nosso, que o lead
> nunca deve ver. Duas mensagens opostas atrás do mesmo código HTTP.
>
> Isto refina — e corrige — a regra "422 é regra de negócio, 400 é bug nosso": um 422
> também pode ser bug nosso, e é o caso mais provável quando aparece, já que os campos
> vêm de extração em texto livre.

### 7.1 Catálogo medido, corpo exato

Todas em `lab-clean` (sem ruído de instabilidade), `2026-09-04`:

#### Recusas de negócio — 422 `cotacao_recusada`

| Requisição | Corpo |
|---|---|
| `idade: 80` | `{"error":"cotacao_recusada","motivo":"Idade acima do limite de aceitacao (75 anos)."}` |
| `idade: 17` | `{"error":"cotacao_recusada","motivo":"Idade fora das faixas aceitas."}` |
| `idade: 0` | `{"error":"cotacao_recusada","motivo":"Idade fora das faixas aceitas."}` |
| `veiculo_ano: 2000` | `{"error":"cotacao_recusada","motivo":"Veiculo com mais de 20 anos nao e aceito."}` |
| `veiculo_ano: 2005` | idem (21 anos em 2026 — borda) |
| `veiculo_ano: 2030` | `{"error":"cotacao_recusada","motivo":"Idade do veiculo fora das faixas aceitas."}` |
| `veiculo_ano: 2027` | idem (idade negativa) |
| `plano_id: "ouro"` | `{"error":"cotacao_recusada","motivo":"Plano 'ouro' inexistente. Opcoes: essencial, completo, premium"}` |

**Três dessas oito não são recusas de verdade**, apesar do rótulo:

- `veiculo_ano` no futuro (2027, 2030) — o lead não é inelegível; o dado está errado.
  Dizer "seu veículo não é aceito" a quem informou 2027 é mentir. É reperguntar.
- `plano_id` inexistente — o plano fomos **nós** que escolhemos. Nenhum lead digita
  `plano_id`. Um 422 aqui é defeito nosso disfarçado de recusa.

→ A classificação não pode parar no `error: cotacao_recusada`. Ela precisa olhar o
`motivo` e separar **recusa real** (idade ≥76, idade <18, veículo >20 anos) de
**erro de dados nosso** (ano futuro, plano inexistente). Só a primeira vira mensagem
de recusa para o lead.

#### Defeito nosso — 422 `detail` (validação do Pydantic)

| Requisição | `type` | Nota |
|---|---|---|
| sem `idade` | `missing` | |
| sem `veiculo_ano` | `missing` | |
| `{}` | `missing` × 2 | acumula todos os erros |
| `idade: 201` | `less_than_equal` | acima do `le=200` |
| `idade: -1` | `greater_than_equal` | |
| `veiculo_ano: 1949` | `greater_than_equal` | abaixo do `ge=1950` |
| `idade: "trinta"` | `int_parsing` | |
| `plano_id: null` | `string_type` | |

Corpo, na forma do FastAPI:
`{"detail":[{"type":"missing","loc":["body","idade"],"msg":"Field required","input":{…}}]}`

⚠️ `loc` e `input` **ecoam o payload enviado** — que contém idade e CEP do lead. Este
corpo não pode ir para log estruturado sem passar pelo mascaramento.

#### Defeito nosso — 400 `payload_invalido`

| Requisição | Corpo |
|---|---|
| `data_inicio: "15/07/2026"` | `{"error":"payload_invalido","detalhe":"Invalid isoformat string: '15/07/2026'"}` |
| `data_inicio: "2026-13-01"` | `{"error":"payload_invalido","detalhe":"month must be in 1..12"}` |

Na prática o 400 é o caminho de **`data_inicio` mal formatada** — é o único campo cujo
parsing acontece dentro de `cotar()`. Como a data vem de texto livre ("dia 15 do mês
que vem", "próxima segunda"), é o erro nosso mais provável, e a correção é normalizar
para ISO antes de chamar.

### 7.2 Precedência real

```
1. roteamento          →  404 / 405
2. validação Pydantic  →  422 {"detail":[...]}          ← nunca mascarada pelo sorteio
3. SORTEIO             →  500/502/503  ou  sleep(8s)     ← mascara tudo abaixo
4. regra de negócio    →  422 {"error":"cotacao_recusada"}
5. parsing interno     →  400 {"error":"payload_invalido"}
6. sucesso             →  200
```

O degrau 3 é o que produz o achado da §3.6.

### 7.3 Política que sai daí

```
timeout de leitura .......... 12 s          (> SLOW_SECONDS = 8; margem para a rede)
tentativas .................. 3             (0,8% de falha residual — §3.4)
retentáveis ................. 500 · 502 · 503 · timeout · erro de conexão
nunca retentar .............. 400 · 422 (as duas formas) · 404 · 405
backoff ..................... exponencial com jitter, base ~250 ms, teto ~2 s
                              (não há Retry-After para respeitar — §3.1)
concorrência ................ semáforo bem abaixo de 40 chamadas simultâneas (§3.3)
circuit breaker ............. abre por falhas consecutivas; meia-abertura com sonda
orçamento de pior caso ...... 3 × 12 s + backoff ≈ 40 s → excede o tempo de uma
                              resposta de chat ⇒ a cotação é um job com estado,
                              e o agente avisa antes de esperar
```

O último item é consequência aritmética, não preferência de design: o pior caso da
política de retry não cabe dentro de um turno de conversa. Ou o agente fala antes de
ter o preço, ou ele fica mudo por 40 segundos.

---

## 8. O dataset, medido contra estas regras

Medições sobre `dataset/conversations.parquet` (26.470 mensagens, 2.500 conversas).

### 8.1 30,0% dos leads são incotáveis

| Motivo | Conversas |
|---|---|
| idade ≥ 76 | 280 |
| veículo com mais de 20 anos (ano ≤ 2005 em 2026) | 531 |
| ambos | 60 |
| **pelo menos um** | **751 = 30,0%** |

O caminho de recusa é fluxo principal, não exceção. E, pela §3.6, com o default de 20%
de falha, **cerca de 150 desses 751 leads apresentam-se primeiro como um 5xx.**

### 8.2 100% das cotações do dataset são impossíveis

O gerador sorteia plano e preço de forma independente do perfil:

```python
plano = random.choice(["Essencial","Completo","Premium"])
preco = random.choice([129,159,189,219,259,299,349,389])
```

Confrontando os 8 preços usados com o conjunto fechado de 72 prêmios alcançáveis (§5.4):

| Preço no dataset | Alcançável em algum plano? |
|---|---|
| 129,90 · 159,90 · 189,90 · 219,90 · 259,90 · 299,90 · 349,90 · 389,90 | **nenhum** |

**2.500 de 2.500 cotações (100%) são matematicamente impossíveis.** Além disso:

| Verificação | Resultado |
|---|---|
| frase de cobertura idêntica em todas | 100% — sempre "Cobre colisao, roubo e furto", a do Essencial, mesmo anunciando Premium |
| mencionam carência | **0** |
| mencionam data de início / pro-rata | **0** |

→ **O dataset não pode ser few-shot do turno de cotação.** Fazê-lo ensina o modelo a
escrever um preço plausível em vez de o preço calculado, a repetir a cobertura errada
e a nunca citar a carência — os três erros mais graves possíveis nesta entrega.

Uso legítimo: tom e ritmo, taxonomia de objeções, ordem das perguntas de qualificação,
casos de teste de extração, e corpus de replay para avaliação.

### 8.3 Sujeira confirmada

| Problema | Medição | Tratamento |
|---|---|---|
| `timestamp` não monotônico com `message_index` | **2.495 / 2.500 = 99,8%** | ordenar por `message_index`, nunca por timestamp |
| CPF em texto livre | 2.500 conversas = **100%** | mascaramento obrigatório |
| CEP em texto livre | 2.500 conversas = **100%** | idem |
| telefone | 1.379 = 55,2% | idem |
| e-mail | 1.379 = 55,2% | idem |
| placa (Mercosul) | 839 = 33,6% | idem |
| mídia sem transcrição | 1.789 mensagens (6,8%): 774 documento · 550 imagem · 465 áudio | política explícita: pedir por texto ou encaminhar; nunca inventar conteúdo |

Tamanho das conversas: mín 8 · mediana 11 · máx 14 mensagens.
Desfechos: `em_negociacao` 757 · `ganho` 712 · `perdido` 538 · `sem_resposta` 493.

---

## 9. Onde a medição concorda e onde diverge dos 10 fatos

| # | Fato | Veredito | Detalhe |
|---|---|---|---|
| 1 | Lenta não é falha; 8s → 200; timeout > 8s | **confirmado** | 8,004s medido; `-m 5` mata o sucesso, `-m 12` o salva (§3.2) |
| 2 | Sorteio independente; 3 tentativas → ~0,8% | **confirmado** | 0,720 medido vs 0,729 teórico em `p=0.9` (§3.4) |
| 3 | 422 e 400 nunca retentam; 422 é negócio, 400 é bug nosso | **confirmado com correção** | ver abaixo |
| 4 | 30% incotáveis (280 idade + 531 veículo) | **confirmado** | 751/2.500 = 30,0%, 60 com os dois motivos (§8.1) |
| 5 | Cotações do dataset inválidas; 42% impossíveis | **confirmado, e mais forte** | ver abaixo |
| 6 | Pro-rata só com `data_inicio` de dia ≠ 1 | **confirmado** | tabela completa em §6.2 |
| 7 | Carência de 30 dias sempre vem na resposta | **confirmado** | presente em 100% dos 200, nos três planos (§6.1) |
| 8 | Sem CEP subcota; agravo 1,30 em `07/08/21/26/59` | **confirmado, e mais amplo** | ver abaixo |
| 9 | `timestamp` fora de ordem em 99,8% | **confirmado** | 2.495/2.500 (§8.3) |
| 10 | 100% das conversas com CPF e CEP | **confirmado** | e mais: 55% telefone, 55% e-mail, 34% placa (§8.3) |

### Divergências e refinamentos

**Fato 3 — a taxonomia tem quatro classes, não três.** "422 = negócio, 400 = bug nosso"
está incompleto em duas direções (§7):

- Um **422 do Pydantic** (`{"detail":[...]}`) é bug nosso, não regra de negócio. É a
  forma mais provável de erro nosso, porque os campos vêm de extração em texto livre.
- Dentro do **422 `cotacao_recusada`**, três dos oito casos não são recusas: veículo
  com ano futuro e `plano_id` inexistente são dados errados nossos vestidos de recusa.
  Repassá-los ao lead como "você não é aceito" é mentir para ele.

A regra prática permanece — **nada além de 5xx e timeout retenta** — mas a classificação
que decide *o que dizer ao lead* precisa ler a forma do corpo e o `motivo`, não só o
status.

**Fato 5 — não são 42%, são 100%.** A medição anterior testou se o preço caía no
*intervalo* `[base, base × 1,60 × 1,45 × 1,30]`, e 58% caíam. Mas o intervalo é
contínuo e o conjunto de prêmios possíveis é **discreto: 24 valores por plano, 72 no
total**. Testando pertinência ao conjunto — que é o teste correto — nenhum dos 8 preços
do dataset é alcançável em nenhum plano. **2.500/2.500 = 100% impossíveis.** Os 58%
"na faixa" eram coincidência de intervalo, não de cálculo. A conclusão original fica
mais forte, não mais fraca.

**Fato 8 — a subcotação por CEP tem duas causas, não uma.** Além do CEP ausente, um CEP
com **7 dígitos** (`"7000-000"`, zero à esquerda perdido — erro de digitação corriqueiro
em conversa) também zera o agravo silenciosamente, porque o prefixo lido vira `"70"`.
E `"cep": ""` é falsy e passa como ausente. Normalizar para 8 dígitos antes de chamar
é requisito de correção (§4.1, §5.3).

### Três achados que não estavam na lista

1. **A falha mascara a recusa (§3.6).** Com `FAILURE_RATE=0.20`, ~20% dos leads
   incotáveis chegam primeiro como 5xx. A primeira resposta nunca é diagnóstico
   suficiente, e o retry é o que revela a recusa.
2. **Teto de 40 chamadas lentas concorrentes (§3.3).** Acima disso o tempo dobra para
   ~16,6s e o timeout de 12–15s expira — falha artificial em massa sob carga. Exige
   limitar a concorrência do cliente.
3. **`plano_id: ""` cota `essencial` calado (§4.1).** Uma falha de extração de plano
   não vira erro: vira uma cotação errada com status 200. Junto com o CEP de 7 dígitos,
   é a segunda forma de errar o preço sem nenhum sinal HTTP.

---

## 10. Resumo operacional

O que este mapeamento fixa para o resto da entrega:

1. **Read timeout de 12s**, 3 tentativas, backoff exponencial com jitter, só em
   5xx/timeout. Sem `Retry-After` para respeitar.
2. **Concorrência limitada** contra a `/quote`, bem abaixo de 40.
3. **Quatro classes de erro**, decididas pela forma do corpo e não só pelo status;
   dentro da recusa, separar recusa real de dado nosso errado.
4. **Nunca concluir recusa a partir de um 5xx**, nem indisponibilidade sem esgotar as
   tentativas.
5. **Validar e normalizar `plano_id`, `cep` (8 dígitos) e `data_inicio` (ISO) antes de
   chamar** — os três erram sem status HTTP.
6. **Perguntar `data_inicio`** na qualificação, senão o pro-rata não existe.
7. **Carência e pro-rata saem do JSON por template**, nunca do modelo.
8. **Preço só vem do conjunto de 72 valores possíveis** — é o gabarito de qualquer
   verificação, e a prova de que o dataset não serve de few-shot de cotação.
9. **O pior caso da política (~40s) não cabe num turno** ⇒ cotação é job com estado.
10. **Cenário reproduzível = (seed, processo reiniciado, sequência exata)**, em série.
