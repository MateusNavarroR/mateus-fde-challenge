# Fatia 8 — As três telas de operação

**Objetivo:** o avaliador abre o admin e vê, sem rodar nada e sem acreditar em prosa:
cada mensagem com id e status; cada cotação com todas as suas tentativas (`attempt`,
`http_status`, latência, `outcome`); a saúde real da `/quote` com p50/p95 e o estado do
circuit breaker; o custo e a taxa de acerto de cache lidos da nossa própria base; e a
fila de handoff recebendo um caso novo **sem recarregar a página**.

**Arquitetura:** três telas sobre um layout comum. O layout carrega o badge de pendentes
e mantém **um** socket `/api/events` para a sessão inteira — não um por tela, senão o
badge pisca a cada navegação e o push some justamente enquanto o avaliador troca de aba.
Cada tela é leitura de um endpoint só, e o push do socket **invalida e recarrega**, nunca
sintetiza o item a partir do frame: um item montado no cliente diverge do que o banco tem
na primeira mudança de schema, e o admin existe para dizer a verdade sobre o banco.

**Depende de:** a fatia 7 (`web/src/api/`, o socket com reconexão, o teste de deriva) e
o estado real produzido pelo Núcleo até a fatia 6 — recusa, handoff e breaker precisam
existir para as telas terem o que mostrar.

**Escopo de arquivo:** **somente** `web/` e `tests/web/`. Nada em `app/`, `db/` ou
`docs/openapi.yaml`. As pendências do backend estão no fim, em **DEPENDÊNCIA PARA O
NÚCLEO**.

**Critério de pronto:**

1. `npm --prefix web run test` verde, incluindo a deriva do OpenAPI nos dois sentidos e
   o inventário de superfície consumida;
2. `npm --prefix web run e2e` verde, com as cinco evidências restantes gravadas em
   `docs/evidencia-ui/` a partir de estado real;
3. o painel de custo é uma **seção de `/admin/status` com título próprio e âncora**
   (`/admin/status#custo`), e mostra **"n/a"** onde `cache_read` é nulo;
4. existe o link `chat → admin` e **não existe** `admin → chat`.

> **`/frontend-design` na criação de cada tela, `/impeccable` na revisão.** Três telas
> densas de número são onde uma UI genérica mais custa: o avaliador precisa achar o
> breaker aberto em dois segundos.

---

## As quatro decisões que governam estas telas

Antes das tasks, porque cada uma vira asserção:

1. **O painel de custo é seção, não quinta tela** (`DECISOES-FECHADAS.md` §8). São seis
   números, e uma rota nova para seis números é escopo por escopo. Duas condições, e as
   duas são testadas: **bloco com título próprio e âncora**, não rodapé; e nomeado no
   README, porque é a parte que quase ninguém faz num take-home e não pode depender de o
   avaliador tropeçar nela.
2. **Navegação assimétrica.** `chat → admin` existe e é a demonstração inteira da
   rastreabilidade. `admin → chat` **não existe**: por ele o avaliador assumiria o lugar
   do lead numa conversa que já tem handoff, e isso não tem resposta boa. Há um teste
   negativo para isso, porque é o tipo de link que alguém adiciona "por simetria".
3. **A tela não abre arquivo de preço.** `custo_usd` e `pricing_vigencia` chegam
   calculados de `/api/usage` (`CLAUDE.md` 26). Se a UI recalculasse a partir de
   `config/model_pricing.yaml`, existiriam duas origens de preço e um custo histórico
   deixaria de ser auditável no dia em que a tabela mudasse.
4. **`cache_read` nulo é "n/a", nunca "0 %"** (`CLAUDE.md` 26, migração `0002`). Um zero
   ali diria "o cache não acertou" onde a verdade é "não existe cache neste caminho" — o
   Ollama não popula o campo. Isto é o teste mais barato desta fatia e o que mais
   facilmente se perde num `?? 0`.

---

## Task 1 — Cliente HTTP, `ADMIN_TOKEN` e o inventário de superfície

**Files:** Create `web/src/api/cliente.ts` · Modify `tests/web/unit/openapi-deriva.test.ts`
· Test `tests/web/unit/cliente.test.ts`

`ADMIN_TOKEN` é **opcional e exigido quando definido** (`CLAUDE.md` 14c). Sem ele a
aplicação sobe. O erro fácil aqui é mandar um cabeçalho vazio, que transforma um token
opcional em token obrigatório mal configurado.

- [ ] **Passo 1: teste que falha**

```ts
// tests/web/unit/cliente.test.ts
import { beforeEach, describe, expect, it, vi } from "vitest";
import { get, patch, ROTAS } from "../../web/src/api/cliente";

beforeEach(() => { localStorage.clear(); vi.restoreAllMocks(); });

it("sem token, nenhum cabeçalho de admin é enviado", async () => {
  const f = vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json({ items: [] }));
  await get(ROTAS.handoffs());
  expect([...new Headers(f.mock.calls[0]![1]!.headers).keys()]).not.toContain("x-admin-token");
});

it("com token gravado, o cabeçalho vai em toda chamada", async () => {
  localStorage.setItem("autoseguro.admin_token", "t-abc");
  const f = vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json({ items: [] }));
  await get(ROTAS.handoffs());
  expect(new Headers(f.mock.calls[0]![1]!.headers).get("x-admin-token")).toBe("t-abc");
});

it("401 vira um erro tipado, não um crash de parse", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("", { status: 401 }));
  await expect(get(ROTAS.status())).rejects.toMatchObject({ tipo: "nao_autorizado" });
});

it("409 na transição de handoff preserva a mensagem do backend", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    Response.json({ error: "transicao_invalida", message: "resolvido não volta para pendente" }, { status: 409 }));
  await expect(patch(ROTAS.handoff("h1"), { status: "pendente" }))
    .rejects.toMatchObject({ tipo: "conflito", message: /resolvido não volta/ });
});

it("backend fora do ar vira erro tipado, não uma tela em branco", async () => {
  vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("failed to fetch"));
  await expect(get(ROTAS.status())).rejects.toMatchObject({ tipo: "indisponivel" });
});

it("nenhuma rota é montada por concatenação solta de string", () => {
  // ROTAS é a superfície inteira que a UI consome. É ela que o teste de deriva lê.
  expect(Object.keys(ROTAS).sort()).toEqual(
    ["conversa", "conversas", "eventos", "handoff", "handoffs", "health", "status", "usage", "wsChat"].sort());
});
```

E, no arquivo da deriva, o terceiro teste — **o inventário**:

