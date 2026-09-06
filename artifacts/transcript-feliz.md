# Caminho feliz — do «oi» à cotação

> Gerado por `scripts/transcript.py`. **Entregável nº 4** do enunciado: log de uma
> execução completa, do início ao fim.
>
> **Modelo:** `anthropic:claude-sonnet-5`. O nome fica no artefato porque a conversa é produto DELE:
> um transcript sem o modelo nomeado convida a ser comparado com outro gerado por um
> modelo diferente, que é exatamente o erro que este repositório se obriga a não
> cometer com as medições de cache e custo.

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

- Conversa: `conv_91079b4c026c462f`
- Gerado em: 2026-09-06T05:11:57+00:00
- `[+Xs]` é o tempo desde o início da conversa; `Δ` é o tempo desde a mensagem do
  lead naquele turno — é a coluna que a política de espera governa.

## Transcript

```
[  +0.0s]           lead     Oi, queria fazer um seguro pro meu carro
[  +5.5s]  Δ +5.5s  agente   Oi! Bora te ajudar. Me passa dois dados pra começar: a idade de quem dirige o carro na maior parte do tempo, e o ano do veículo?
[  +5.6s]           lead     e um Onix 2019
[  +8.7s]  Δ +3.1s  agente   Beleza, Onix 2019 anotado. E a idade de quem dirige mais o carro?
[  +8.7s]           lead     tenho 28 anos, cep [CEP]
[ +12.1s]  Δ +3.4s  agente   Show, já tenho idade, ano do carro e CEP. Só falta: quando você quer que a cobertura comece, e qual plano prefere — Essencial, Completo ou Premium?
[ +12.1s]           lead     qual a diferença dos planos?
[ +14.6s]  Δ +2.5s  agente   O Essencial cobre colisão, roubo e furto. O Completo tem tudo isso mais terceiros e vidros. O Premium cobre tudo do Completo, mais carro reserva e assistência 24h — e é o que tem a menor franquia entre os três (o Essencial tem a maior).
                             
                             Qual faz mais sentido pra você? E já aproveito e pergunto: quando quer que a cobertura comece?
[ +14.7s]           lead     quero o completo mesmo
[ +17.5s]  Δ +2.9s  agente   Fechado, Completo anotado. Só falta uma coisa: quando você quer que a cobertura comece?
[ +17.6s]           lead     pode começar dia 17 de outubro
[ +20.0s]  Δ +2.5s  sistema  Fechei sua cotação 👇
                             
                             *Completo — R$ 392,25/mês*
                             Cobre colisão, roubo, furto, terceiros e vidros.
                             Franquia de R$ 3.000.
                             
                             Começando dia 17/10, o primeiro boleto sai proporcional: *R$ 189,80* (15 dos 31 dias).
                             Do mês seguinte em diante, R$ 392,25 cheio.
                             
                             ⚠️ Roubo e furto começam a valer 30 dias depois do início da vigência.
                             
                             Quer seguir com a contratação?
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
| 11 | `sistema` | `text` | `sent` | `q_cdb9585b44734317` |

### Cotações

| quote_id | status | prêmio | outcome | latência |
|---|---|---|---|---|
| `q_cdb9585b44734317` | `ok` | R$ 392.25 | `—` | 10 ms |

#### Tentativas de `q_cdb9585b44734317`

| # | HTTP | outcome | latência |
|---|---|---|---|
| 1 | 200 | `ok` | 10 ms |

### Handoff

Nenhum. O agente resolveu sozinho — que é o desfecho pretendido deste cenário.
