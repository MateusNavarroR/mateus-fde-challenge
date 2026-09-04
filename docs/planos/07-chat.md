# Fatia 7 — O adaptador web e a tela `/chat`

**Objetivo:** o lead conversa pelo navegador e **vê a degradação acontecer**. Num turno
bloqueado de até 37 s, as três mensagens de sistema — aviso aos 6 s, reforço aos ~20 s,
e o bloco da cotação (ou o texto de indisponibilidade) quando o job resolve — chegam à
tela **uma a uma, enquanto o turno ainda não terminou**, com o indicador de digitando
aceso do começo ao fim.

**Arquitetura:** a tela é um cliente burro de um fluxo de eventos. Ela não decide nada
sobre a conversa: recebe `MessageEvent`, `TypingEvent` e `StateEvent` pelo WebSocket
`/api/chat/{conversation_id}`, mantém um mapa `id → Message` e **renderiza ordenado por
`index`**. Quem produz as três mensagens é o backend — a tool de cotação despacha pelo
`ChannelAdapter`, e o adaptador `web` é só o transporte. A consequência de desenho é
que a tela não tem cronômetro nenhum: não existe um `setTimeout(6000)` no navegador. Se
existisse, a tela estaria reimplementando a política em outro lugar, e as duas cópias
divergiriam na primeira mudança de limiar.

**Stack:** React 18 + TypeScript estrito + Vite. Vitest + Testing Library para unidade,
Playwright para as evidências. Nenhuma biblioteca de estado global: um `useReducer` e um
`WebSocket` bastam, e um reducer puro é o que torna a ordenação testável sem navegador.

**Depende de:** `docs/openapi.yaml` **congelado** (o contrato é ele, não a implementação)
e do estado real produzido pelo Núcleo até a fatia 4 — antes dela não existe degradação
para a tela mostrar (`docs/DECISOES-FECHADAS.md` §7). A fatia 8 (admin) depende desta
por `web/src/api/` e pelo teste de deriva do OpenAPI.

**Escopo de arquivo:** este plano toca **somente** `web/` e `tests/web/`. Nada em `app/`,
`db/` ou `docs/openapi.yaml`. O que o Núcleo precisa entregar para esta tela funcionar
está no fim, em **DEPENDÊNCIA PARA O NÚCLEO** — como nota, não como task.

**Critério de pronto:**

1. `npm --prefix web run test` verde (unidade + deriva do OpenAPI);
2. `npm --prefix web run e2e` verde;
3. com `QUOTE_FAILURE_RATE=1.0`, a conversa no navegador mostra ①, ②, ③+④ em sequência,
   com o digitando aceso entre a primeira e a última, e o Playwright grava
   `docs/evidencia-ui/03-chat-degradacao.png` a partir desse estado real;
4. `rg -n '[0-9]{3}\.[0-9]{3}\.[0-9]{3}-[0-9]{2}|@example\.|\+55 ' web tests/web` não
   acha nada (invariante 13b).

> **Quem implementa invoca `/frontend-design` na criação de cada tela e `/impeccable` na
> revisão** (`CLAUDE.md`, decisões fechadas). Os planos definem comportamento e prova;
> a direção visual sai das skills.

---

## O mecanismo, antes das tasks

Esta seção não é contexto: é a especificação que as Tasks 4, 5 e 6 implementam. O
comportamento sob falha é o critério que o enunciado diz que mais separa, e ele é
inteiramente uma questão de **qual frame chega, emitido por quem, em que ordem**.

### A sequência de frames de um turno degradado

Relógio contado da chegada da mensagem do lead (`DECISOES-FECHADAS.md` §1).

| t | Frame no WS `/api/chat/{id}` | Emitido por | O que a tela faz |
|---|---|---|---|
| +0.00 s | ← `{"type":"message","text":"..."}` | **cliente** | insere a bolha otimista, id temporário, e entra na fila de reconciliação |
| +0.05 s | → `MessageEvent` · `autor: "lead"`, `index: n`, conteúdo **mascarado** | `repo.gravar_mensagem` | reconcilia a bolha otimista por id; o texto exibido passa a ser o mascarado |
| +0.05 s | → `TypingEvent` · `ativo: true` | camada de conversa, no início do turno | acende o indicador |
| +0.10 s | → `StateEvent` · `state: "cotando"` | camada de conversa | atualiza o rótulo de estado |
| **+6.00 s** | → `MessageEvent` · `autor: "sistema"`, `index: n+1`, texto ① | **de dentro da tool de cotação**, pelo `ChannelAdapter` web | **insere a bolha e mantém o digitando aceso** |
| **+20.0 s** | → `MessageEvent` · `autor: "sistema"`, `index: n+2`, texto ② | idem | idem |
| **+37.1 s** | → `MessageEvent` · `autor: "sistema"`, `index: n+3`, texto ③+④ | idem, quando o job termina `failed` | insere a bolha |
| +37.1 s | → `StateEvent` · `state: "encaminhado"` | camada de conversa | trava o campo de entrada |
| +37.2 s | → `TypingEvent` · `ativo: false` | camada de conversa, **no fim do turno** | apaga o indicador |

No caminho feliz lento, as linhas de +6 s e de +37 s são substituídas por: ① aos 6 s e,
aos ~8 s, um `MessageEvent` `autor: "agente"` com o bloco da cotação e **`quote_id`
não-nulo**.

Três consequências que a tela precisa respeitar, e cada uma vira teste:

1. **O digitando não é por mensagem, é por turno.** Ele acende no `TypingEvent`
   `ativo: true` e só apaga no `ativo: false`. Um cliente ingênuo apagaria o indicador ao
   receber a primeira mensagem — e aí o lead veria "aviso de espera" seguido de silêncio
   morto por 31 s, que é exatamente o buraco que a política existe para tapar.
2. **`sistema` e `agente` são visualmente idênticos para o lead.** A distinção é
   auditoria, não produto: para quem está do outro lado, é a mesma empresa falando. A
   distinção existe e é visível **no admin** (fatia 8), onde é informação.