```ts
// tests/web/unit/openapi-deriva.test.ts  (acrescentar)
import { ROTAS } from "../../web/src/api/cliente";

it("toda rota que a UI consome está no contrato congelado", () => {
  const doContrato = Object.keys(congelado.paths);
  const template = (u: string) => u.replace(/\/[^/]*\$\{[^}]+\}/g, (m) => m.replace(/\$\{[^}]+\}/, "{id}"));
  for (const usada of Object.values(ROTAS).map((f) => template(String(f("id"))))) {
    const casa = doContrato.some((p) => p.replace(/\{[^}]+\}/g, "{id}") === usada.split("?")[0]);
    expect(casa, `${usada} não existe no openapi congelado`).toBe(true);
  }
});
```

- [ ] **Passo 2:** `npm --prefix web run test -- cliente deriva` → FAIL
- [ ] **Passo 3:** implementar `cliente.ts`. `ROTAS` é a **única** origem de URL do
      projeto — nenhum componente escreve `"/api/..."` no meio do JSX, porque é assim que
      uma rota escapa do inventário. Erros viram
      `{ tipo: "nao_autorizado" | "nao_encontrado" | "conflito" | "indisponivel" | "erro", message }`.
- [ ] **Passo 4:** `npm --prefix web run test -- cliente deriva` → PASS
- [ ] **Passo 5:** `git commit -m "feat(admin): cliente com ROTAS como origem única e ADMIN_TOKEN opcional"`

---

## Task 2 — O layout, o badge de pendentes e a navegação

**Files:** Create `web/src/admin/LayoutAdmin.tsx`, `web/src/admin/useEventos.ts` · Test
`tests/web/unit/layout-admin.test.tsx`

O badge é **visível de qualquer tela** — é o que faz a fila ser operada em vez de
consultada.

- [ ] **Passo 1: teste que falha**

```tsx
// tests/web/unit/layout-admin.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LayoutAdmin } from "../../web/src/admin/LayoutAdmin";
import { montarBackendFalso } from "../fakes/backend-falso";

it("o badge de pendentes aparece nas três telas", async () => {
  const srv = montarBackendFalso({ handoffs: { items: [], pendentes: 3 } });
  for (const rota of ["/admin/conversas", "/admin/status", "/admin/handoffs"]) {
    const { unmount } = render(<LayoutAdmin rota={rota} />);
    expect(await screen.findByTestId("badge-pendentes"), rota).toHaveTextContent("3");
    unmount();
  }
  srv.fechar();
});

it("o badge some quando não há pendente — zero não é informação, é ruído", async () => {
  montarBackendFalso({ handoffs: { items: [], pendentes: 0 } });
  render(<LayoutAdmin rota="/admin/status" />);
  expect(await screen.findByRole("navigation")).toBeVisible();
  expect(screen.queryByTestId("badge-pendentes")).toBeNull();
});

it("o badge sobe no push, sem recarregar", async () => {
  const srv = montarBackendFalso({ handoffs: { items: [], pendentes: 1 } });
  render(<LayoutAdmin rota="/admin/status" />);
  expect(await screen.findByTestId("badge-pendentes")).toHaveTextContent("1");
  srv.responderComPendentes(2);
  await srv.push({ type: "handoff.created", handoff: { id: "h9", status: "pendente" } });
  expect(await screen.findByTestId("badge-pendentes")).toHaveTextContent("2");
});

it("as três telas se ligam entre si", () => {
  render(<LayoutAdmin rota="/admin/status" />);
  const nav = screen.getByRole("navigation");
  for (const [nome, href] of [[/convers/i, "/admin/conversas"], [/status/i, "/admin/status"], [/handoff/i, "/admin/handoffs"]] as const) {
    expect(screen.getByRole("link", { name: nome })).toHaveAttribute("href", href);
  }
  expect(nav).toBeVisible();
});

it("NÃO existe link do admin para o chat (decisão fechada §8)", () => {
  // O inverso existe e é testado na fatia 7. Este é o teste negativo que impede
  // alguém de adicionar o link "por simetria" seis meses depois.
  const { container } = render(<LayoutAdmin rota="/admin/conversas" />);
  expect(container.querySelectorAll('a[href^="/chat"]')).toHaveLength(0);
});

it("um socket de eventos para a sessão inteira, não um por tela", () => {
  const srv = montarBackendFalso({});
  const { rerender } = render(<LayoutAdmin rota="/admin/conversas" />);
  rerender(<LayoutAdmin rota="/admin/handoffs" />);
  rerender(<LayoutAdmin rota="/admin/status" />);
  expect(srv.socketsAbertos).toBe(1);
});
```

- [ ] **Passo 2:** `npm --prefix web run test -- layout-admin` → FAIL
- [ ] **Passo 3:** implementar. `useEventos` usa o `conectarEventos` da fatia 7 (mesma
      reconexão com backoff) e expõe um assinador por tipo de evento. O layout mostra o
      estado da conexão: **um admin que perdeu o push e não avisa é pior que um admin sem
      push**, porque o operador confia numa fila parada.
- [ ] **Passo 4:** `npm --prefix web run test -- layout-admin` → PASS
- [ ] **Passo 5:** `git commit -m "feat(admin): layout com badge de pendentes e um socket por sessão"`

---

## Task 3 — `/admin/conversas`: a lista

**Files:** Create `web/src/admin/PaginaConversas.tsx` · Test
`tests/web/unit/pagina-conversas.test.tsx`

- [ ] **Passo 1: teste que falha**

```tsx
it("cada linha traz estado, total de mensagens e o desfecho da última cotação", async () => {
  montarBackendFalso({ conversas: { items: [
    { id: "c1", channel: "web", state: "encaminhado", criado_em: "...", total_mensagens: 7,
      atualizado_em: "...", ultima_mensagem: "Já passei sua conversa", handoff_pendente: true,
      ultima_cotacao_status: "failed" },
  ], next_cursor: null } });
  render(<PaginaConversas />);
  const linha = await screen.findByRole("row", { name: /c1/ });
  expect(within(linha).getByText("encaminhado")).toBeVisible();
  expect(within(linha).getByText("7")).toBeVisible();
  expect(within(linha).getByTestId("marca-handoff-pendente")).toBeVisible();
  expect(within(linha).getByText(/failed|falhou/i)).toBeVisible();
});

it("`refused` e `failed` são distinguíveis à primeira vista", async () => {
  // Recusa é desfecho de negócio e não gera handoff (§2); failed é indisponibilidade
  // e gera. Empilhar os dois no mesmo cinza apaga a decisão mais importante do produto.
  montarBackendFalso({ conversas: { items: [
    { id: "c1", ultima_cotacao_status: "refused", state: "fechado", total_mensagens: 4, handoff_pendente: false },
    { id: "c2", ultima_cotacao_status: "failed", state: "encaminhado", total_mensagens: 9, handoff_pendente: true },
  ], next_cursor: null } });
  render(<PaginaConversas />);
  const [a, b] = await screen.findAllByTestId("selo-cotacao");
  expect(a!.className).not.toBe(b!.className);
});

it("filtra por estado sem inventar valor de enum", async () => {
  const srv = montarBackendFalso({ conversas: { items: [], next_cursor: null } });
  render(<PaginaConversas />);
  await userEvent.selectOptions(await screen.findByLabelText(/estado/i), "encaminhado");
  expect(srv.ultimaUrl).toContain("state=encaminhado");
  expect([...screen.getByLabelText(/estado/i).querySelectorAll("option")].map((o) => o.value).filter(Boolean))
    .toEqual(["novo", "qualificando", "cotando", "cotado", "fechado", "encaminhado"]);
});

it("pagina por cursor, não por offset", async () => {
  const srv = montarBackendFalso({ conversas: { items: [{ id: "c1" }], next_cursor: "cur-2" } });
  render(<PaginaConversas />);
  await userEvent.click(await screen.findByRole("button", { name: /mais/i }));
  expect(srv.ultimaUrl).toContain("cursor=cur-2");
});

it("estado vazio explica o que fazer, sem parecer erro", async () => {
  montarBackendFalso({ conversas: { items: [], next_cursor: null } });
  render(<PaginaConversas />);
  expect(await screen.findByTestId("estado-vazio")).toHaveTextContent(/nenhuma conversa/i);
  expect(screen.queryByRole("alert")).toBeNull();
});
```

