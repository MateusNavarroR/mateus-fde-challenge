# Caminho degradado — a `/quote` não responde

> Gerado por `scripts/transcript.py`. **Entregável nº 4** do enunciado: log de uma
> execução completa, do início ao fim.

## Como reproduzir

```bash
QUOTE_SLOW_RATE=1 QUOTE_SLOW_SECONDS=13 QUOTE_FAILURE_RATE=0 docker compose up -d --build --wait
docker compose exec -T app python scripts/transcript.py --cenario degradado \
  > artifacts/transcript-degradado.md
```

O redirecionamento é do lado de fora de propósito: o contêiner é efêmero e montar um
volume só para isto acrescentaria uma linha ao `docker-compose.yml` que não serve ao
produto. O artefato nasce onde vai viver.

O `docker compose up` acima **reinicia o processo da `/quote`** com essas variáveis, e
é isso que torna o cenário reproduzível: o RNG do legado é um fluxo global e contínuo
do processo, então a tripla que define um cenário é *(seed, processo reiniciado,
sequência exata de requisições)* — a seed sozinha não basta.

`SLOW_SECONDS=13` é **maior** que o nosso read timeout de 12 s, então as três tentativas estouram e o job termina `failed`. É o pior caso da política, forçado de propósito: no tráfego real ele acontece em ~0,8 % dos jobs, e esperar por ele para gerar o artefato seria esperar por acaso.

**Como ler os Δ.** O aviso tem limiar de 6 s e o reforço de 20 s, contados da chegada da mensagem do lead. O aviso costuma aparecer um pouco depois dos 6 s, e a aritmética é esta: quem agenda os dois timers é a **tool de cotação**, e o modelo leva alguns segundos para chegar até ela. Quando o job começa depois dos 6 s, o prazo já venceu e o aviso sai na hora — é por isso que ele acompanha o início do job, e não o relógio.

O disparo é de dentro da tool de propósito: um watchdog na camada de conversa dispararia **durante** a geração do modelo e produziria «só um instante» seguido da resposta 0,2 s depois. Para a demora que não é da cotação existe um segundo relógio, aos 10 s, na camada de conversa.

- Conversa: `conv_cc22b8da36ec44c0`
- Gerado em: 2026-09-05T03:54:27+00:00
- `[+Xs]` é o tempo desde o início da conversa; `Δ` é o tempo desde a mensagem do
  lead naquele turno — é a coluna que a política de espera governa.

## Transcript

```
[  +0.0s]           lead     Oi, queria fazer um seguro pro meu carro
[  +2.7s]  Δ +2.7s  agente   Opa, tudo bem? Posso te ajudar sim.
                             
                             Pra começar, me passa a idade do condutor principal e o ano do carro?
[  +2.7s]           lead     e um Onix 2019
[  +5.8s]  Δ +3.1s  agente   Boa, Onix 2019 anotado.
                             
                             E a idade do condutor principal, qual é?
[  +5.8s]           lead     tenho 28 anos, cep [CEP]
[ +10.1s]  Δ +4.3s  agente   Show, 28 anos e CEP [CEP] registrados.
                             
                             Falta pouco: a partir de quando você quer que o seguro comece? E qual plano te interessa?
                             
                             - **Essencial**: colisão, roubo e furto
                             - **Completo**: tudo do Essencial + terceiros e vidros
                             - **Premium**: tudo do Completo + carro reserva e assistência 24h (é o de menor franquia)
[ +10.1s]           lead     qual a diferença dos planos?
[ +17.4s]  Δ +7.3s  agente   A diferença é o que cada um cobre:
                             
                             **Essencial** — o básico: colisão, roubo e furto. Se bater ou levarem o carro, tá coberto. Mas se você bater em outro carro, o prejuízo do outro é por sua conta.
                             
                             **Completo** — tudo do Essencial + danos a terceiros (o carro do outro) e vidros (para-brisa, vidro lateral, farol). É o mais escolhido, porque parabrisa trincado é o que mais acontece no dia a dia.
                             
                             **Premium** — tudo do Completo + carro reserva enquanto o seu tá na oficina e assistência 24h (guincho, chaveiro, pane seca). É também o de menor franquia — franquia é a parte que você paga do conserto quando aciona o seguro. Quanto menor, menos sai do seu bolso na hora do sinistro.
                             
                             Resumindo: o Essencial protege o seu carro, o Completo protege você de terceiros também, e o Premium te dá o suporte pra não ficar a pé.
                             
                             Qual faz mais sentido pro seu uso? E pra quando você quer começar?
[ +17.4s]           lead     quero o completo mesmo
[ +20.7s]  Δ +3.3s  agente   Fechado, Completo anotado.
                             
                             Só falta uma coisa: a partir de quando você quer que a cobertura comece? Pode ser já a partir de amanhã, ou você prefere outra data?
[ +20.7s]           lead     pode começar dia 17 de outubro
[ +26.7s]  Δ +6.0s  sistema  Tô buscando o valor no sistema e ele tá lento agora. Já te trago, tá?
[ +40.7s]  Δ+20.0s  sistema  Ainda tô aqui, viu? O sistema não me devolveu ainda. Assim que sair eu te mando.
[ +61.1s]  Δ+40.4s  sistema  Não consegui confirmar o valor agora: o sistema de cotação não respondeu. Não vou te passar um número sem ter certeza dele.
                             
                             Já passei sua conversa pra um atendente da equipe, com tudo que a gente conversou. A equipe assume daqui.
```

## O que ficou gravado

**Estado final da conversa:** `encaminhado`

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
| 11 | `sistema` | `text` | `sent` | — |
| 12 | `sistema` | `text` | `sent` | — |
| 13 | `sistema` | `text` | `sent` | — |

### Cotações

| quote_id | status | prêmio | outcome | latência |
|---|---|---|---|---|
| `q_d1baf4ffa4d5479f` | `failed` | — | `timeout` | 36083 ms |

#### Tentativas de `q_d1baf4ffa4d5479f`

| # | HTTP | outcome | latência |
|---|---|---|---|
| 1 | — (sem resposta) | `timeout` | 12022 ms |
| 2 | — (sem resposta) | `timeout` | 12042 ms |
| 3 | — (sem resposta) | `timeout` | 12019 ms |

### Handoff

- gatilho `cotacao_indisponivel`, disparado por **regra**
  - motivo: a cotação não respondeu depois de esgotadas as tentativas