3. **A ordem é `index`, nunca chegada nem `criado_em`.** Os timestamps do dataset estão
   99,8 % fora de ordem (`CLAUDE.md`), e sob replay de reconexão a chegada é
   arbitrária por construção. O reducer ordena por `index` e ponto.

### Por que a reconexão é obrigatória

Uma janela de 37 s com o socket aberto é longa o bastante para uma troca de rede, um
sleep de laptop ou um proxy impaciente derrubar a conexão — e o que se perde ali é
justamente ① e ②, as duas mensagens que provam o comportamento sob falha.

O protocolo é: ao abrir (inclusive na primeira vez), o cliente envia

```json
{"type":"hello","last_index":-1}
```

com `last_index` = maior `index` que ele já tem (`-1` quando não tem nenhum). O servidor
responde com replay **do banco**, em ordem de `index`, de tudo com `index > last_index`,
e em seguida com o `TypingEvent` e o `StateEvent` correntes. Como o reducer é idempotente
por `id` e ordena por `index`, um replay que repita mensagens não duplica nada — e é por
isso que o cliente pode reenviar `hello` sem medo em toda reabertura.

O replay vem do banco, não de um buffer em memória do processo: um buffer se perde no
restart do container, que é operação rotineira aqui (`CLAUDE.md`, reprodutibilidade).

### A bolha otimista, e por que ela não reconcilia por texto

A tentação é casar a bolha otimista com o eco do servidor comparando o texto. **Não
funciona, e o motivo é um invariante do produto:** o `conteudo` que volta já passou pelo
mascaramento, e não existe endpoint que devolva a versão crua (`openapi.yaml`, invariante
2 do preâmbulo). Se o lead escreveu um CPF, o texto digitado e o texto ecoado são
diferentes por construção. Casar por texto produziria uma bolha duplicada exatamente na
conversa que exercita PII.

A reconciliação é **FIFO**: o cliente mantém uma fila de ids temporários na ordem de
envio; cada `MessageEvent` com `autor: "lead"` cujo `index` seja maior que o maior
conhecido consome o primeiro id da fila e o substitui pela mensagem persistida. Isso é
determinístico mesmo quando o lead envia uma segunda mensagem durante um turno bloqueado
— caso que existe de verdade, porque a camada de conversa enfileira em vez de recusar.

---

## Task 1 — O esqueleto do `web/`, com o bind certo

**Files:** Create `web/package.json`, `web/tsconfig.json`, `web/vite.config.ts`,
`web/index.html`, `web/src/main.tsx`, `web/src/App.tsx` · Test
`tests/web/unit/config.test.ts`

O invariante 14b não é sobre o compose só: um `vite dev` publica em `localhost` por
default, mas `vite preview` e qualquer `--host` acidental furam isso. O teste trava a
configuração no arquivo, que é onde alguém a mudaria.

- [ ] **Passo 1: teste que falha**

```ts
// tests/web/unit/config.test.ts
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import config from "../../web/vite.config";

describe("configuração do vite", () => {
  it("publica só em 127.0.0.1, nunca em 0.0.0.0 (CLAUDE.md 14b)", () => {
    expect(config.server?.host).toBe("127.0.0.1");
    expect(config.preview?.host).toBe("127.0.0.1");
  });

  it("não deixa host aberto em nenhum script do package.json", () => {
    const pkg = JSON.parse(readFileSync("web/package.json", "utf8"));
    for (const [nome, cmd] of Object.entries<string>(pkg.scripts)) {
      expect(cmd, nome).not.toMatch(/--host(\s|=|$)/);
      expect(cmd, nome).not.toContain("0.0.0.0");
    }
  });

  it("proxya /api para o backend local, para haver uma origem só", () => {
    const proxy = config.server?.proxy as Record<string, { target: string; ws?: boolean }>;
    expect(proxy["/api"].target).toBe("http://127.0.0.1:8080");
    expect(proxy["/api"].ws).toBe(true); // sem isto o WebSocket não passa pelo dev server
  });
});
```

- [ ] **Passo 2:** `npm --prefix web run test -- config` → FAIL (`web/vite.config.ts` não existe)
- [ ] **Passo 3:** criar o esqueleto. `tsconfig.json` com `"strict": true` e
      `"noUncheckedIndexedAccess": true`; **nenhum `any` no projeto** (convenção do
      workspace). Rotas em `App.tsx`: `/chat`, `/admin/conversas`,
      `/admin/conversas/:id`, `/admin/status`, `/admin/handoffs` — as de admin ficam como
      placeholder até a fatia 8. Scripts: `dev`, `build`, `test`, `e2e`, `lint`.
- [ ] **Passo 4:** `npm --prefix web run test -- config` → PASS
- [ ] **Passo 5:** `git commit -m "feat(web): esqueleto React+Vite publicando só em 127.0.0.1"`

---

## Task 2 — Tipos derivados do contrato congelado

**Files:** Create `web/src/api/tipos.ts` · Test `tests/web/unit/tipos.test.ts`

Os tipos são transcrição do `openapi.yaml`, não invenção. O teste desta task é o que
impede a transcrição de envelhecer em silêncio; a Task 3 fecha o cerco pelo lado das
rotas.

- [ ] **Passo 1: teste que falha**

```ts
// tests/web/unit/tipos.test.ts
import { readFileSync } from "node:fs";
import { parse } from "yaml";
import { describe, expect, it } from "vitest";
import { AUTORES, ESTADOS_CONVERSA, OUTCOMES, STATUS_HANDOFF, STATUS_JOB, STATUS_MENSAGEM } from "../../web/src/api/tipos";

const spec = parse(readFileSync("docs/openapi.yaml", "utf8"));
const enumDe = (nome: string): string[] => spec.components.schemas[nome].enum;

describe("os enums da UI são os do contrato congelado", () => {
  it.each([
    ["ConversationState", ESTADOS_CONVERSA],
    ["MessageStatus", STATUS_MENSAGEM],
    ["QuoteOutcome", OUTCOMES],
    ["QuoteJobStatus", STATUS_JOB],
    ["HandoffStatus", STATUS_HANDOFF],
  ])("%s", (nome, nosso) => {
    expect([...nosso].sort()).toEqual([...enumDe(nome)].sort());
  });

  it("autor tem os quatro valores, e `sistema` é um deles", () => {
    const doContrato = spec.components.schemas.Message.properties.autor.enum;
    expect([...AUTORES].sort()).toEqual([...doContrato].sort());
    expect(AUTORES).toContain("sistema");
  });

  it("os cinco outcomes existem — cada um implica uma ação distinta (API-COTACAO §7)", () => {
    expect(OUTCOMES).toHaveLength(5);
  });
});
```

