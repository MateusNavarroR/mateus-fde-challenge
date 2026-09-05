# Política de resiliência da `/quote`

> Esta é a **parte técnica**: timeout, retry, backoff, breaker e taxonomia. O que o
> agente **diz ao lead** enquanto isso acontece é decisão aberta nº2
> (`docs/DECISOES-FECHADAS.md`) — e é ela que consome esta política, não o contrário.
>
> Todo número abaixo é derivado de uma medição em `docs/API-COTACAO.md`. Onde há
> escolha, o trade-off está declarado.

---

## 1. Os parâmetros, e de onde cada um vem

| Parâmetro | Valor | Derivado de |
|---|---|---|
| `connect_timeout` | 2 s | rede local; o legado responde em ~2 ms quando responde |
| `read_timeout` | **12 s** | a chamada lenta dorme **8,004 s** e devolve **200 correto** (§3.2) |
| `max_attempts` | **3** | 0,20³ = 0,8 % de falha residual; a 4ª compra 0,64 pp (§3.4) |
| `backoff_base` | 250 ms | não há `Retry-After` para respeitar (§3.1) |
| `backoff_fator` | 2,0 | 250 ms → 500 ms → 1 s |
| `backoff_teto` | 2 s | mantém o pior caso dentro do orçamento abaixo |
| `jitter` | full jitter | `sleep(random(0, min(teto, base·2ⁿ)))` |
| `max_concorrencia` | **8** | o legado serializa acima de 40 lentas simultâneas (§3.3) |
| `breaker_limiar` | 5 falhas consecutivas | ver §4 |
| `breaker_cooldown` | 20 s | ver §4 |

### 1.1 Por que 12 s e não 9 s

O `read_timeout` tem que ser maior que `QUOTE_SLOW_SECONDS`, que é 8 s no
`docker-compose` do desafio. Medido, na mesma instância e mesma requisição:

| Timeout | Resultado |
|---|---|
| 5 s | timeout — **um 200 correto destruído pelo cliente** |
| 12 s | **200 em 8,00 s** |

Um timeout menor que 8 s não "protege" nada: converte 10 % de sucessos em falhas, e o
retry as reproduz, porque o próximo sorteio pode cair de novo na faixa lenta. A margem
de 4 s existe porque `SLOW_SECONDS` é configurável e porque a rede não é instantânea.

**Custo assumido:** quando a falha é de rede de verdade, esperamos 12 s para descobrir.
É o preço de não destruir os 10 % de chamadas lentas legítimas, e é o lado certo do
trade-off — a lentidão é 10 % do tráfego e a queda de rede é rara.

### 1.2 Por que 3 tentativas

Independência entre tentativas confirmada empiricamente (§3.4: 0,720 medido contra
0,729 teórico). Com `FAILURE_RATE=0.20`:

| Tentativas | Falha residual | Ganho da última |
|---|---|---|
| 1 | 20 % | — |
| 2 | 4 % | 16 pp |
| 3 | **0,8 %** | 3,2 pp |
| 4 | 0,16 % | 0,64 pp |

A 4ª tentativa compra 0,64 pp e pode custar mais 12 s. O critério que fecha a conta não
é a taxa: é o orçamento de tempo (§3).

### 1.3 Por que limitar a concorrência em 8

O handler da `/quote` é síncrono, então o FastAPI o roda no threadpool do AnyIO, cujo
limite é 40. Com 60 chamadas lentas simultâneas, 40 terminaram em ~8,8 s e **20
enfileiraram para ~16,6 s** — acima do nosso `read_timeout` de 12 s.

Ou seja: sem limitar a concorrência, o dimensionamento do timeout deixa de valer
exatamente quando há mais leads, e o modo de falha é o pior possível — falha
artificial em massa sob carga.

Um semáforo de 8 mantém margem larga mesmo com várias conversas cotando ao mesmo
tempo. Esperar no semáforo **não** conta contra o `read_timeout` (é fila nossa, não
latência do legado), mas conta contra o orçamento do turno — por isso a espera no
semáforo é registrada separadamente na tentativa.

---