- [ ] **Passo 2:** `npm --prefix web run test -- pagina-conversas` → FAIL
- [ ] **Passo 3:** implementar; a linha inteira leva a `/admin/conversas/{id}`
- [ ] **Passo 4:** PASS
- [ ] **Passo 5:** `git commit -m "feat(admin): lista de conversas com filtro por estado e paginação por cursor"`

---

## Task 4 — O detalhe: mensagens com id e status, e a linha do tempo das tentativas

**Files:** Create `web/src/admin/DetalheConversa.tsx`,
`web/src/admin/LinhaDoTempoCotacao.tsx` · Test `tests/web/unit/detalhe-conversa.test.tsx`

É a resposta ao critério C4 numa tela só. A linha do tempo é a parte que prova que a
instabilidade foi **tratada**, e não apenas sobrevivida: três tentativas com `outcome`
diferente contam a política inteira sem uma linha de README.

- [ ] **Passo 1: teste que falha**

```tsx
it("toda mensagem mostra id, index, autor e status", async () => {
  montarBackendFalso({ conversa: { id: "c1", perfil: {}, quotes: [], handoffs: [], messages: [
    { id: "m1", index: 0, autor: "lead", tipo: "text", conteudo: "oi", status: "received", quote_id: null, criado_em: "..." },
    { id: "m2", index: 1, autor: "agente", tipo: "text", conteudo: "olá", status: "sent", quote_id: null, criado_em: "..." },
  ] } });
  render(<DetalheConversa id="c1" />);
  const linha = await screen.findByTestId("msg-m1");
  for (const t of ["m1", "0", "lead", "received"]) expect(within(linha).getByText(t)).toBeVisible();
});

it("renderiza na ordem de index mesmo com a lista embaralhada e o timestamp fora de ordem", async () => {
  montarBackendFalso({ conversa: { messages: [
    { id: "m3", index: 2, criado_em: "2026-01-01T00:00:01Z", autor: "agente", conteudo: "c", status: "sent", tipo: "text", quote_id: null },
    { id: "m1", index: 0, criado_em: "2026-01-01T00:00:09Z", autor: "lead", conteudo: "a", status: "received", tipo: "text", quote_id: null },
    { id: "m2", index: 1, criado_em: "2026-01-01T00:00:05Z", autor: "sistema", conteudo: "b", status: "sent", tipo: "text", quote_id: null },
  ], quotes: [], handoffs: [], perfil: {} } });
  render(<DetalheConversa id="c1" />);
  expect((await screen.findAllByTestId(/^msg-/)).map((e) => e.dataset.index)).toEqual(["0", "1", "2"]);
});

it("aqui `sistema` É distinguível de `agente` — no admin isso é informação", async () => {
  // Na /chat os dois são idênticos, de propósito. A assimetria é deliberada e as duas
  // pontas têm teste, senão alguém "uniformiza" e perde a auditoria.
  montarBackendFalso({ conversa: { messages: [
    { id: "m1", index: 0, autor: "sistema", conteudo: "aviso", status: "sent", tipo: "text", quote_id: null, criado_em: "..." },
    { id: "m2", index: 1, autor: "agente", conteudo: "olá", status: "sent", tipo: "text", quote_id: null, criado_em: "..." },
  ], quotes: [], handoffs: [], perfil: {} } });
  render(<DetalheConversa id="c1" />);
  expect(screen.getByTestId("msg-m1").className).not.toBe(screen.getByTestId("msg-m2").className);
});

it("a linha do tempo mostra attempt, http_status, latência e outcome", async () => {
  montarBackendFalso({ conversa: { messages: [], handoffs: [], perfil: {}, quotes: [{
    id: "q1", status: "failed", circuito_aberto: false, total_latency_ms: 37_100,
    request: { plano_id: "completo", idade: 28, veiculo_ano: 2019, cep: null, data_inicio: null },
    criado_em: "...", attempts: [
      { id: "a1", attempt: 1, http_status: 503, latency_ms: 2, outcome: "transient", criado_em: "..." },
      { id: "a2", attempt: 2, http_status: null, latency_ms: 12_000, outcome: "timeout", criado_em: "..." },
      { id: "a3", attempt: 3, http_status: 500, latency_ms: 3, outcome: "transient", criado_em: "..." },
    ] } ] } });
  render(<DetalheConversa id="c1" />);
  const linhas = await screen.findAllByTestId(/^tentativa-/);
  expect(linhas.map((l) => l.textContent)).toEqual([
    expect.stringContaining("503"), expect.stringContaining("timeout"), expect.stringContaining("500")]);
  expect(within(linhas[1]!).getByText("—")).toBeVisible();   // http_status nulo é "—", não "0"
  expect(within(linhas[1]!).getByText(/12[.,]0\s*s|12000\s*ms/)).toBeVisible();
});

it("`circuito_aberto` é distinguido de `tentamos 3 vezes e falhou`", async () => {
  // O job é failed SEM nenhuma tentativa. Sem essa distinção, a tela sugere que a API
  // foi chamada e não foi — e com o breaker aberto não sabemos nada sobre o lead.
  montarBackendFalso({ conversa: { messages: [], handoffs: [], perfil: {}, quotes: [
    { id: "q1", status: "failed", circuito_aberto: true, attempts: [], request: {}, criado_em: "..." }] } });
  render(<DetalheConversa id="c1" />);
  expect(await screen.findByTestId("selo-circuito-aberto")).toHaveTextContent(/não chamamos|circuito aberto/i);
  expect(screen.queryByTestId(/^tentativa-/)).toBeNull();
});

it("uma cotação `refused` mostra o motivo e NÃO mostra handoff", async () => {
  montarBackendFalso({ conversa: { messages: [], handoffs: [], perfil: {}, quotes: [
    { id: "q1", status: "refused", motivo_recusa: "veiculo_acima_de_20_anos", circuito_aberto: false,
      attempts: [{ id: "a1", attempt: 1, http_status: 422, latency_ms: 40, outcome: "refused", criado_em: "..." }],
      request: {}, criado_em: "..." }] } });
  render(<DetalheConversa id="c1" />);
  expect(await screen.findByText(/veículo acima de 20 anos/i)).toBeVisible();
  expect(screen.queryByTestId(/^handoff-/)).toBeNull();
});

it("o perfil mostra os campos faltantes como progresso, com o CEP mascarado", async () => {
  montarBackendFalso({ conversa: { messages: [], quotes: [], handoffs: [], perfil: {
    idade: 28, veiculo_ano: 2019, cep: null, data_inicio: null, plano_id: null,
    campos_faltantes: ["cep", "data_inicio", "plano_id"] } } });
  render(<DetalheConversa id="c1" />);
  expect(await screen.findByTestId("campos-faltantes")).toHaveTextContent(/cep/i);
});

it("marca a mensagem com valor monetário e quote_id nulo", async () => {
  montarBackendFalso({ conversa: { quotes: [], handoffs: [], perfil: {}, messages: [
    { id: "m1", index: 0, autor: "agente", conteudo: "fica R$ 392,25", status: "sent", tipo: "text", quote_id: null, criado_em: "..." }] } });
  render(<DetalheConversa id="c1" />);
  expect(await screen.findByTestId("marca-bug")).toBeVisible();
});

it("404 mostra o estado de erro, não uma tela em branco", async () => {
  montarBackendFalso({ conversaErro: 404 });
  render(<DetalheConversa id="fantasma" />);
  expect(await screen.findByRole("alert")).toHaveTextContent(/não encontrad/i);
});
```