- [ ] **Passo 2:** `npm --prefix web run test -- tipos` → FAIL
- [ ] **Passo 3:** escrever `tipos.ts` com `Message`, `Conversation`, `ConversationDetail`,
      `Quote`, `QuoteAttempt`, `QuoteResultado`, `QuoteHealth`, `Handoff`, `Usage`,
      `UsageAgregado`, `MessageEvent`, `TypingEvent`, `StateEvent`, mais os arrays
      `as const` que o teste importa. Campos anuláveis do contrato são `| null` no tipo —
      **`cache_read` e `taxa_acerto_cache` nunca são `number` puro**, e é o tipo que vai
      obrigar a tela da fatia 8 a tratar o "n/a".
- [ ] **Passo 4:** `npm --prefix web run test -- tipos` → PASS
- [ ] **Passo 5:** `git commit -m "feat(web): tipos transcritos do openapi congelado"`

---

## Task 3 — O teste de deriva do OpenAPI, nos dois sentidos

**Files:** Create `tests/web/unit/openapi-deriva.test.ts`, `web/scripts/baixar-openapi.mjs`
· Test o próprio arquivo

Este é o teste que separa "construímos contra o contrato" de "construímos contra o que a
implementação faz". Ele tem dois sentidos, e **o segundo é o que pega superfície não
documentada** — uma rota que apareceu no backend e nunca passou por decisão escrita.

- [ ] **Passo 1: teste que falha**

```ts
// tests/web/unit/openapi-deriva.test.ts
import { existsSync, readFileSync } from "node:fs";
import { parse } from "yaml";
import { describe, expect, it } from "vitest";

const GERADO = "tests/web/.openapi-gerado.json";

const congelado = parse(readFileSync("docs/openapi.yaml", "utf8"));
const rotas = (spec: { paths: Record<string, object> }) =>
  Object.entries(spec.paths)
    .flatMap(([p, ops]) => Object.keys(ops).map((m) => `${m.toUpperCase()} ${p}`))
    .sort();

describe.runIf(existsSync(GERADO))("deriva entre o congelado e o gerado", () => {
  const gerado = JSON.parse(readFileSync(GERADO, "utf8"));

  it("toda rota do congelado existe no gerado", () => {
    const faltando = rotas(congelado).filter((r) => !rotas(gerado).includes(r));
    expect(faltando, "o backend não entrega o que o contrato promete").toEqual([]);
  });

  it("toda rota do gerado existe no congelado", () => {
    const sobrando = rotas(gerado).filter((r) => !rotas(congelado).includes(r));
    expect(sobrando, "superfície não documentada — passa por decisão escrita antes").toEqual([]);
  });

  it("o arquivo gerado é ignorado pelo git", () => {
    expect(readFileSync(".gitignore", "utf8")).toContain("tests/web/.openapi-gerado.json");
  });
});

it("o teste de deriva não passa por ausência do arquivo", () => {
  // Sem esta linha, `describe.runIf` faria a suíte inteira sumir em silêncio quando
  // ninguém rodou o backend — e um teste que some passando é pior que um teste ausente.
  expect(existsSync(GERADO), "rode `npm --prefix web run openapi:baixar` com o backend no ar").toBe(true);
});
```

- [ ] **Passo 2:** `npm --prefix web run test -- deriva` → FAIL (nas duas pontas: sem
      script e sem arquivo)
- [ ] **Passo 3:** escrever `web/scripts/baixar-openapi.mjs`, que faz `fetch` de
      `http://127.0.0.1:8080/openapi.json` e grava em `tests/web/.openapi-gerado.json`;
      adicionar o script `openapi:baixar` ao `package.json`. As duas rotas de WebSocket
      (`/api/chat/{conversation_id}` e `/api/events`) aparecem no gerado como `GET` —
      é como o FastAPI documenta o upgrade, e é como o congelado as descreve, então a
      comparação fecha sem exceção.
- [ ] **Passo 4:** com o backend no ar, `npm --prefix web run openapi:baixar &&
      npm --prefix web run test -- deriva` → PASS
- [ ] **Passo 5:** `git commit -m "test(web): deriva do openapi nos dois sentidos"`

> **Se o segundo sentido falhar**, a correção **não** é relaxar o teste nem editar o
> congelado. É abrir a rota na spec por decisão escrita, ou removê-la do backend. O
> `openapi.yaml` está congelado desde a Fase 0 e esta frente não o altera.

---

## Task 4 — O reducer da conversa: ordem, idempotência e reconciliação

**Files:** Create `web/src/chat/useConversa.ts` (o reducer exportado puro) · Test
`tests/web/unit/reducer-conversa.test.ts`

O coração da tela é uma função pura. Testá-la sem navegador é o que permite exercitar a
janela de 37 s em milissegundos — uma suíte que dorme 37 s ninguém roda (é a mesma lição
do relógio injetado da fatia 1).

- [ ] **Passo 1: teste que falha**

