# Caminho feliz — do «oi» à cotação

> Gerado por `scripts/transcript.py`. **Entregável nº 4** do enunciado: log de uma
> execução completa, do início ao fim.

## Como reproduzir

```bash
QUOTE_FAILURE_RATE=0 QUOTE_SLOW_RATE=0 docker compose up -d --build --wait
docker compose exec -T app python scripts/transcript.py --cenario feliz \
  > artifacts/transcript-feliz.md
```

O redirecionamento é do lado de fora de propósito: o contêiner é efêmero e montar um
volume só para isto acrescentaria uma linha ao `docker-compose.yml` que não serve ao
produto. O artefato nasce onde vai viver.

O `docker compose up` acima **reinicia o processo da `/quote`** com essas variáveis, e
é isso que torna o cenário reproduzível: o RNG do legado é um fluxo global e contínuo
do processo, então a tripla que define um cenário é *(seed, processo reiniciado,
sequência exata de requisições)* — a seed sozinha não basta.

A `/quote` responde na primeira tentativa. É o cenário que prova o critério nº 1: o agente atende de ponta a ponta e entrega o preço.

- Conversa: `conv_392991146ef64013`
- Gerado em: 2026-09-05T03:53:08+00:00
- `[+Xs]` é o tempo desde o início da conversa; `Δ` é o tempo desde a mensagem do
  lead naquele turno — é a coluna que a política de espera governa.

## Transcript

```
[  +0.0s]           lead     Oi, queria fazer um seguro pro meu carro
[  +5.1s]  Δ +5.1s  agente   Oi! Que bom, vamos resolver isso rapidinho.
                             
                             Pra começar: qual a sua idade e o ano do carro?
[  +5.1s]           lead     e um Onix 2019
[  +8.6s]  Δ +3.5s  agente   Boa, Onix 2019 anotado.
                             
                             E a sua idade? Só me confirma também o CEP de onde o carro dorme.
[  +8.6s]           lead     tenho 28 anos, cep [CEP]
[ +14.1s]  Δ +5.4s  agente   Perfeito, tudo anotado.
                             
                             Faltam só duas coisas:
                             
                             1. Quando você quer que a cobertura comece?
                             2. Qual plano te interessa mais?
                             - **Essencial**: colisão, roubo e furto
                             - **Completo**: tudo do Essencial + terceiros e vidros
                             - **Premium**: tudo do Completo + carro reserva e assistência 24h (é o de menor franquia)
[ +14.1s]           lead     qual a diferença dos planos?
[ +21.5s]  Δ +7.5s  agente   Boa pergunta! A diferença tá no que cada um cobre:
                             
                             **Essencial** — o básico bem feito: colisão, roubo e furto. Se bater o carro ou levarem ele, tá coberto. Mas dano em terceiro e vidro (parabrisa, por exemplo) ficam por sua conta.
                             
                             **Completo** — tudo do Essencial + **terceiros** (se você bater no carro de alguém, a gente cobre o prejuízo dele) e **vidros** (parabrisa, vidro lateral, retrovisor, farol).
                             
                             **Premium** — tudo do Completo + **carro reserva** (fica sem carro enquanto o seu tá na oficina? a gente te dá um) e **assistência 24h** (guincho, chaveiro, pane seca, bateria a qualquer hora).
                             
                             Outra diferença importante: a **franquia**, que é a parte que você paga quando aciona o seguro num sinistro. O Premium tem a menor, o Essencial a maior. Os valores exatos só saem na cotação.
                             
                             Pra um Onix 2019 no dia a dia, o Completo costuma ser o mais procurado, principalmente pela cobertura de terceiros — é o tipo de prejuízo que pesa mais.
                             
                             Qual faz mais sentido pra você? E quando quer que comece a valer?
[ +21.5s]           lead     quero o completo mesmo
[ +25.0s]  Δ +3.5s  agente   Fechado, Completo então!
                             
                             Só falta uma coisa: quando você quer que a cobertura comece? Pode ser já a partir de amanhã, ou uma data que você preferir.
[ +25.1s]           lead     pode começar dia 17 de outubro
[ +28.7s]  Δ +3.6s  sistema  Fechei sua cotação 👇
                             
                             *Completo — R$ 392,25/mês*
                             Cobre colisão, roubo, furto, terceiros e vidros.
                             Franquia de R$ 3.000.
                             
                             Começando dia 17/10, o primeiro boleto sai proporcional: *R$ 189,80* (15 dos 31 dias).
                             Do mês seguinte em diante, R$ 392,25 cheio.
                             
                             ⚠️ Roubo e furto começam a valer 30 dias depois do início da vigência.
                             
                             Quer que eu siga com a emissão?
```

## O que ficou gravado

**Estado final da conversa:** `cotado`

### Mensagens

| index | autor | tipo | status | quote_id |
|---|---|---|---|---|
| 0 | `lead` | `text` | `received` | — |
| 1 | `agente` | `text` | `sent` | — |
| 2 | `lead` | `text` | `received` | — |
| 3 | `agente` | `text` | `sent` | — |
| 4 | `lead` | `text` | `received` | — |
| 5 | `agente` | `text` | `sent` | — |
| 6 | `lead` | `text` | `received` | — |
| 7 | `agente` | `text` | `sent` | — |
| 8 | `lead` | `text` | `received` | — |
| 9 | `agente` | `text` | `sent` | — |
| 10 | `lead` | `text` | `received` | — |
| 11 | `sistema` | `text` | `sent` | `q_4866c659fe9d49ee` |

### Cotações

| quote_id | status | prêmio | outcome | latência |
|---|---|---|---|---|
| `q_4866c659fe9d49ee` | `ok` | R$ 392.25 | `—` | 11 ms |

#### Tentativas de `q_4866c659fe9d49ee`

| # | HTTP | outcome | latência |
|---|---|---|---|
| 1 | 200 | `ok` | 11 ms |

### Handoff

Nenhum. O agente resolveu sozinho — que é o desfecho pretendido deste cenário.
