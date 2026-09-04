import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { LayoutAdmin } from "../../../web/src/admin/LayoutAdmin";
import { montarBackendFalso } from "../fakes/backend-falso";

it("o badge de pendentes aparece nas três telas", async () => {
  montarBackendFalso({ handoffs: { items: [], pendentes: 3 } });
  for (const rota of ["/admin/conversas", "/admin/status", "/admin/handoffs"]) {
    const { unmount } = render(<LayoutAdmin rota={rota} />);
    expect(await screen.findByTestId("badge-pendentes"), rota).toHaveTextContent("3");
    unmount();
  }
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
  montarBackendFalso({});
  render(<LayoutAdmin rota="/admin/status" />);
  const nav = screen.getByRole("navigation");
  for (const [nome, href] of [
    [/convers/i, "/admin/conversas"],
    [/status/i, "/admin/status"],
    [/handoff/i, "/admin/handoffs"],
  ] as const) {
    expect(screen.getByRole("link", { name: nome })).toHaveAttribute("href", href);
  }
  expect(nav).toBeVisible();
});

it("NÃO existe link do admin para o chat (decisão fechada §8)", () => {
  // O inverso existe e é testado na fatia 7. Este é o teste negativo que impede
  // alguém de adicionar o link "por simetria" seis meses depois.
  montarBackendFalso({});
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
