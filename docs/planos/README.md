# Planos de implementação — frente Núcleo

Derivados de **`docs/DECISOES-FECHADAS.md`** e da spec do Núcleo. Se um plano divergir
da spec, **a spec manda** — ou a divergência é comunicada e justificada antes.

> **Para quem vai executar:** cada fatia é uma **sessão nova**, começando por ler
> `CLAUDE.md` e o plano da fatia. Não emende da fatia 1 até a 6 na mesma sessão: a
> restrição do turno 1 não sobrevive ao turno 80, e um agente que constrói muito antes
> de qualquer coisa rodar não tem sinal de erro.
>
> Os passos usam checkbox (`- [ ]`) para acompanhamento. As sub-skills
> `subagent-driven-development` e `executing-plans` são manual-only neste workspace e
> **não** são pré-requisito destes planos — a execução é sequencial, uma fatia por
> sessão, com validação do usuário ao final de cada uma.

---

## As seis fatias

| # | Plano | Ao final |
|---|---|---|
| 1 | [`01-espinha.md`](01-espinha.md) | o console conversa, a mensagem persiste com id e status, e a PII já não passa |
| 2 | [`02-qualificacao.md`](02-qualificacao.md) | os cinco campos saem de texto livre |
| 3 | [`03-cotacao.md`](03-cotacao.md) | a primeira cotação sai, renderizada por template — **o entregável nº 4 existe em rascunho** |
| 4 | [`04-resiliencia.md`](04-resiliencia.md) | prova com `FAILURE_RATE=1.0` e `SLOW_RATE=1.0` |
| 5 | [`05-handoff.md`](05-handoff.md) | sete gatilhos, um teste cada |
| 6 | [`06-recusa.md`](06-recusa.md) | os 30 % incotáveis tratados como fluxo principal |

---

## Mapa de arquivos

Cada arquivo tem **uma** responsabilidade. O que muda junto, mora junto.

```
app/
├── contracts/            ← Fase 0, CONGELADO. Uma exceção prevista: ver nota.
│   ├── quote.py          QuoteRequest · QuotePayload · classificar_erro · QuoteResult
│   ├── conversa.py       LeadProfile · Turn · HandoffSignal · ConversationState
│   └── channel.py        a porta ChannelAdapter
│
├── config.py             (1) settings por pydantic-settings; todos os limiares
├── textos.py             (3) os dez textos, cópia literal de docs/TEXTOS.md
│
├── privacy/
│   └── mascarar.py       (1) CPF · telefone · e-mail · CEP · placa
│
├── persistence/
│   ├── db.py             (1) engine e sessão
│   ├── models.py         (1) SQLAlchemy sobre as migrações
│   └── repo.py           (1) ponto de estrangulamento: gravar_mensagem()
│
├── agent/
│   ├── guardrail.py      (1,3) as três verificações + injeção
│   ├── catalogo.py       (2) busca /planos no boot, SEM valor monetário
│   ├── prompt.py         (2) system estático cacheável + bloco volátil cache=False
│   ├── tools.py          (2,3,5) qualify_lead · quote_plan · escalate_to_human
│   └── runner.py         (1) um turno; grava turn_usage
│
├── quote/
│   ├── client.py         (3,4) timeout · retry · backoff · semáforo
│   ├── breaker.py        (4) circuit breaker, global por processo
│   ├── job.py            (3,4) orquestra tentativas → QuoteResult; persiste attempts
│   └── renderer.py       (3) QuotePayload → str. ORIGEM ÚNICA do bloco de preço.
│
├── handoff/
│   └── gatilhos.py       (5) os sete, com precedência e composição de texto
│
├── channels/
│   └── console.py        (1) ConsoleAdapter; typing no-op; transcript com [+Xs]
│
├── conversa.py           (1,4) fila de um turno por conversa; relógio de 10 s
└── console_main.py       (1) python -m app.console

db/migrations/
├── 0001_inicial.sql      Fase 0
├── 0002_turn_usage.sql   Fase 0
└── 0003_handoff_trigger.sql  (5) CHECK com os sete gatilhos fechados

tests/nucleo/             uma suíte por fatia + test_guardrail.py transversal
```