```ts
// tests/web/unit/reducer-conversa.test.ts
import { describe, expect, it } from "vitest";
import { estadoInicial, reduzir, type Estado } from "../../web/src/chat/useConversa";
import { gerarPii, fraseDoLead } from "../fixtures/pii";

const msg = (index: number, autor: string, conteudo: string, extra = {}) => ({
  type: "message" as const,
  message: {
    id: `m${index}`, index, autor, tipo: "text", conteudo,
    status: "sent", quote_id: null, criado_em: "2026-01-01T00:00:00Z", ...extra,
  },
});

const aplicar = (eventos: unknown[], de: Estado = estadoInicial()) =>
  eventos.reduce<Estado>((e, ev) => reduzir(e, ev as never), de);

describe("ordenação", () => {
  it("ordena por index, não por ordem de chegada", () => {
    const e = aplicar([msg(2, "agente", "terceira"), msg(0, "lead", "primeira"), msg(1, "sistema", "segunda")]);
    expect(e.mensagens.map((m) => m.conteudo)).toEqual(["primeira", "segunda", "terceira"]);
  });

  it("ordena por index mesmo quando criado_em está fora de ordem", () => {
    // 99,8% das conversas do dataset têm timestamp fora de ordem (CLAUDE.md).
    const e = aplicar([
      msg(0, "lead", "primeira", { criado_em: "2026-01-01T00:00:09Z" }),
      msg(1, "agente", "segunda", { criado_em: "2026-01-01T00:00:03Z" }),
    ]);
    expect(e.mensagens.map((m) => m.index)).toEqual([0, 1]);
  });

  it("é idempotente por id — o replay da reconexão não duplica", () => {
    const e = aplicar([msg(0, "lead", "oi"), msg(1, "agente", "olá"), msg(0, "lead", "oi"), msg(1, "agente", "olá")]);
    expect(e.mensagens).toHaveLength(2);
  });
});

describe("bolha otimista", () => {
  it("aparece antes de qualquer resposta do servidor", () => {
    const e = reduzir(estadoInicial(), { type: "envio-local", idTemp: "tmp-1", texto: "quero cotar" });
    expect(e.mensagens.at(-1)).toMatchObject({ id: "tmp-1", autor: "lead", pendente: true });
  });

  it("reconcilia por id, e o texto exibido passa a ser o MASCARADO", () => {
    // Reconciliar por texto seria bug: não existe endpoint que devolva a versão crua
    // (openapi.yaml, invariante 2). Aqui o digitado e o ecoado diferem por construção.
    const [frase, pii] = fraseDoLead(11);
    let e = reduzir(estadoInicial(), { type: "envio-local", idTemp: "tmp-1", texto: frase });
    e = reduzir(e, msg(0, "lead", frase.replace(pii.cpf, "[CPF]")));
    expect(e.mensagens).toHaveLength(1);
    expect(e.mensagens[0]!.id).toBe("m0");
    expect(e.mensagens[0]!.pendente).toBe(false);
    expect(e.mensagens[0]!.conteudo).not.toContain(pii.cpf);
  });

  it("reconcilia FIFO quando o lead envia duas antes do eco (a conversa enfileira)", () => {
    let e = reduzir(estadoInicial(), { type: "envio-local", idTemp: "tmp-1", texto: "primeira" });
    e = reduzir(e, { type: "envio-local", idTemp: "tmp-2", texto: "segunda" });
    e = aplicar([msg(0, "lead", "primeira"), msg(2, "lead", "segunda")], e);
    expect(e.mensagens.map((m) => m.id)).toEqual(["m0", "m2"]);
    expect(e.pendentesDoLead).toEqual([]);
  });
});

describe("o turno bloqueado de 37 s", () => {
  it("mantém o digitando aceso entre as três mensagens de sistema", () => {
    let e = aplicar([{ type: "typing", ativo: true }, msg(0, "lead", "quero cotar")]);
    for (const [i, texto] of ["aviso", "reforço", "indisponibilidade"].entries()) {
      e = reduzir(e, msg(i + 1, "sistema", texto) as never);
      expect(e.digitando, `apagou no ${texto}`).toBe(true);
    }
    e = reduzir(e, { type: "typing", ativo: false });
    expect(e.digitando).toBe(false);
  });

  it("mensagem do agente também não apaga o digitando — só o typing false apaga", () => {
    let e = aplicar([{ type: "typing", ativo: true }, msg(0, "agente", "oi")]);
    expect(e.digitando).toBe(true);
  });

  it("o StateEvent encaminhado trava a entrada", () => {
    const e = reduzir(estadoInicial(), { type: "state", state: "encaminhado" });
    expect(e.entradaBloqueada).toBe(true);
  });
});

describe("hello e replay", () => {
  it("last_index é o maior index conhecido, -1 quando vazio", () => {
    expect(estadoInicial().ultimoIndex).toBe(-1);
    expect(aplicar([msg(0, "lead", "a"), msg(7, "agente", "b")]).ultimoIndex).toBe(7);
  });

  it("o replay parcial preserva o que já havia e não reordena nada", () => {
    let e = aplicar([msg(0, "lead", "a"), msg(1, "sistema", "aviso")]);
    e = aplicar([msg(1, "sistema", "aviso"), msg(2, "sistema", "reforço")], e);
    expect(e.mensagens.map((m) => m.index)).toEqual([0, 1, 2]);
  });
});

describe("o guardrail visível", () => {
  it("marca como bug uma mensagem com valor monetário e quote_id nulo", () => {
    const e = aplicar([msg(0, "agente", "fica R$ 392,25/mês", { quote_id: null })]);
    expect(e.mensagens[0]!.suspeitaDeBug).toBe(true);
  });

  it("não marca a mesma mensagem quando o quote_id existe", () => {
    const e = aplicar([msg(0, "agente", "fica R$ 392,25/mês", { quote_id: "q1" })]);
    expect(e.mensagens[0]!.suspeitaDeBug).toBe(false);
  });

  it("não marca texto sem dinheiro — o marcador não pode virar paranoia", () => {
    const e = aplicar([msg(0, "agente", "tenho 35 anos de estrada, carro 2019")]);
    expect(e.mensagens[0]!.suspeitaDeBug).toBe(false);
  });
});
```

- [ ] **Passo 2:** `npm --prefix web run test -- reducer` → FAIL
- [ ] **Passo 3:** implementar. O estado é
      `{ porId: Map<string, Mensagem>, pendentesDoLead: string[], digitando, state, entradaBloqueada }`;
      `mensagens` é derivado com `[...porId.values()].sort((a,b) => a.index - b.index)`, com
      as pendentes ao fim. `suspeitaDeBug` usa o mesmo regex de dinheiro do guardrail do
      Núcleo (`R\$\s*[\d.,]+` e `[\d.,]+\s*reais`), transcrito — a tela **exibe** o bug,
      quem o impede é o backend.
