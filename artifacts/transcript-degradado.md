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

- Conversa: `conv_6f9613cc5df5473a`
- Gerado em: 2026-09-05T05:33:01+00:00
- `[+Xs]` é o tempo desde o início da conversa; `Δ` é o tempo desde a mensagem do
  lead naquele turno — é a coluna que a política de espera governa.

## Transcript

```
[  +0.0s]           lead     Oi, queria fazer um seguro pro meu carro
[  +5.5s]  Δ +5.5s  agente   Oi! Bem-vindo à AutoSeguro 😊
                             
                             Pra te passar o valor certinho preciso de umas informações rápidas.
                             
                             Começando: qual a sua idade e o ano do carro?
[  +5.5s]           lead     e um Onix 2019
[ +10.3s]  Δ +4.8s  agente   Boa, Onix 2019 anotado.
                             
                             E a sua idade? Me passa também o CEP de onde o carro costuma dormir.
[ +10.3s]           lead     tenho 28 anos, cep [CEP]
[ +16.0s]  Δ +5.7s  agente   Perfeito, tudo anotado.
                             
                             Faltam só duas coisas:
                             
                             1) Quando você quer que o seguro comece a valer?
                             2) Qual plano te interessa?
                             - **Essencial**: colisão, roubo e furto
                             - **Completo**: tudo do Essencial + terceiros e vidros
                             - **Premium**: tudo do Completo + carro reserva e assistência 24h (é o de menor franquia)
[ +16.0s]           lead     qual a diferença dos planos?
[ +23.9s]  Δ +7.9s  agente   Boa pergunta! Vou pelo que cada um cobre:
                             
                             **Essencial** — o básico bem coberto: colisão, roubo e furto. Protege o seu carro, mas não cobre dano que você cause em terceiros nem vidros.
                             
                             **Completo** — tudo do Essencial + **danos a terceiros** (se você bater em outro carro ou machucar alguém) e **vidros** (para-brisa, vidros laterais, retrovisores, faróis). É o mais escolhido, porque para-brisa trincado é bem comum.
                             
                             **Premium** — tudo do Completo + **carro reserva** (você não fica a pé enquanto o seu está na oficina) e **assistência 24h** (guincho, pane seca, chaveiro, bateria). É também o de **menor franquia** dos três — franquia é aquela parte que você paga do próprio bolso quando aciona o conserto.
                             
                             Resumindo: quanto mais completo o plano, menor a franquia e mais situação coberta.
                             
                             Qual faz mais sentido pra você? E me diz também a data que você quer que comece a valer.
[ +23.9s]           lead     quero o completo mesmo
[ +27.8s]  Δ +3.9s  agente   Fechado, Completo então.
                             
                             Só falta a data: quando você quer que a cobertura comece a valer?
[ +27.8s]           lead     pode começar dia 17 de outubro
[ +33.8s]  Δ +6.0s  sistema  Tô buscando o valor no sistema e ele tá lento agora. Já te trago, tá?
[ +47.8s]  Δ+20.0s  sistema  Ainda tô aqui, viu? O sistema não me devolveu ainda. Assim que sair eu te mando.
[ +68.0s]  Δ+40.2s  sistema  Não consegui confirmar o valor agora: o sistema de cotação não respondeu. Não vou te passar um número sem ter certeza dele.
                             
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
| `q_2941687c1b77401a` | `failed` | — | `timeout` | 36099 ms |

#### Tentativas de `q_2941687c1b77401a`

| # | HTTP | outcome | latência |
|---|---|---|---|
| 1 | — (sem resposta) | `timeout` | 12021 ms |
| 2 | — (sem resposta) | `timeout` | 12035 ms |
| 3 | — (sem resposta) | `timeout` | 12043 ms |

### Handoff

- gatilho `cotacao_indisponivel`, disparado por **regra**
  - motivo: a cotação não respondeu depois de esgotadas as tentativas
