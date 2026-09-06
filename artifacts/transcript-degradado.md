# Caminho degradado — a `/quote` não responde

> Gerado por `scripts/transcript.py`. **Entregável nº 4** do enunciado: log de uma
> execução completa, do início ao fim.
>
> **Modelo:** `anthropic:claude-sonnet-5`. O nome fica no artefato porque a conversa é produto DELE:
> um transcript sem o modelo nomeado convida a ser comparado com outro gerado por um
> modelo diferente, que é exatamente o erro que este repositório se obriga a não
> cometer com as medições de cache e custo.

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

- Conversa: `conv_b9fea658e8004af7`
- Gerado em: 2026-09-06T05:13:16+00:00
- `[+Xs]` é o tempo desde o início da conversa; `Δ` é o tempo desde a mensagem do
  lead naquele turno — é a coluna que a política de espera governa.

## Transcript

```
[  +0.0s]           lead     Oi, queria fazer um seguro pro meu carro
[  +4.4s]  Δ +4.4s  agente   Oi! Bora te ajudar. Me passa duas coisas: qual sua idade e o ano do carro?
[  +4.5s]           lead     e um Onix 2019
[  +8.3s]  Δ +3.7s  agente   Beleza, Onix 2019 anotado. Agora me diz sua idade e o CEP de onde o carro dorme?Me passa sua idade e o CEP de onde o carro fica à noite?
[  +8.5s]           lead     tenho 28 anos, cep [CEP]
[ +12.0s]  Δ +3.6s  agente   Show, já tenho idade, ano do carro e CEP. Agora só falta saber: quando você quer que a cobertura comece, e qual plano prefere — essencial, completo ou premium?
[ +12.0s]           lead     qual a diferença dos planos?
[ +14.8s]  Δ +2.8s  agente   Claro! Olha a diferença:
                             
                             - **Essencial**: cobre colisão, roubo e furto.
                             - **Completo**: tudo do essencial mais terceiros e vidros.
                             - **Premium**: tudo do completo mais carro reserva e assistência 24h — e tem a menor franquia dos três (o essencial tem a maior).
                             
                             Qual faz mais sentido pra você? E quando quer que a cobertura comece?
[ +14.8s]           lead     quero o completo mesmo
[ +17.8s]  Δ +3.0s  agente   Fechado, plano completo. E quando você quer que a cobertura comece?Só falta a data de início da cobertura — pode ser hoje mesmo ou alguma data específica?
[ +17.8s]           lead     pode começar dia 17 de outubro
[ +23.8s]  Δ +6.0s  sistema  Tô buscando o valor no sistema e ele tá lento agora. Já te trago, tá?
[ +37.8s]  Δ+20.0s  sistema  Ainda tô aqui, viu? O sistema não me devolveu ainda. Assim que sair eu te mando.
[ +56.8s]  Δ+39.0s  sistema  Não consegui confirmar o valor agora: o sistema de cotação não respondeu. Não vou te passar um número sem ter certeza dele.
                             
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
| `q_3a7cde745fca4855` | `failed` | — | `timeout` | 36086 ms |

#### Tentativas de `q_3a7cde745fca4855`

| # | HTTP | outcome | latência |
|---|---|---|---|
| 1 | — (sem resposta) | `timeout` | 12020 ms |
| 2 | — (sem resposta) | `timeout` | 12022 ms |
| 3 | — (sem resposta) | `timeout` | 12044 ms |

### Handoff

- gatilho `cotacao_indisponivel`, disparado por **regra**
  - motivo: a cotação não respondeu depois de esgotadas as tentativas