- [ ] **Passo 4:** `npm --prefix web run test -- reducer` → PASS
- [ ] **Passo 5:** `git commit -m "feat(chat): reducer ordenado por index, idempotente e com reconciliação FIFO"`

> `tests/web/fixtures/pii.ts` é a porta do TypeScript para a regra do
> `docs/planos/00-fixtures-pii.md`: mesmo desenho, mesmo contrato `(frase, pii)`, gerador
> semeado com um LCG explícito — **`Math.random()` não aceita seed, e sem seed a falha
> deixa de ser reproduzível**. Nenhum literal, nenhum golden file, nenhuma lista de
> exceções. Ele nasce nesta task, junto com o primeiro teste que o usa.

---

## Task 5 — O socket: hello, replay e reconexão

**Files:** Create `web/src/api/ws.ts` · Test `tests/web/unit/ws.test.ts`

A reconexão não é robustez extra aqui. Ela é requisito do comportamento contratado: com
uma janela de 37 s, um socket que cai sem se recuperar apaga ① e ②, que são a prova.

- [ ] **Passo 1: teste que falha**

```ts
// tests/web/unit/ws.test.ts
import { beforeEach, describe, expect, it, vi } from "vitest";
import { conectarChat } from "../../web/src/api/ws";
import { WebSocketFalso } from "../fakes/websocket-falso";

beforeEach(() => { vi.useFakeTimers(); vi.stubGlobal("WebSocket", WebSocketFalso); });

it("envia hello com last_index -1 na primeira abertura", () => {
  const s = conectarChat("c1", { ultimoIndex: () => -1, aoEvento: vi.fn() });
  WebSocketFalso.ultima!.abrir();
  expect(JSON.parse(WebSocketFalso.ultima!.enviados[0]!)).toEqual({ type: "hello", last_index: -1 });
  s.fechar();
});

it("reabre e repete o hello com o último index que a tela tem", () => {
  let indice = -1;
  const s = conectarChat("c1", { ultimoIndex: () => indice, aoEvento: () => { indice = 2; } });
  WebSocketFalso.ultima!.abrir();
  WebSocketFalso.ultima!.receber({ type: "message", message: { index: 2 } });
  WebSocketFalso.ultima!.cair();
  vi.advanceTimersByTime(1_000);
  WebSocketFalso.ultima!.abrir();
  expect(JSON.parse(WebSocketFalso.ultima!.enviados[0]!)).toEqual({ type: "hello", last_index: 2 });
  s.fechar();
});

it("o backoff cresce e tem teto — não martela o backend caído", () => {
  const s = conectarChat("c1", { ultimoIndex: () => -1, aoEvento: vi.fn() });
  const esperas: number[] = [];
  for (let i = 0; i < 8; i++) {
    WebSocketFalso.ultima!.cair();
    esperas.push(WebSocketFalso.proximaEsperaMs);
    vi.advanceTimersByTime(WebSocketFalso.proximaEsperaMs);
  }
  expect(esperas[0]!).toBeLessThan(esperas[3]!);
  expect(Math.max(...esperas)).toBeLessThanOrEqual(10_000);
  s.fechar();
});

it("expõe o estado da conexão para a tela avisar o lead", () => {
  const estados: string[] = [];
  const s = conectarChat("c1", { ultimoIndex: () => -1, aoEvento: vi.fn(), aoStatus: (e) => estados.push(e) });
  WebSocketFalso.ultima!.abrir();
  WebSocketFalso.ultima!.cair();
  expect(estados).toEqual(["conectando", "conectado", "reconectando"]);
  s.fechar();
});

it("um fechamento pedido pela tela não reconecta", () => {
  const s = conectarChat("c1", { ultimoIndex: () => -1, aoEvento: vi.fn() });
  WebSocketFalso.ultima!.abrir();
  s.fechar();
  vi.advanceTimersByTime(60_000);
  expect(WebSocketFalso.criadas).toBe(1);
});

it("ignora frame desconhecido sem derrubar a conexão", () => {
  const aoEvento = vi.fn();
  const s = conectarChat("c1", { ultimoIndex: () => -1, aoEvento });
  WebSocketFalso.ultima!.abrir();
  WebSocketFalso.ultima!.receber({ type: "coisa_do_futuro" });
  expect(aoEvento).not.toHaveBeenCalled();
  expect(WebSocketFalso.ultima!.fechada).toBe(false);
  s.fechar();
});
```

- [ ] **Passo 2:** `npm --prefix web run test -- ws` → FAIL
- [ ] **Passo 3:** implementar `conectarChat(conversationId, { ultimoIndex, aoEvento, aoStatus })`
      e `conectarEventos(...)` (esta usada pela fatia 8, mesma mecânica de reconexão, sem
      `hello`). Backoff exponencial com jitter, teto de 10 s. A URL é derivada do
      `location`: `ws://` sobre `http:`, `wss://` sobre `https:` — nunca host fixo, que
      quebraria atrás do proxy do compose.
- [ ] **Passo 4:** `npm --prefix web run test -- ws` → PASS
- [ ] **Passo 5:** `git commit -m "feat(web): socket com hello/last_index, replay e reconexão com backoff"`

---

## Task 6 — A tela `/chat`

**Files:** Create `web/src/chat/PaginaChat.tsx`, `Bolha.tsx`, `Digitando.tsx`,
`BlocoCotacao.tsx` · Test `tests/web/unit/pagina-chat.test.tsx`

> **Invocar `/frontend-design` antes de escrever o JSX.** A tela simula um canal de
> mensagem; o que ela precisa provar é o ritmo da espera, não o enfeite.

- [ ] **Passo 1: teste que falha**