- [ ] **Passo 2:** `npm --prefix web run test -- detalhe-conversa` → FAIL
- [ ] **Passo 3:** implementar. O mapa de `motivo_recusa` → texto de exibição vive numa
      constante da tela e cobre os **três** valores do enum; um `default` genérico
      esconderia um motivo novo, e o enum é fechado.
- [ ] **Passo 4:** PASS
- [ ] **Passo 5:** `git commit -m "feat(admin): detalhe com mensagens por index e linha do tempo das tentativas"`

---

## Task 5 — `/admin/status`: a saúde real da `/quote`

**Files:** Create `web/src/admin/PaginaStatus.tsx` · Test
`tests/web/unit/pagina-status.test.tsx`

- [ ] **Passo 1: teste que falha**

```tsx
it("mostra o /health do legado COM a ressalva de que ele mente", async () => {
  // O /health do legado responde 200 com 100% das cotações falhando. Exibi-lo sem a
  // nota é como se produz um monitor que mente (openapi.yaml, /api/health).
  montarBackendFalso({ status: { upstream_health: { status: "ok", latency_ms: 3, nota: "responde 200 mesmo com 100% das cotações falhando" },
    janela: { total: 50, sucesso: 0, taxa_sucesso: 0, p50_ms: 3, p95_ms: 8004, por_outcome: { transient: 50 } },
    breaker: { estado: "aberto", falhas_consecutivas: 12, aberto_desde: "...", reabre_em: "..." }, ultimas_tentativas: [] } });
  render(<PaginaStatus />);
  expect(await screen.findByTestId("upstream")).toHaveTextContent(/ok/);
  expect(screen.getByTestId("upstream")).toHaveTextContent(/mesmo com 100% das cotações falhando/);
});

it("o breaker aberto é o elemento mais visível da tela", async () => {
  montarBackendFalso({ status: { breaker: { estado: "aberto", falhas_consecutivas: 12, aberto_desde: "2026-01-01T10:00:00Z", reabre_em: "2026-01-01T10:00:20Z" },
    janela: { total: 50, sucesso: 0, taxa_sucesso: 0, p50_ms: 3, p95_ms: 8004 }, upstream_health: { status: "ok" }, ultimas_tentativas: [] } });
  render(<PaginaStatus />);
  const b = await screen.findByTestId("breaker");
  expect(b).toHaveAttribute("data-estado", "aberto");
  expect(b).toHaveTextContent(/reabre/i);          // quando reabre, não só que abriu
  expect(b).toHaveTextContent("12");
});

it("os três estados do breaker são visualmente distintos", async () => {
  const classes = new Set<string>();
  for (const estado of ["fechado", "aberto", "meia_abertura"]) {
    montarBackendFalso({ status: { breaker: { estado, falhas_consecutivas: 0 }, janela: { total: 1, sucesso: 1, taxa_sucesso: 1, p50_ms: 3, p95_ms: 3 }, upstream_health: { status: "ok" }, ultimas_tentativas: [] } });
    const { unmount } = render(<PaginaStatus />);
    classes.add((await screen.findByTestId("breaker")).className);
    unmount();
  }
  expect(classes.size).toBe(3);
});

it("p95 é exibido junto de p50 e taxa de sucesso", async () => {
  montarBackendFalso({ status: { janela: { total: 50, sucesso: 45, taxa_sucesso: 0.9, p50_ms: 120, p95_ms: 8004, por_outcome: { ok: 45, timeout: 3, transient: 2 } },
    breaker: { estado: "fechado", falhas_consecutivas: 0 }, upstream_health: { status: "ok" }, ultimas_tentativas: [] } });
  render(<PaginaStatus />);
  expect(await screen.findByTestId("taxa-sucesso")).toHaveTextContent("90");
  expect(screen.getByTestId("p50")).toHaveTextContent(/120/);
  expect(screen.getByTestId("p95")).toHaveTextContent(/8[.,]0\s*s|8004/);  // as lentas de 8s aparecem
  expect(screen.getByTestId("por-outcome")).toHaveTextContent(/timeout/);
});

it("cada tentativa recente leva à conversa que a originou", async () => {
  montarBackendFalso({ status: { ultimas_tentativas: [
    { id: "a1", attempt: 2, http_status: null, latency_ms: 12_000, outcome: "timeout", criado_em: "...", quote_id: "q1", conversation_id: "c7" }],
    janela: { total: 1, sucesso: 0, taxa_sucesso: 0, p50_ms: 12000, p95_ms: 12000 },
    breaker: { estado: "fechado", falhas_consecutivas: 1 }, upstream_health: { status: "ok" } } });
  render(<PaginaStatus />);
  expect(await screen.findByRole("link", { name: /c7/ })).toHaveAttribute("href", "/admin/conversas/c7");
});

it("upstream inalcançável não some da tela nem vira zero", async () => {
  montarBackendFalso({ status: { upstream_health: { status: "unreachable", latency_ms: null },
    janela: { total: 0, sucesso: 0, taxa_sucesso: 0, p50_ms: 0, p95_ms: 0 },
    breaker: { estado: "aberto", falhas_consecutivas: 5 }, ultimas_tentativas: [] } });
  render(<PaginaStatus />);
  expect(await screen.findByTestId("upstream")).toHaveTextContent(/inalcanç/i);
});
```