## 2. O que retenta, e o que nunca retenta

A decisão **não** sai do status HTTP sozinho. O 422 carrega dois erros de naturezas
opostas, distinguíveis pela forma do corpo, e dentro da recusa há casos que são bug
nosso disfarçado. Cinco desfechos, porque são cinco ações distintas:

| Desfecho | Reconhecido por | Retenta? | O que acontece |
|---|---|---|---|
| `ok` | 200 | — | renderiza por template e responde |
| `transient` | 500 · 502 · 503 | **sim** | backoff + jitter |
| `timeout` | sem resposta em 12 s, erro de conexão | **sim** | backoff + jitter |
| `refused` | 422 `{"error":"cotacao_recusada"}` com motivo de recusa real | **não** | o lead ouve o motivo, texto de um mapa fixo nosso |
| `bad_request` | 400 · 422 `{"detail":[…]}` · 422 "recusa" que é dado nosso errado · 404 · 405 | **não** | bug nosso; o lead nunca vê o erro |

Motivos que contam como recusa real — os únicos três:

- `Idade acima do limite de aceitacao (75 anos).`
- `Idade fora das faixas aceitas.` (idade < 18)
- `Veiculo com mais de 20 anos nao e aceito.`

Motivos que a API chama de recusa mas **são `bad_request`**:

- `Idade do veiculo fora das faixas aceitas.` — o lead informou um ano futuro. Ele não
  é inelegível; o dado está errado. Reperguntar.
- `Plano 'X' inexistente.` — nenhum lead digita `plano_id`. Fomos nós que escolhemos.

E um motivo desconhecido cai em `bad_request` de propósito: **na dúvida, não afirmamos
ao lead que ele foi recusado.**

### 2.1 A regra que vem do sorteio acontecer antes da validação

O sorteio de falha roda **antes** da regra de negócio. Medido: um lead de 80 anos, com
`FAILURE_RATE=1.0`, devolveu `502 503 502 500 502` — nunca 422.

Duas proibições saem daí, e elas valem tanto para o código quanto para o texto:

> **Nunca concluir recusa a partir de um 5xx.**
> **Nunca concluir indisponibilidade sem esgotar as tentativas.**

Com o default de 20 %, cerca de um em cada cinco leads incotáveis apresenta-se primeiro
como indisponibilidade — e leads incotáveis são 30 % do tráfego. É o retry que revela a
recusa: o mesmo mecanismo que existe para a resiliência é o que produz o diagnóstico
correto do caminho de recusa.

---

## 3. Orçamento de tempo — e por que a cotação é um job

Pior caso de um job, sem contar fila de semáforo:

```
tentativa 1: 12,0 s (timeout)  + backoff ≤ 0,25 s
tentativa 2: 12,0 s (timeout)  + backoff ≤ 0,50 s
tentativa 3: 12,0 s (timeout)
                                 ─────────
                                  ~36,8 s
```

Caso lento porém bem-sucedido, que é o comum: `8,0 s` numa única tentativa.

**~37 s não cabe dentro de um turno de conversa.** Ninguém espera meio minuto por uma
resposta no WhatsApp sem achar que o atendimento caiu. Isso não é preferência de
design; é aritmética, e ela força a arquitetura:

> A cotação é um **job com estado** (`pending → ok | refused | failed`), e o agente
> **fala antes de ter o preço**.

O que ele diz e a partir de qual tentativa ele diz é a decisão aberta nº2. A política
técnica só garante que o job existe, que ele tem id desde a primeira tentativa, e que
o resultado chega como mensagem nova quando chegar.

---

## 4. Circuit breaker

Três estados, com a transição por sonda:

```
             5 falhas consecutivas
   fechado ───────────────────────► aberto
      ▲                               │ cooldown 20 s
      │                               ▼
      └──── 1 sonda ok ────────  meia-abertura
                                      │ sonda falha
                                      └──────────► aberto (cooldown reinicia)
```