```tsx
// tests/web/unit/pagina-chat.test.tsx
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { PaginaChat } from "../../web/src/chat/PaginaChat";
import { montarServidorFalso } from "../fakes/servidor-falso";

it("sistema e agente são visualmente idênticos para o lead", async () => {
  const srv = montarServidorFalso();
  render(<PaginaChat conversationId="c1" />);
  await srv.emitir({ type: "message", message: { id: "m1", index: 0, autor: "sistema", conteudo: "aviso", tipo: "text", status: "sent", quote_id: null, criado_em: "..." } });
  await srv.emitir({ type: "message", message: { id: "m2", index: 1, autor: "agente", conteudo: "olá", tipo: "text", status: "sent", quote_id: null, criado_em: "..." } });
  const [a, b] = screen.getAllByTestId(/^bolha-/);
  expect(a!.className).toBe(b!.className);          // mesma aparência
  expect(screen.queryByText(/sistema/i)).toBeNull(); // e nenhum rótulo que denuncie
});

it("a bolha do lead é distinta da dos dois", async () => {
  const srv = montarServidorFalso();
  render(<PaginaChat conversationId="c1" />);
  await srv.emitir({ type: "message", message: { id: "m1", index: 0, autor: "lead", conteudo: "oi", tipo: "text", status: "sent", quote_id: null, criado_em: "..." } });
  await srv.emitir({ type: "message", message: { id: "m2", index: 1, autor: "agente", conteudo: "olá", tipo: "text", status: "sent", quote_id: null, criado_em: "..." } });
  const [lead, agente] = screen.getAllByTestId(/^bolha-/);
  expect(lead!.className).not.toBe(agente!.className);
});

it("o digitando fica aceso durante as três mensagens do turno degradado", async () => {
  const srv = montarServidorFalso();
  render(<PaginaChat conversationId="c1" />);
  await srv.emitir({ type: "typing", ativo: true });
  for (const [i, texto] of ["Tô buscando o valor", "Ainda tô aqui", "Não consegui confirmar"].entries()) {
    await srv.emitirMensagem(i + 1, "sistema", texto);
    expect(screen.getByTestId("digitando"), texto).toBeVisible();
  }
  await srv.emitir({ type: "typing", ativo: false });
  expect(screen.queryByTestId("digitando")).toBeNull();
});

it("o campo trava e explica quando o estado vira encaminhado", async () => {
  const srv = montarServidorFalso();
  render(<PaginaChat conversationId="c1" />);
  await srv.emitir({ type: "state", state: "encaminhado" });
  expect(screen.getByRole("textbox")).toBeDisabled();
  expect(screen.getByText(/atendente/i)).toBeVisible();  // por que travou, não só que travou
});

it("mostra o aviso de reconexão e o esconde ao voltar", async () => {
  const srv = montarServidorFalso();
  render(<PaginaChat conversationId="c1" />);
  await srv.derrubar();
  expect(screen.getByRole("status")).toHaveTextContent(/reconectando/i);
  await srv.reabrir();
  expect(screen.queryByRole("status")).toBeNull();
});

it("marca visivelmente a mensagem com preço sem quote_id", async () => {
  const srv = montarServidorFalso();
  render(<PaginaChat conversationId="c1" />);
  await srv.emitirMensagem(0, "agente", "fica R$ 392,25/mês", { quote_id: null });
  expect(within(screen.getByTestId("bolha-m0")).getByTestId("marca-bug")).toBeVisible();
});

it("o link para o admin leva à conversa corrente — e não existe o inverso", async () => {
  render(<PaginaChat conversationId="c1" />);
  expect(screen.getByRole("link", { name: /ver esta conversa no admin/i }))
    .toHaveAttribute("href", "/admin/conversas/c1");
});

it("o input não some enquanto o turno roda — a mensagem entra na fila", async () => {
  const srv = montarServidorFalso();
  render(<PaginaChat conversationId="c1" />);
  await srv.emitir({ type: "typing", ativo: true });
  await userEvent.type(screen.getByRole("textbox"), "e o premium?{Enter}");
  expect(screen.getByText("e o premium?")).toBeVisible();  // bolha otimista, turno em voo
});
```

- [ ] **Passo 2:** `npm --prefix web run test -- pagina-chat` → FAIL
- [ ] **Passo 3:** implementar. `BlocoCotacao` **não formata número nenhum**: o bloco
      chega pronto do `quote/renderer.py`, que é a origem única do texto com valor
      monetário (`README` dos planos, fronteira 1). A tela só o exibe preservando as
      quebras de linha e destacando a linha da carência que já vem marcada. Formatar
      moeda no front seria abrir uma segunda origem de preço.
- [ ] **Passo 4:** `npm --prefix web run test -- pagina-chat` → PASS
- [ ] **Passo 5:** `git commit -m "feat(chat): tela com digitando por turno e bolhas idênticas para sistema e agente"`

---

## Task 7 — Sessão: retomada ao carregar, nova conversa por botão

**Files:** Create `web/src/chat/sessao.ts` · Test `tests/web/unit/sessao.test.ts`

`DECISOES-FECHADAS.md` §8: **sempre-nova é o comportamento certo do botão, não do
carregamento.** Um F5 no meio da conversa destruiria a demonstração — e a demonstração é
uma janela de 37 s, em que apertar F5 por impaciência é o gesto mais provável do mundo.

- [ ] **Passo 1: teste que falha**