- [ ] **Passo 2:** `npm --prefix web run test -- pagina-status` → FAIL
- [ ] **Passo 3:** implementar; a tela recarrega a cada `quote.attempt` recebido pelo
      socket, com *debounce*, senão um cenário degradado a repinta dezenas de vezes por
      segundo
- [ ] **Passo 4:** PASS
- [ ] **Passo 5:** `git commit -m "feat(admin): saúde da /quote com p50/p95 e estado do breaker"`

---

## Task 6 — O painel de custo, seção de `/admin/status`

**Files:** Create `web/src/admin/PainelCusto.tsx` · Modify `web/src/admin/PaginaStatus.tsx`
· Test `tests/web/unit/painel-custo.test.tsx`

Seção com **título próprio e âncora**, não rodapé (`DECISOES-FECHADAS.md` §8). E a
regra que mais fácil se perde num `?? 0`: **`cache_read` nulo é "n/a"**.

- [ ] **Passo 1: teste que falha**

```tsx
it("é uma seção com título próprio e âncora, não um rodapé", async () => {
  montarBackendFalso({ usage: usageMinimo() });
  render(<PaginaStatus />);
  const secao = await screen.findByRole("region", { name: /custo/i });
  expect(secao).toHaveAttribute("id", "custo");
  expect(within(secao).getByRole("heading", { level: 2 })).toBeVisible();
});

it("cache_read nulo mostra n/a, NUNCA 0 %", async () => {
  // O Ollama não popula cache_read. Zero diria "o cache não acertou"; a verdade é
  // "não existe cache neste caminho" (CLAUDE.md 26, migração 0002).
  montarBackendFalso({ usage: { total: { tokens_in: 900, tokens_out: 120, cache_read: null, cache_write: null, taxa_acerto_cache: null, custo_usd: null, pricing_vigencia: null, latency_p50_ms: 800 }, por_provider: [], por_conversa: [] } });
  render(<PaginaStatus />);
  const secao = await screen.findByRole("region", { name: /custo/i });
  expect(within(secao).getByTestId("taxa-cache")).toHaveTextContent("n/a");
  expect(within(secao).getByTestId("taxa-cache")).not.toHaveTextContent("0");
  expect(within(secao).getByTestId("custo-total")).toHaveTextContent("n/a");
});

it("cache_read zero de verdade mostra 0 % — n/a e zero são coisas diferentes", async () => {
  montarBackendFalso({ usage: { total: { tokens_in: 900, tokens_out: 120, cache_read: 0, cache_write: 0, taxa_acerto_cache: 0, custo_usd: 0.004, pricing_vigencia: "2026-01-15", latency_p50_ms: 800 }, por_provider: [], por_conversa: [] } });
  render(<PaginaStatus />);
  expect(within(await screen.findByRole("region", { name: /custo/i })).getByTestId("taxa-cache")).toHaveTextContent("0");
});

it("mostra Anthropic e Ollama lado a lado, cada um com o seu tratamento de cache", async () => {
  montarBackendFalso({ usage: { total: { tokens_in: 3000, tokens_out: 400, cache_read: 2100, cache_write: 900, taxa_acerto_cache: 0.7, custo_usd: 0.0123, pricing_vigencia: "2026-01-15", latency_p50_ms: 900 },
    por_provider: [
      { provider: "anthropic", tokens_in: 2000, tokens_out: 300, cache_read: 2100, cache_write: 900, taxa_acerto_cache: 0.7, custo_usd: 0.0123, pricing_vigencia: "2026-01-15", latency_p50_ms: 900 },
      { provider: "ollama", tokens_in: 1000, tokens_out: 100, cache_read: null, cache_write: null, taxa_acerto_cache: null, custo_usd: null, pricing_vigencia: null, latency_p50_ms: 1500 }],
    por_conversa: [] } });
  render(<PaginaStatus />);
  const secao = await screen.findByRole("region", { name: /custo/i });
  expect(within(secao).getByRole("row", { name: /anthropic/i })).toHaveTextContent("70");
  expect(within(secao).getByRole("row", { name: /ollama/i })).toHaveTextContent("n/a");
});

it("o custo mostra a vigência do preço — sem procedência é um número solto", async () => {
  montarBackendFalso({ usage: usageComCusto("2026-01-15") });
  render(<PaginaStatus />);
  expect(within(await screen.findByRole("region", { name: /custo/i })).getByTestId("vigencia"))
    .toHaveTextContent("2026-01-15");
});

it("a tela NÃO abre config/model_pricing.yaml nem multiplica token por preço", async () => {
  // O custo vem calculado do backend (CLAUDE.md 26). Duas origens de preço é como um
  // custo histórico deixa de ser auditável.
  const fonte = readFileSync("web/src/admin/PainelCusto.tsx", "utf8");
  expect(fonte).not.toMatch(/model_pricing|per_million|\* *1_?000_?000|preco_por_token/i);
});

it("o custo por conversa liga para o detalhe da conversa", async () => {
  montarBackendFalso({ usage: { total: {...}, por_provider: [], por_conversa: [
    { conversation_id: "c7", turnos: 6, tokens_in: 900, tokens_out: 200, cache_read: 700, cache_write: 200, taxa_acerto_cache: 0.78, custo_usd: 0.0031, pricing_vigencia: "2026-01-15", latency_p50_ms: 800 }] } });
  render(<PaginaStatus />);
  expect(await screen.findByRole("link", { name: /c7/ })).toHaveAttribute("href", "/admin/conversas/c7");
});

it("sem nenhum turno gravado, a seção existe e explica — não some", async () => {
  montarBackendFalso({ usage: { total: { tokens_in: 0, tokens_out: 0, cache_read: null, cache_write: null, taxa_acerto_cache: null, custo_usd: null, pricing_vigencia: null, latency_p50_ms: null }, por_provider: [], por_conversa: [] } });
  render(<PaginaStatus />);
  const secao = await screen.findByRole("region", { name: /custo/i });
  expect(within(secao).getByTestId("estado-vazio")).toBeVisible();
});
```

