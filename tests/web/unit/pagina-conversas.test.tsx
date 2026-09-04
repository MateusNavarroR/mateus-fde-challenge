import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { PaginaConversas } from "../../../web/src/admin/PaginaConversas";
import { montarBackendFalso } from "../fakes/backend-falso";

const linha = (extra: Record<string, unknown>) => ({
  channel: "web",
  criado_em: "2026-01-01T00:00:00Z",
  atualizado_em: "2026-01-01T00:00:00Z",
  ...extra,
});

it("cada linha traz estado, total de mensagens e o desfecho da última cotação", async () => {
  montarBackendFalso({
    conversas: {
      items: [
        linha({
          id: "c1",
          state: "encaminhado",
          total_mensagens: 7,
          ultima_mensagem: "Já passei sua conversa",
          handoff_pendente: true,
          ultima_cotacao_status: "failed",
        }),
      ],
      next_cursor: null,
    },
  });
  render(<PaginaConversas />);
  const l = await screen.findByRole("row", { name: /c1/ });
  expect(within(l).getByText("encaminhado")).toBeVisible();
  expect(within(l).getByText("7")).toBeVisible();
  expect(within(l).getByTestId("marca-handoff-pendente")).toBeVisible();
  expect(within(l).getByText(/failed|falhou/i)).toBeVisible();
});

it("`refused` e `failed` são distinguíveis à primeira vista", async () => {
  // Recusa é desfecho de negócio e não gera handoff (§2); failed é
  // indisponibilidade e gera. Empilhar os dois no mesmo cinza apaga a decisão
  // mais importante do produto.
  montarBackendFalso({
    conversas: {
      items: [
        linha({
          id: "c1",
          ultima_cotacao_status: "refused",
          state: "fechado",
          total_mensagens: 4,
          handoff_pendente: false,
        }),
        linha({
          id: "c2",
          ultima_cotacao_status: "failed",
          state: "encaminhado",
          total_mensagens: 9,
          handoff_pendente: true,
        }),
      ],
      next_cursor: null,
    },
  });
  render(<PaginaConversas />);
  const [a, b] = await screen.findAllByTestId("selo-cotacao");
  expect(a!.className).not.toBe(b!.className);
});

it("filtra por estado sem inventar valor de enum", async () => {
  const srv = montarBackendFalso({ conversas: { items: [], next_cursor: null } });
  render(<PaginaConversas />);
  await userEvent.selectOptions(await screen.findByLabelText(/estado/i), "encaminhado");
  expect(srv.ultimaUrl).toContain("state=encaminhado");
  expect(
    [...screen.getByLabelText(/estado/i).querySelectorAll("option")]
      .map((o) => o.value)
      .filter(Boolean),
  ).toEqual(["novo", "qualificando", "cotando", "cotado", "fechado", "encaminhado"]);
});

it("pagina por cursor, não por offset", async () => {
  const srv = montarBackendFalso({
    conversas: { items: [linha({ id: "c1", total_mensagens: 1 })], next_cursor: "cur-2" },
  });
  render(<PaginaConversas />);
  await userEvent.click(await screen.findByRole("button", { name: /mais/i }));
  expect(srv.ultimaUrl).toContain("cursor=cur-2");
  expect(srv.ultimaUrl).not.toContain("offset");
});

it("estado vazio explica o que fazer, sem parecer erro", async () => {
  montarBackendFalso({ conversas: { items: [], next_cursor: null } });
  render(<PaginaConversas />);
  expect(await screen.findByTestId("estado-vazio")).toHaveTextContent(/nenhuma conversa/i);
  expect(screen.queryByRole("alert")).toBeNull();
});