```ts
// tests/web/unit/sessao.test.ts
import { beforeEach, describe, expect, it, vi } from "vitest";
import { abrirOuRetomar, novaConversa, CHAVE } from "../../web/src/chat/sessao";

beforeEach(() => localStorage.clear());

it("retoma a conversa gravada sem criar outra", async () => {
  localStorage.setItem(CHAVE, "c-antiga");
  const post = vi.fn();
  expect(await abrirOuRetomar({ post, getConversa: async () => ({ id: "c-antiga" }) })).toBe("c-antiga");
  expect(post).not.toHaveBeenCalled();
});

it("cria uma conversa quando não há nenhuma gravada", async () => {
  const post = vi.fn(async () => ({ id: "c-nova" }));
  expect(await abrirOuRetomar({ post, getConversa: async () => null })).toBe("c-nova");
  expect(post).toHaveBeenCalledWith("/api/conversations", { channel: "web" });
  expect(localStorage.getItem(CHAVE)).toBe("c-nova");
});

it("cria outra quando a gravada já não existe no backend (banco recriado)", async () => {
  localStorage.setItem(CHAVE, "c-fantasma");
  const post = vi.fn(async () => ({ id: "c-nova" }));
  expect(await abrirOuRetomar({ post, getConversa: async () => null })).toBe("c-nova");
});

it("o botão de nova conversa descarta a sessão e cria outra", async () => {
  localStorage.setItem(CHAVE, "c-antiga");
  const post = vi.fn(async () => ({ id: "c-nova" }));
  expect(await novaConversa({ post })).toBe("c-nova");
  expect(localStorage.getItem(CHAVE)).toBe("c-nova");
});

it("external_ref nunca carrega dado de pessoa", async () => {
  // openapi.yaml: "Nunca um telefone real (...) Repositório público."
  const post = vi.fn(async () => ({ id: "c" }));
  await abrirOuRetomar({ post, getConversa: async () => null });
  expect(post.mock.calls[0]![1]).not.toHaveProperty("external_ref");
});

it("localStorage indisponível não quebra a tela", async () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("bloqueado"); });
  const post = vi.fn(async () => ({ id: "c-nova" }));
  await expect(abrirOuRetomar({ post, getConversa: async () => null })).resolves.toBe("c-nova");
});
```

- [ ] **Passo 2:** `npm --prefix web run test -- sessao` → FAIL
- [ ] **Passo 3:** implementar. Ao retomar, a tela carrega o histórico por
      `GET /api/conversations/{id}` (já mascarado, já ordenado por `index`) **antes** de
      abrir o socket, e o `hello` sai com o `last_index` desse histórico — o que evita
      pedir de novo o que ela acabou de buscar.
- [ ] **Passo 4:** `npm --prefix web run test -- sessao` → PASS
- [ ] **Passo 5:** `git commit -m "feat(chat): retomada de sessão ao carregar e botão de nova conversa"`

---

## Task 8 — Evidência Playwright: as duas do `/chat`

**Files:** Create `web/playwright.config.ts`, `tests/web/e2e/chat-degradacao.spec.ts`,
`tests/web/e2e/chat-cotacao.spec.ts`, `tests/web/e2e/ajuda/cenario.ts`

**Screenshot com dado de exemplo não vale.** Cada evidência declara o comando que produz
o estado real, e o teste falha se o estado não aparecer — é a diferença entre provar e
ilustrar.

- [ ] **Passo 1: teste que falha**

```ts
// tests/web/e2e/chat-degradacao.spec.ts
import { expect, test } from "@playwright/test";
import { subirCenario } from "./ajuda/cenario";

// Estado real:
//   QUOTE_FAILURE_RATE=1.0 QUOTE_SLOW_RATE=0 QUOTE_SEED=42 docker compose up -d --force-recreate quote-api
// (restart obrigatório: o RNG do legado é um fluxo global do processo — CLAUDE.md,
//  reprodutibilidade. Sem o recreate, a seed não significa nada.)
test("degradação visível: aviso, reforço e encaminhamento em um turno só", async ({ page }) => {
  await subirCenario("degradado");
  await page.goto("/chat");
  await page.getByRole("button", { name: /nova conversa/i }).click();

  const t0 = Date.now();
  await page.getByRole("textbox").fill("tenho 28 anos, carro 2019, cep 07XXX-XXX, começo dia 17/10, quero o completo");
  await page.getByRole("textbox").press("Enter");

  await expect(page.getByTestId("digitando")).toBeVisible();

  await expect(page.getByText("Tô buscando o valor no sistema e ele tá lento agora. Já te trago, tá?")).toBeVisible({ timeout: 15_000 });
  expect(Date.now() - t0).toBeGreaterThan(5_000);           // o aviso não é imediato
  await expect(page.getByTestId("digitando")).toBeVisible(); // e o turno não terminou

  await expect(page.getByText("Ainda tô aqui, viu? O sistema não me devolveu ainda. Assim que sair eu te mando.")).toBeVisible({ timeout: 25_000 });
  await expect(page.getByTestId("digitando")).toBeVisible();

  await expect(page.getByText(/Não consegui confirmar o valor agora/)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/Já passei sua conversa pra um atendente da equipe/)).toBeVisible();
  await expect(page.getByRole("textbox")).toBeDisabled();
  await expect(page.getByTestId("digitando")).toBeHidden();

  // nenhum valor monetário apareceu em nenhum momento do caminho degradado
  await expect(page.getByText(/R\$/)).toHaveCount(0);

  await page.screenshot({ path: "docs/evidencia-ui/03-chat-degradacao.png", fullPage: true });
});

test("a reconexão traz de volta o que chegou com o socket caído", async ({ page, context }) => {
  await subirCenario("degradado");
  await page.goto("/chat");
  await page.getByRole("textbox").fill("quero cotar, 28 anos, carro 2019");
  await page.getByRole("textbox").press("Enter");
  await context.setOffline(true);
  await expect(page.getByRole("status")).toContainText(/reconectando/i);
  await page.waitForTimeout(25_000);              // ① e ② são emitidos com a tela cega
  await context.setOffline(false);
  await expect(page.getByText("Tô buscando o valor no sistema e ele tá lento agora. Já te trago, tá?")).toBeVisible();
  await expect(page.getByText("Ainda tô aqui, viu? O sistema não me devolveu ainda. Assim que sair eu te mando.")).toBeVisible();
});
```