- [ ] **Passo 2:** `npm --prefix web run test -- painel-custo` → FAIL
- [ ] **Passo 3:** implementar. Um único helper `formatarOuNa(v, formatador)` que devolve
      `"n/a"` para `null | undefined` e formata o resto — **o `??` proibido não é uma
      regra de estilo, é o invariante 26 escrito em código**. `/admin/status#custo` rola
      até a seção ao carregar com a âncora.
- [ ] **Passo 4:** PASS
- [ ] **Passo 5:** `git commit -m "feat(admin): painel de custo como seção ancorada, com n/a onde não há cache"`

---

## Task 7 — `/admin/handoffs`: a fila operável e o push

**Files:** Create `web/src/admin/PaginaHandoffs.tsx` · Test
`tests/web/unit/pagina-handoffs.test.tsx`

Sem o `PATCH`, a fila não é operável — é só uma lista que cresce (`openapi.yaml`).

- [ ] **Passo 1: teste que falha**

```tsx
it("cada item mostra o gatilho, o motivo e quem disparou", async () => {
  montarBackendFalso({ handoffs: { pendentes: 1, items: [{ id: "h1", conversation_id: "c7",
    trigger: "cotacao_indisponivel", reason: "job de cotação terminou failed", summary: null,
    disparado_por: "regra", quote_id: "q1", ultima_cotacao: null, status: "pendente", criado_em: "...",
    assumido_em: null, resolved_at: null }] } });
  render(<PaginaHandoffs />);
  const item = await screen.findByTestId("handoff-h1");
  expect(within(item).getByText(/cotacao_indisponivel|cotação indisponível/i)).toBeVisible();
  expect(within(item).getByTestId("disparado-por")).toHaveTextContent(/regra/);
});

it("distingue gatilho de regra de decisão do modelo", async () => {
  // Um gatilho determinístico e uma decisão do modelo produzem o mesmo sinal, e a fila
  // distingue os dois (openapi.yaml, Handoff.disparado_por).
  montarBackendFalso({ handoffs: { pendentes: 2, items: [
    { id: "h1", disparado_por: "regra", trigger: "cotacao_indisponivel", status: "pendente", conversation_id: "c1", reason: "", criado_em: "..." },
    { id: "h2", disparado_por: "modelo", trigger: "assunto_sensivel", status: "pendente", conversation_id: "c2", reason: "", criado_em: "..." }] } });
  render(<PaginaHandoffs />);
  const [a, b] = await screen.findAllByTestId("disparado-por");
  expect(a!.textContent).not.toBe(b!.textContent);
});

it("assumir e resolver chamam o PATCH e refletem na hora", async () => {
  const srv = montarBackendFalso({ handoffs: { pendentes: 1, items: [{ id: "h1", status: "pendente", conversation_id: "c1", trigger: "lead_pediu_atendente", disparado_por: "regra", reason: "", criado_em: "..." }] } });
  render(<PaginaHandoffs />);
  await userEvent.click(await screen.findByRole("button", { name: /assumir/i }));
  expect(srv.ultimoPatch).toEqual(["/api/handoffs/h1", { status: "assumido" }]);
  expect(await screen.findByRole("button", { name: /resolver/i })).toBeVisible();
});

it("não oferece transição inválida — resolvido não volta", async () => {
  montarBackendFalso({ handoffs: { pendentes: 0, items: [{ id: "h1", status: "resolvido", conversation_id: "c1", trigger: "lead_pediu_atendente", disparado_por: "regra", reason: "", criado_em: "..." }] } });
  render(<PaginaHandoffs />);
  const item = await screen.findByTestId("handoff-h1");
  expect(within(item).queryByRole("button", { name: /assumir|resolver/i })).toBeNull();
});

it("409 do backend aparece como mensagem, e o item volta ao estado real", async () => {
  const srv = montarBackendFalso({ handoffs: { pendentes: 1, items: [{ id: "h1", status: "pendente", conversation_id: "c1", trigger: "guardrail", disparado_por: "regra", reason: "", criado_em: "..." }] }, patchErro: 409 });
  render(<PaginaHandoffs />);
  await userEvent.click(await screen.findByRole("button", { name: /assumir/i }));
  expect(await screen.findByRole("alert")).toBeVisible();
  expect(await screen.findByRole("button", { name: /assumir/i })).toBeVisible();
});

it("um handoff criado no backend entra na fila SEM reload", async () => {
  const srv = montarBackendFalso({ handoffs: { pendentes: 0, items: [] } });
  render(<PaginaHandoffs />);
  expect(await screen.findByTestId("estado-vazio")).toBeVisible();
  srv.responderComHandoff({ id: "h9", status: "pendente", conversation_id: "c9", trigger: "cotacao_indisponivel", disparado_por: "regra", reason: "", criado_em: "..." });
  await srv.push({ type: "handoff.created", handoff: { id: "h9" } });
  expect(await screen.findByTestId("handoff-h9")).toBeVisible();
});

it("o push recarrega do backend, não monta o item a partir do frame", async () => {
  // Item montado no cliente diverge do banco na primeira mudança de schema — e o
  // admin existe para dizer a verdade sobre o banco.
  const srv = montarBackendFalso({ handoffs: { pendentes: 0, items: [] } });
  render(<PaginaHandoffs />);
  const antes = srv.chamadas("/api/handoffs");
  await srv.push({ type: "handoff.created", handoff: { id: "h9" } });
  expect(srv.chamadas("/api/handoffs")).toBe(antes + 1);
});

it("cada item leva à conversa de origem — e não ao /chat", async () => {
  montarBackendFalso({ handoffs: { pendentes: 1, items: [{ id: "h1", conversation_id: "c7", status: "pendente", trigger: "guardrail", disparado_por: "regra", reason: "", criado_em: "..." }] } });
  const { container } = render(<PaginaHandoffs />);
  expect(await screen.findByRole("link", { name: /c7/ })).toHaveAttribute("href", "/admin/conversas/c7");
  expect(container.querySelectorAll('a[href^="/chat"]')).toHaveLength(0);
});
```

- [ ] **Passo 2:** `npm --prefix web run test -- pagina-handoffs` → FAIL
- [ ] **Passo 3:** implementar. Os rótulos cobrem os **sete** gatilhos da tabela fechada
      (`DECISOES-FECHADAS.md` §3) — `cotacao_recusada` não está entre eles, porque
      **recusa não vira handoff**; um teste garante que a tela não tem rótulo para ele.
- [ ] **Passo 4:** PASS
- [ ] **Passo 5:** `git commit -m "feat(admin): fila de handoff operável com push em tempo real"`

---

## Task 8 — Estados vazios, estados de erro e responsivo

**Files:** Create `web/src/ui/Vazio.tsx`, `web/src/ui/Erro.tsx` · Modify as três telas ·
Test `tests/web/unit/estados.test.tsx`

