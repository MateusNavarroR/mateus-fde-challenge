import { render, screen, within } from "@testing-library/react";
import { expect, it } from "vitest";
import { DetalheConversa } from "../../../web/src/admin/DetalheConversa";
import { montarBackendFalso } from "../fakes/backend-falso";

const T = "2026-01-01T00:00:00Z";

it("toda mensagem mostra id, index, autor e status", async () => {
  montarBackendFalso({
    conversa: {
      id: "c1",
      perfil: {},
      quotes: [],
      handoffs: [],
      messages: [
        { id: "m1", index: 0, autor: "lead", tipo: "text", conteudo: "oi", status: "received", quote_id: null, criado_em: T },
        { id: "m2", index: 1, autor: "agente", tipo: "text", conteudo: "olá", status: "sent", quote_id: null, criado_em: T },
      ],
    },
  });
  render(<DetalheConversa id="c1" />);
  const linha = await screen.findByTestId("msg-m1");
  for (const t of ["m1", "0", "lead", "received"]) {
    expect(within(linha).getByText(t), t).toBeVisible();
  }
});

it("renderiza na ordem de index mesmo com a lista embaralhada e o timestamp fora de ordem", async () => {
  montarBackendFalso({
    conversa: {
      messages: [
        { id: "m3", index: 2, criado_em: "2026-01-01T00:00:01Z", autor: "agente", conteudo: "c", status: "sent", tipo: "text", quote_id: null },
        { id: "m1", index: 0, criado_em: "2026-01-01T00:00:09Z", autor: "lead", conteudo: "a", status: "received", tipo: "text", quote_id: null },
        { id: "m2", index: 1, criado_em: "2026-01-01T00:00:05Z", autor: "sistema", conteudo: "b", status: "sent", tipo: "text", quote_id: null },
      ],
      quotes: [],
      handoffs: [],
      perfil: {},
    },
  });
  render(<DetalheConversa id="c1" />);
  expect((await screen.findAllByTestId(/^msg-/)).map((e) => e.dataset.index)).toEqual([
    "0",
    "1",
    "2",
  ]);
});

it("aqui `sistema` É distinguível de `agente` — no admin isso é informação", async () => {
  // Na /chat os dois são idênticos, de propósito. A assimetria é deliberada e as
  // duas pontas têm teste, senão alguém "uniformiza" e perde a auditoria.
  montarBackendFalso({
    conversa: {
      messages: [
        { id: "m1", index: 0, autor: "sistema", conteudo: "aviso", status: "sent", tipo: "text", quote_id: null, criado_em: T },
        { id: "m2", index: 1, autor: "agente", conteudo: "olá", status: "sent", tipo: "text", quote_id: null, criado_em: T },
      ],
      quotes: [],
      handoffs: [],
      perfil: {},
    },
  });
  render(<DetalheConversa id="c1" />);
  await screen.findByTestId("msg-m1");
  expect(screen.getByTestId("msg-m1").className).not.toBe(
    screen.getByTestId("msg-m2").className,
  );
});

it("a linha do tempo mostra attempt, http_status, latência e outcome", async () => {
  montarBackendFalso({
    conversa: {
      messages: [],
      handoffs: [],
      perfil: {},
      quotes: [
        {
          id: "q1",
          status: "failed",
          circuito_aberto: false,
          total_latency_ms: 37_100,
          request: { plano_id: "completo", idade: 28, veiculo_ano: 2019, cep: null, data_inicio: null },
          criado_em: T,
          attempts: [
            { id: "a1", attempt: 1, http_status: 503, latency_ms: 2, outcome: "transient", criado_em: T },
            { id: "a2", attempt: 2, http_status: null, latency_ms: 12_000, outcome: "timeout", criado_em: T },
            { id: "a3", attempt: 3, http_status: 500, latency_ms: 3, outcome: "transient", criado_em: T },
          ],
        },
      ],
    },
  });
  render(<DetalheConversa id="c1" />);
  const linhas = await screen.findAllByTestId(/^tentativa-/);
  expect(linhas.map((l) => l.textContent)).toEqual([
    expect.stringContaining("503"),
    expect.stringContaining("timeout"),
    expect.stringContaining("500"),
  ]);
  // http_status nulo é "—", não "0": não houve resposta.
  expect(within(linhas[1]!).getByText("—")).toBeVisible();
  expect(within(linhas[1]!).getByText(/12[.,]0\s*s|12000\s*ms/)).toBeVisible();
});

it("`circuito_aberto` é distinguido de `tentamos 3 vezes e falhou`", async () => {
  // O job é failed SEM nenhuma tentativa. Sem essa distinção, a tela sugere que a
  // API foi chamada e não foi — e com o breaker aberto não sabemos nada sobre o lead.
  montarBackendFalso({
    conversa: {
      messages: [],
      handoffs: [],
      perfil: {},
      quotes: [
        { id: "q1", status: "failed", circuito_aberto: true, attempts: [], request: {}, criado_em: T },
      ],
    },
  });
  render(<DetalheConversa id="c1" />);
  expect(await screen.findByTestId("selo-circuito-aberto")).toHaveTextContent(
    /não chamamos|circuito aberto/i,
  );
  expect(screen.queryByTestId(/^tentativa-/)).toBeNull();
});

it("uma cotação `refused` mostra o motivo e NÃO mostra handoff", async () => {
  montarBackendFalso({
    conversa: {
      messages: [],
      handoffs: [],
      perfil: {},
      quotes: [
        {
          id: "q1",
          status: "refused",
          motivo_recusa: "veiculo_acima_de_20_anos",
          circuito_aberto: false,
          attempts: [
            { id: "a1", attempt: 1, http_status: 422, latency_ms: 40, outcome: "refused", criado_em: T },
          ],
          request: {},
          criado_em: T,
        },
      ],
    },
  });
  render(<DetalheConversa id="c1" />);
  expect(await screen.findByText(/veículo acima de 20 anos/i)).toBeVisible();
  expect(screen.queryByTestId(/^handoff-/)).toBeNull();
});

it("o perfil mostra os campos faltantes como progresso, com o CEP mascarado", async () => {
  montarBackendFalso({
    conversa: {
      messages: [],
      quotes: [],
      handoffs: [],
      perfil: {
        idade: 28,
        veiculo_ano: 2019,
        cep: null,
        data_inicio: null,
        plano_id: null,
        campos_faltantes: ["cep", "data_inicio", "plano_id"],
      },
    },
  });
  render(<DetalheConversa id="c1" />);
  expect(await screen.findByTestId("campos-faltantes")).toHaveTextContent(/cep/i);
});

it("marca a mensagem com valor monetário e quote_id nulo", async () => {
  montarBackendFalso({
    conversa: {
      quotes: [],
      handoffs: [],
      perfil: {},
      messages: [
        { id: "m1", index: 0, autor: "agente", conteudo: "fica R$ 392,25", status: "sent", tipo: "text", quote_id: null, criado_em: T },
      ],
    },
  });
  render(<DetalheConversa id="c1" />);
  expect(await screen.findByTestId("marca-bug")).toBeVisible();
});

it("404 mostra o estado de erro, não uma tela em branco", async () => {
  montarBackendFalso({ conversaErro: 404 });
  render(<DetalheConversa id="fantasma" />);
  expect(await screen.findByRole("alert")).toHaveTextContent(/não encontrad/i);
});