```ts
// tests/web/e2e/chat-cotacao.spec.ts
// Estado real:
//   QUOTE_FAILURE_RATE=0 QUOTE_SLOW_RATE=0 docker compose up -d --force-recreate quote-api
test("a cotação sai com preço, carência e pro-rata", async ({ page }) => {
  await subirCenario("feliz");
  await page.goto("/chat");
  await page.getByRole("button", { name: /nova conversa/i }).click();
  await page.getByRole("textbox").fill("28 anos, carro 2019, cep 07XXX-XXX, plano completo, começo dia 17/10");
  await page.getByRole("textbox").press("Enter");

  const bloco = page.getByTestId("bloco-cotacao");
  await expect(bloco).toBeVisible({ timeout: 20_000 });
  await expect(bloco).toContainText(/R\$ ?\d/);            // preço
  await expect(bloco).toContainText(/30 dias/);            // carência — invariante 2
  await expect(bloco).toContainText(/Franquia/i);          // sempre
  await expect(bloco).toContainText(/proporcional|integral/); // pro-rata, ou a ausência dela
  await expect(bloco).not.toContainText(/CEP|agravo/i);    // agravo nunca é mencionado

  await expect(bloco.locator("[data-quote-id]")).toHaveAttribute("data-quote-id", /.+/);
  await expect(page.getByTestId("marca-bug")).toHaveCount(0);

  await page.screenshot({ path: "docs/evidencia-ui/04-chat-cotacao.png", fullPage: true });
});
```

- [ ] **Passo 2:** `npm --prefix web run e2e -- chat-` → FAIL
- [ ] **Passo 3:** escrever `playwright.config.ts` (baseURL `http://127.0.0.1:5173`,
      `outputDir` fora de `docs/evidencia-ui/` para os artefatos de falha não poluírem a
      pasta de evidência, `workers: 1` — as suítes que dependem de `QUOTE_SEED` rodam em
      série, sempre) e `ajuda/cenario.ts`, que recria o container da `/quote` com as
      variáveis do cenário e espera o `/api/health` responder. Ajustar a tela até os
      dois passarem **sem afrouxar asserção**.
- [ ] **Passo 4:** `npm --prefix web run e2e -- chat-` → PASS, e os dois PNG existem
- [ ] **Passo 5:** `git commit -m "test(web): evidência de degradação e de cotação a partir de estado real"`

---

## Task 9 — Fechar a fatia

- [ ] **Passo 1:** `npm --prefix web run test` e `npm --prefix web run e2e -- chat-` → verdes
- [ ] **Passo 2:** com o backend no ar,
      `npm --prefix web run openapi:baixar && npm --prefix web run test -- deriva` → PASS
      nos **dois** sentidos
- [ ] **Passo 3:** a varredura de PII sobre o que esta fatia escreveu:

```bash
rg -n '[0-9]{3}\.[0-9]{3}\.[0-9]{3}-[0-9]{2}|[0-9]{5}-[0-9]{3}|@[a-z]+\.(com|br)|\+55' web tests/web
```

Esperado: **nada**. O único gerador de PII é `tests/web/fixtures/pii.ts`, e ele não
contém valor — contém a receita. Não existe lista de exceções.

- [ ] **Passo 4:** **invocar `/impeccable` sobre `/chat`** e aplicar o que ela apontar sem
      quebrar teste; reabrir os dois PNG depois, porque uma revisão visual que não é
      re-evidenciada é uma revisão que ninguém conferiu
- [ ] **Passo 5:** relatar: o que ficou pronto, o comando que provou, a saída, e o que
      ficou de fora — **e que a fatia 8 pode começar**
- [ ] **Passo 6:** `git commit -m "chore: fatia 7 fechada — o lead conversa pelo navegador e vê a degradação"`

---

## DEPENDÊNCIA PARA O NÚCLEO

Nada aqui é task deste plano: são coisas em `app/` que esta tela pressupõe e que **nenhum
dos planos 01 a 06 cria**. Cada uma precisa virar decisão escrita e entrar num plano do
Núcleo antes que esta fatia possa fechar de verdade.

1. **A aplicação FastAPI e os oito caminhos do contrato congelado não existem em plano
   nenhum.** Os planos 01–06 param no `ConsoleAdapter`; `app/main.py`, os routers de
   `/api/*` e `app/channels/web.py` (o segundo adaptador da porta `ChannelAdapter`, que o
   próprio `app/contracts/channel.py` promete) não são criados por nenhum deles. Sem
   isso, o `openapi.json` gerado não existe e o teste de deriva da Task 3 não tem contra o
   que comparar. **É a dependência bloqueante desta frente.**
2. **O frame `{"type":"hello","last_index":N}` precisa ser aceito no WS de chat, com
   replay a partir do banco.** O congelado descreve cliente → servidor apenas como
   `{"type":"message","text":"..."}`. Não é mudança de rota — nenhuma deriva — mas é
   comportamento novo, e sem ele a janela de 37 s fica sem rede de segurança. O replay lê
   `messages` com `index > last_index`, em ordem de `index`, e é seguido do `TypingEvent`
   e do `StateEvent` correntes.
3. **`typing` é por turno, não por mensagem.** `ativo: true` no início do turno,
   `ativo: false` **depois** da última mensagem dele — inclusive depois das três de
   sistema. Se o backend desligar o typing ao despachar ①, o lead vê o aviso e 31 s de
   silêncio, e a Task 6 falha com razão.
4. **A mensagem do lead precisa voltar como `MessageEvent`**, com `id`, `index` e o
   `conteudo` mascarado. Sem esse eco não há reconciliação da bolha otimista, e a tela
   ficaria com uma bolha órfã em toda mensagem enviada.
5. **`ADMIN_TOKEN`, quando definido, precisa de um caminho para o WebSocket.** O
   navegador não deixa o cliente pôr cabeçalho no handshake de WS. Ou o token entra como
   query string em `/api/chat` e `/api/events`, ou o WS fica de fora da exigência com o
   motivo escrito — o bind em `127.0.0.1` continua sendo o controle que de fato importa
   (`DECISOES-FECHADAS.md` §8). Decisão do Núcleo, não da UI.
6. **O bundle de produção precisa ser servido pela mesma origem do backend** (montar
   `web/dist` como estático no FastAPI), senão `docker compose up` deixa de subir o
   produto inteiro em um comando e o invariante 14 quebra. O proxy do Vite resolve só o
   desenvolvimento.