Vazio e erro são estados de produto, não sobras. Num admin, o vazio é o **primeiro**
estado que o avaliador vê, porque ele acabou de subir o compose.

- [ ] **Passo 1: teste que falha**

```tsx
it.each(["/admin/conversas", "/admin/status", "/admin/handoffs"])(
  "%s: vazio explica e não parece erro", async (rota) => {
    montarBackendFalso({ tudoVazio: true });
    render(<Admin rota={rota} />);
    expect(await screen.findByTestId("estado-vazio")).toBeVisible();
    expect(screen.queryByRole("alert")).toBeNull();
  });

it.each(["/admin/conversas", "/admin/status", "/admin/handoffs"])(
  "%s: backend fora mostra erro com o que fazer, não tela em branco", async (rota) => {
    montarBackendFalso({ indisponivel: true });
    render(<Admin rota={rota} />);
    const alerta = await screen.findByRole("alert");
    expect(alerta).toHaveTextContent(/docker compose|indisponível/i);
    expect(within(alerta).getByRole("button", { name: /tentar de novo/i })).toBeVisible();
  });

it("401 pede o ADMIN_TOKEN em vez de repetir 'erro'", async () => {
  montarBackendFalso({ status401: true });
  render(<Admin rota="/admin/status" />);
  expect(await screen.findByLabelText(/token/i)).toBeVisible();
});

it.each([[1440, 900], [390, 844]])("não há rolagem horizontal em %ix%i", async (w, h) => {
  window.innerWidth = w; window.innerHeight = h;
  montarBackendFalso({ populado: true });
  const { container } = render(<Admin rota="/admin/conversas" />);
  await screen.findByRole("table");
  const raiz = container.firstElementChild as HTMLElement;
  expect(raiz.scrollWidth).toBeLessThanOrEqual(raiz.clientWidth);
});
```

- [ ] **Passo 2:** `npm --prefix web run test -- estados` → FAIL
- [ ] **Passo 3:** implementar. Em 390 px a tabela vira lista de cartões — `overflow-x`
      numa tabela larga passaria o teste de `scrollWidth` do container e ainda assim
      seria ilegível no celular; o teste de largura é piso, não teto, e o Playwright da
      Task 9 confere no navegador de verdade.
- [ ] **Passo 4:** PASS
- [ ] **Passo 5:** `git commit -m "feat(admin): estados vazios, estados de erro e layout responsivo"`

---

## Task 9 — As cinco evidências restantes

**Files:** Create `tests/web/e2e/handoff-tempo-real.spec.ts`, `status-breaker.spec.ts`,
`responsivo.spec.ts`, `estados.spec.ts`

Sete evidências ao todo; a fatia 7 gravou `03` e `04`. **Cada uma declara o comando que
produz o estado real** — screenshot com dado de exemplo não vale, e é o motivo de a frente
de Frontend só abrir depois da fatia 4 (`DECISOES-FECHADAS.md` §7).

| # | Arquivo | Comando que produz o estado |
|---|---|---|
| 01 | `01-handoff-tempo-real.png` | `QUOTE_FAILURE_RATE=1.0 docker compose up -d --force-recreate quote-api` + uma conversa dirigida pelo Playwright numa segunda aba |
| 02 | `02-status-breaker-aberto.png` | idem, mais 6 cotações seguidas até o breaker abrir (`breaker_limiar=5`) |
| 03 | `03-chat-degradacao.png` | **fatia 7**, Task 8 |
| 04 | `04-chat-cotacao.png` | **fatia 7**, Task 8 |
| 05 | `05-responsivo-1440.png` · `05-responsivo-390.png` | `scripts/seed_demo.sh` (dump de exemplo) nas quatro telas |
| 06 | `06-estados-vazios.png` | `docker compose down -v && docker compose up -d` — banco recriado, zero linha |
| 07 | `07-estados-de-erro.png` | `docker compose stop app` com o front no ar |

- [ ] **Passo 1: teste que falha**

```ts
// tests/web/e2e/handoff-tempo-real.spec.ts
test("um handoff criado no backend aparece na fila sem reload", async ({ page, context }) => {
  await subirCenario("degradado");                       // QUOTE_FAILURE_RATE=1.0
  await page.goto("/admin/handoffs");
  const antes = await page.getByTestId(/^handoff-/).count();
  const navegacoes: string[] = [];
  page.on("framenavigated", (f) => navegacoes.push(f.url()));

  const lead = await context.newPage();                  // o estado nasce de uma conversa real
  await lead.goto("/chat");
  await lead.getByRole("button", { name: /nova conversa/i }).click();
  await lead.getByRole("textbox").fill("28 anos, carro 2019, cep 07XXX-XXX, completo, começo dia 17/10");
  await lead.getByRole("textbox").press("Enter");

  await expect(page.getByTestId(/^handoff-/)).toHaveCount(antes + 1, { timeout: 60_000 });
  await expect(page.getByTestId("badge-pendentes")).toHaveText(String(antes + 1));
  expect(navegacoes, "a fila recarregou a página — o push não funcionou").toEqual([]);
  await page.screenshot({ path: "docs/evidencia-ui/01-handoff-tempo-real.png", fullPage: true });
});
```

```ts
// tests/web/e2e/status-breaker.spec.ts
test("status com a /quote em falha total e o breaker aberto", async ({ page, context }) => {
  await subirCenario("degradado");
  await dispararCotacoes(context, 6);                    // acima do breaker_limiar=5
  await page.goto("/admin/status");
  await expect(page.getByTestId("breaker")).toHaveAttribute("data-estado", "aberto");
  await expect(page.getByTestId("taxa-sucesso")).toHaveText(/0\s*%/);
  await expect(page.getByTestId("p95")).not.toHaveText("0");
  await expect(page.getByTestId("upstream")).toContainText(/ok/);        // o legado ainda diz ok
  await expect(page.getByTestId(/^tentativa-/).first()).toContainText(/50[0235]|timeout/);
  await page.screenshot({ path: "docs/evidencia-ui/02-status-breaker-aberto.png", fullPage: true });
});

test("a seção de custo está na mesma tela, com âncora própria", async ({ page }) => {
  await page.goto("/admin/status#custo");
  const secao = page.getByRole("region", { name: /custo/i });
  await expect(secao).toBeInViewport();
  await expect(secao.getByTestId("vigencia")).toContainText(/\d{4}-\d{2}-\d{2}|n\/a/);
});
```

```ts
// tests/web/e2e/responsivo.spec.ts
for (const [nome, w, h] of [["1440", 1440, 900], ["390", 390, 844]] as const) {
  test(`sem rolagem horizontal em ${nome}px, nas quatro telas`, async ({ page }) => {
    await popularComDumpDeExemplo();
    await page.setViewportSize({ width: w, height: h });
    for (const rota of ["/chat", "/admin/conversas", "/admin/status", "/admin/handoffs"]) {
      await page.goto(rota);
      const sobra = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(sobra, `${rota} rola na horizontal em ${nome}px`).toBeLessThanOrEqual(0);
    }
    await page.goto("/admin/conversas");
    await page.screenshot({ path: `docs/evidencia-ui/05-responsivo-${nome}.png`, fullPage: true });
  });
}
```

