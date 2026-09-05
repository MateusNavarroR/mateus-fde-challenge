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

- Conversa: `conv_5d29395798b64a6f`
- Gerado em: 2026-09-05T05:33:38+00:00
- `[+Xs]` é o tempo desde o início da conversa; `Δ` é o tempo desde a mensagem do
  lead naquele turno — é a coluna que a política de espera governa.

## Transcript

```
[  +0.0s]           lead     Oi, queria fazer um seguro pro meu carro
[  +3.0s]  Δ +3.0s  agente   Oi! Bora resolver isso rapidinho.
                             
                             Me passa duas coisas pra começar: sua idade (ou do condutor principal) e o ano do carro?
[  +3.0s]           lead     e um Onix 2019
[  +6.5s]  Δ +3.5s  agente   Boa, Onix 2019 anotado.
                             
                             Falta a sua idade (ou do condutor principal) e o CEP de onde o carro dorme.
[  +6.5s]           lead     tenho 28 anos, cep [CEP]
[ +12.1s]  Δ +5.6s  agente   Show, tudo anotado.
                             
                             Agora só faltam duas coisas:
                             
                             1. **Quando você quer que a cobertura comece?** (pode ser já, ou uma data específica)
                             2. **Qual plano te interessa?**
                                - **Essencial**: colisão, roubo e furto
                                - **Completo**: tudo do Essencial + terceiros e vidros
                                - **Premium**: tudo do Completo + carro reserva e assistência 24h (é o de menor franquia)
[ +12.1s]           lead     qual a diferença dos planos?
[ +18.6s]  Δ +6.5s  agente   Diferença é o quanto cada um cobre:
                             
                             **Essencial** — o básico: colisão, roubo e furto. Protege o seu carro, e só ele.
                             
                             **Completo** — tudo isso + **terceiros** (se você bater em alguém, cobre o prejuízo do outro) e **vidros** (para-brisa, vidros laterais, retrovisores).
                             
                             **Premium** — tudo do Completo + **carro reserva** (você não fica a pé enquanto o seu tá na oficina) e **assistência 24h** (guincho, pane, chave trancada).
                             
                             Sobre franquia: é o valor que fica por sua conta quando o carro vai pra oficina num sinistro. O Premium tem a menor franquia e o Essencial a maior — mas os valores exatos só saem na cotação.
                             
                             Na prática: o **Completo** é o que a maioria escolhe, porque bater em terceiro é o que dá mais dor de cabeça. O **Premium** vale se você usa o carro todo dia e não pode ficar sem.
                             
                             Qual faz mais sentido pra você? E quando quer começar?
[ +18.6s]           lead     quero o completo mesmo
[ +22.6s]  Δ +4.0s  agente   Fechou, Completo anotado.
                             
                             Só falta uma coisa: quando você quer que a cobertura comece? Pode ser já a partir de hoje, ou me diz a data que preferir.
[ +22.6s]           lead     pode começar dia 17 de outubro
[ +29.5s]  Δ +6.8s  sistema  Fechei sua cotação 👇
                             
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
| 11 | `sistema` | `text` | `sent` | `q_90c4c570bf2645eb` |

### Cotações

| quote_id | status | prêmio | outcome | latência |
|---|---|---|---|---|
| `q_90c4c570bf2645eb` | `ok` | R$ 392.25 | `—` | 11 ms |

#### Tentativas de `q_90c4c570bf2645eb`

| # | HTTP | outcome | latência |
|---|---|---|---|
| 1 | 200 | `ok` | 11 ms |

### Handoff

Nenhum. O agente resolveu sozinho — que é o desfecho pretendido deste cenário.