> **A exceção ao "congelado".** `HandoffTrigger` foi marcado como provisório no próprio
> contrato da Fase 0, e tem **oito** membros contra os **sete** gatilhos que a decisão 3
> fechou. A fatia 5 remove `COTACAO_RECUSADA` — recusa não vira handoff — e é a única
> alteração autorizada em `app/contracts/`. Qualquer outra volta para decisão escrita.

### As três fronteiras que o mapa trava

1. **`quote/renderer.py` é a única origem de texto com valor monetário.** Nenhum outro
   módulo formata dinheiro. É o que torna a comparação byte a byte possível.
2. **`persistence/repo.py::gravar_mensagem` é o único caminho para o banco.** Toda
   mensagem passa pelo mascaramento e pelo guardrail ali, e nenhuma fatia abre um atalho.
3. **`agent/tools.py` é a fronteira do modelo.** Abaixo dela existem status HTTP,
   tentativas e breaker; acima, não. Nenhuma fatia vaza um `503` para cima.

---

## Ordem e dependências

```
1 espinha ──► 2 qualificação ──► 3 cotação ──► 4 resiliência ──► 5 handoff ──► 6 recusa
     │                                              │                              │
     │                                              └── a frente de Frontend        │
     └── privacy/mascarar.py é reusado pela              abre aqui                  │
         frente de Dados na fatia 9                                                 │
                                          o transcript do entregável nº 4 ──────────┘
                                          nasce na 3 e amadurece até a 6
```

## Convenções de commit

Conventional Commits, em português, uma linha por passo de plano concluído.
Nada de `git push` sem autorização explícita.

---

## Pendências do orquestrador

Coisas combinadas com o usuário que não são de nenhuma fatia e não podem se perder.

### `/impeccable` com vistoria de navegação por Playwright

Depois das fatias 5 e 6, antes de gerar a evidência definitiva:

1. **Vistoria de navegação pela aplicação de verdade**, com Playwright — não revisão de
   componente. Percorrer o **fluxo inicial completo**: entrada na aplicação → escolha da
   via → conversa no `/chat` → cotação saindo → `/admin/conversas` → detalhe com a linha
   do tempo → `/admin/handoffs`.
2. Só então `/impeccable` sobre o que renderiza, com **estado real**. Revisar mockup é
   revisar a coisa errada, e por isso esta ordem.

O motivo de estar aqui e não numa lista mental: a navegação foi justamente o que o
usuário apontou como não comunicando as seções, e uma vistoria feita percorrendo as
telas é o único jeito de saber se a correção pegou. Componente que passa em teste de
unidade e confunde quem navega continua sendo um problema.

#### O percurso, clicando — exatamente como o avaliador vai fazer

```
/  →  escolher a via  →  /chat  →  conversar até SAIR UMA COTAÇÃO
   →  voltar  →  /admin  →  ENCONTRAR aquela conversa  →  abrir o detalhe
   →  /admin/status  →  /admin/handoffs  →  voltar ao /chat
```

Sem pular etapa e sem navegar por URL: **clicando**.

#### As quatro perguntas que a vistoria responde

Nenhuma delas é sobre estética:

1. Em **qualquer ponto** do percurso dá para saber **onde você está**?
2. Em qualquer ponto dá para saber **como sair dali**? Alguma tela é beco sem saída?
3. Algum **estado vazio** deixa de explicar o que fazer?
4. Algum **erro** aparece sem dizer o próximo passo?

#### Por que isto vale mais que captura bonita

Os três defeitos encontrados no dia — `external_ref` colidindo no segundo uso, o stub
no lugar do agente, e a navegação sem seções — **nenhum apareceu em teste**. Os três
apareceram usando. A vistoria por Playwright é a versão automatizável disso.

#### Regra de execução

**Registrar o que encontrar como achado, e não consertar calado.** A lista vai para o
usuário **antes** das correções. Conserto silencioso esconde o tamanho do problema, e é
justamente o tamanho que decide o que entra e o que fica como limitação declarada.