| Parâmetro | Valor | Por quê |
|---|---|---|
| limiar | 5 falhas **consecutivas** | Com `p=0.20`, 5 seguidas por acaso tem probabilidade 0,032 % — o breaker praticamente não abre por azar. Com `p=1.0` (a suíte degradada), abre depois de dois jobs. |
| cooldown | 20 s | maior que o pior caso de um job (~37 s seria ocioso demais; 20 s dá uma sonda por conversa nova sem martelar o legado) |
| meia-abertura | 1 chamada real | não uma requisição sintética: a sonda é a próxima cotação de verdade, que assim não é desperdiçada |

**Só `transient` e `timeout` contam para o breaker.** Uma recusa de negócio é a API
funcionando perfeitamente; contá-la abriria o circuito num dia de muitos leads idosos.
Um `bad_request` é defeito nosso; contá-lo esconderia o bug atrás de um "legado fora".

**Com o breaker aberto, o job nasce `failed` sem nenhuma tentativa** e com
`circuito_aberto = true`. A tela de status precisa distinguir isso de "tentamos 3 vezes
e falhou" — são situações diferentes para quem opera, e a coluna existe para isso.

O breaker é **global por processo**, não por conversa: a instabilidade é do legado, e
descobri-la numa conversa deve poupar as outras.

---

## 5. Idempotência e efeito colateral

`POST /quote` é função pura: sem estado, sem escrita, sem cobrança. Retentar é seguro
por construção, e não precisamos de chave de idempotência do lado deles.

Do nosso lado, cada tentativa vira uma linha em `quote_attempts`, com `attempt`,
`http_status`, `latency_ms` e `outcome`. **A tentativa é gravada mesmo quando o job
inteiro falha** — é justamente o caso em que a linha do tempo importa.

---

## 6. Observabilidade mínima (sem depender do profile opcional)

Por tentativa, gravado no banco: `attempt`, `http_status`, `latency_ms`, `outcome`,
`detalhe` (mascarado), `quote_id`, `conversation_id`.

Derivado em `/api/quote-health`, sobre as últimas N: taxa de sucesso, p50, p95,
contagem por `outcome`, estado do breaker.

O p95 vai mostrar ~8 s sempre que houver chamada lenta na janela. **Isso é o
comportamento correto sendo exibido, não um problema** — a tela de status precisa
deixar isso explícito, senão parece defeito.

⚠️ Nada de PII em log ou trace. O corpo do 422 de validação **ecoa o payload enviado**
(idade, CEP do lead); por isso `classificar_erro` não propaga o `detalhe` desse caso, e
todo texto que chega ao banco passa antes pelo mascaramento.

---

## 7. Como isto é provado

| Suíte | Configuração | Prova |
|---|---|---|
| caminho feliz | `FAILURE_RATE=0` | cota, renderiza, cita carência e pro-rata |
| degradado | `FAILURE_RATE=1.0` | 3 tentativas, nenhum preço inventado, breaker abre, handoff |
| lentidão | `SLOW_RATE=1.0`, `SLOW_SECONDS=8` | 1 tentativa, ~8 s, **a cotação sai** |
| timeout curto | `SLOW_RATE=1.0`, `read_timeout=5` | teste de regressão: prova que 5 s destrói o sucesso — o motivo de 12 s fica no código, não só na prosa |
| recusa | idade 80 · veículo com >20 anos | **uma** tentativa, sem retry, motivo real ao lead |
| `bad_request` | `data_inicio` malformada · plano inexistente | sem retry, sem mensagem de recusa ao lead |
| recusa mascarada | `FAILURE_RATE=0.20`, seed fixa, idade 80 | o 5xx inicial **não** vira "você foi recusado" |
| breaker | `FAILURE_RATE=1.0`, sequencial | abre na 5ª falha; job seguinte nasce `failed` sem tentativa |
| concorrência | 20 jobs simultâneos, `SLOW_RATE=1.0` | nenhuma tentativa acima de 12 s — o semáforo segurou |

Todas as suítes que dependem de `QUOTE_SEED` rodam **em série e com restart do
container antes**: o RNG é um fluxo global do processo, e um cenário reproduzível é a
tripla (seed, processo reiniciado, sequência exata de requisições).