```ts
// tests/web/e2e/estados.spec.ts
test("estados vazios com o banco recém-criado", async ({ page }) => {
  await recriarBancoVazio();                             // docker compose down -v && up -d
  for (const rota of ["/admin/conversas", "/admin/status", "/admin/handoffs"]) {
    await page.goto(rota);
    await expect(page.getByTestId("estado-vazio")).toBeVisible();
    await expect(page.getByRole("alert")).toHaveCount(0); // vazio não é erro
  }
  await page.goto("/admin/conversas");
  await page.screenshot({ path: "docs/evidencia-ui/06-estados-vazios.png", fullPage: true });
});

test("estados de erro com o backend parado", async ({ page }) => {
  await pararBackend();                                  // docker compose stop app
  await page.goto("/admin/status");
  await expect(page.getByRole("alert")).toContainText(/indisponível|docker compose/i);
  await page.goto("/chat");
  await expect(page.getByRole("status")).toContainText(/reconectando/i);
  await page.screenshot({ path: "docs/evidencia-ui/07-estados-de-erro.png", fullPage: true });
  await religarBackend();
});
```

- [ ] **Passo 2:** `npm --prefix web run e2e` → FAIL
- [ ] **Passo 3:** implementar os auxiliares em `tests/web/e2e/ajuda/` e ajustar as telas
      até passarem, **sem afrouxar asserção**. Tudo em série (`workers: 1`): as suítes que
      dependem de `QUOTE_SEED` nunca rodam em paralelo (`CLAUDE.md`, reprodutibilidade).
- [ ] **Passo 4:** `npm --prefix web run e2e` → PASS, e os oito PNG existem em
      `docs/evidencia-ui/`
- [ ] **Passo 5:** `git commit -m "test(web): as sete evidências, cada uma a partir de estado real"`

---

## Task 10 — Fechar a fatia e a frente

- [ ] **Passo 1:** `npm --prefix web run test` e `npm --prefix web run e2e` → verdes
- [ ] **Passo 2:** com o backend no ar,
      `npm --prefix web run openapi:baixar && npm --prefix web run test -- deriva` →
      PASS nos dois sentidos, mais o inventário de superfície consumida
- [ ] **Passo 3:** a varredura de PII sobre tudo que a frente escreveu, inclusive as
      imagens gravadas nesta fatia:

```bash
rg -n '[0-9]{3}\.[0-9]{3}\.[0-9]{3}-[0-9]{2}|@[a-z]+\.(com|br)|\+55' web tests/web
```

Esperado: **nada**. E abrir os oito PNG conferindo que o que aparece na tela é a versão
**mascarada** — não porque a screenshot precisa ser limpa, mas porque **é o comportamento
correto do produto**: não existe endpoint que devolva a crua, e a evidência mostra o
sistema como ele é, não uma versão especial para foto.

- [ ] **Passo 4:** conferir a assimetria de navegação de uma vez:

```bash
rg -n 'href="/chat' web/src/admin && echo "REGRESSÃO: admin → chat não existe" && exit 1
rg -q 'ver esta conversa no admin' web/src/chat || { echo "faltou o link chat → admin"; exit 1; }
```

- [ ] **Passo 5:** **invocar `/impeccable` sobre as três telas** e aplicar o que ela
      apontar sem quebrar teste; regravar as evidências afetadas
- [ ] **Passo 6:** relatar: o que ficou pronto, o comando que provou, a saída, e o que
      ficou de fora — **e que a frente de Frontend está completa**
- [ ] **Passo 7:** `git commit -m "chore: fatia 8 fechada — as três telas de operação e o painel de custo"`

---

## DEPENDÊNCIA PARA O NÚCLEO

Não são tasks deste plano. São coisas em `app/` que estas telas pressupõem e que nenhum
dos planos 01 a 06 cria.

1. **As seis rotas REST e o WS `/api/events` não são criados por plano nenhum.** Vale o
   mesmo item nº 1 da fatia 7: `app/main.py` e os routers não existem, e sem eles não há
   `openapi.json` gerado nem tela alguma. **Bloqueante.**
2. **`/api/events` precisa de forma de frame definida.** O congelado nomeia os três
   eventos (`handoff.created`, `handoff.updated`, `quote.attempt`) mas não a forma do
   envelope. A UI assume `{"type": "<nome>", ...}` e **só usa o `type`** — o corpo é
   ignorado de propósito, porque a tela recarrega do endpoint em vez de montar o item.
   Basta o Núcleo garantir o campo `type`.
3. **`/api/usage` precisa devolver custo já calculado**, com `pricing_vigencia`, e
   **`cache_read`/`taxa_acerto_cache` nulos — nunca zero** — quando o provider não
   reporta caching. Um `COALESCE(cache_read, 0)` no SQL do agregado apagaria a distinção
   inteira do invariante 26, e o teste da Task 6 passaria a mentir junto com o backend.
4. **`/api/quote-health` precisa popular `ultimas_tentativas[].conversation_id`** e
   `breaker.reabre_em`. Sem o primeiro não há link para a conversa de origem — que é a
   navegação que demonstra rastreabilidade; sem o segundo a tela diz que o breaker abriu
   mas não quando volta, que é a única informação acionável ali.
5. **`PATCH /api/handoffs/{id}` precisa recusar transição inválida com 409** e o corpo
   `Erro`. Se ele aceitar tudo, a fila deixa de ter estado confiável e o teste de 409
   passa a ser inverificável do lado da UI.
6. **`ADMIN_TOKEN` como `X-Admin-Token` nas rotas REST**, exigido apenas quando definido
   (`CLAUDE.md` 14c) — e a mesma pendência da fatia 7 sobre o handshake do WebSocket, que
   não aceita cabeçalho no navegador.
7. **`config/model_pricing.yaml` precisa ter uma entrada para o modelo em uso**, senão
   `custo_usd` sai `NULL` (correto, por construção) e o painel mostra "n/a" no lugar do
   número que ele existe para provar. Não é bug da UI, mas é o que faria a evidência 02
   parecer vazia.
8. **`scripts/seed_demo.sh` (dump de exemplo) não existe em plano nenhum**, e a evidência
   05 depende dele para ter as telas populadas — e `eval_runs` fica **fora** desse dump
   (`DECISOES-FECHADAS.md` §9): nenhuma das telas mostra avaliação, e linha que ninguém vê
   não justifica alguém ler um juízo de LLM como métrica de produto.
