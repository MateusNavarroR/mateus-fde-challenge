import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { PaginaChat } from "../../../web/src/chat/PaginaChat";
import { montarServidorFalso } from "../fakes/servidor-falso";

it("sistema e agente são visualmente idênticos para o lead", async () => {
  const srv = montarServidorFalso();
  render(<PaginaChat conversationId="c1" />);
  await srv.emitirMensagem(0, "sistema", "aviso");
  await srv.emitirMensagem(1, "agente", "olá");
  const [a, b] = screen.getAllByTestId(/^bolha-/);
  // Mesma aparência…
  expect(a!.className).toBe(b!.className);
  // …e nenhum rótulo que denuncie a origem. Para quem está do outro lado é a
  // mesma empresa falando; a distinção é auditoria e vive no admin.
  expect(screen.queryByText(/sistema/i)).toBeNull();
});

it("a bolha do lead é distinta da dos dois", async () => {
  const srv = montarServidorFalso();
  render(<PaginaChat conversationId="c1" />);
  await srv.emitirMensagem(0, "lead", "oi");
  await srv.emitirMensagem(1, "agente", "olá");
  const [lead, agente] = screen.getAllByTestId(/^bolha-/);
  expect(lead!.className).not.toBe(agente!.className);
});

it("o digitando fica aceso durante as três mensagens do turno degradado", async () => {
  const srv = montarServidorFalso();
  render(<PaginaChat conversationId="c1" />);
  await srv.emitir({ type: "typing", ativo: true });
  for (const [i, texto] of [
    "Tô buscando o valor",
    "Ainda tô aqui",
    "Não consegui confirmar",
  ].entries()) {
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
  // Por que travou, não só que travou.
  expect(screen.getByText(/atendente/i)).toBeVisible();
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

it("o link para o admin leva à conversa corrente — e não existe o inverso", () => {
  montarServidorFalso();
  const { container } = render(<PaginaChat conversationId="c1" />);
  expect(screen.getByRole("link", { name: /ver esta conversa no admin/i })).toHaveAttribute(
    "href",
    "/admin/conversas/c1",
  );
  expect(container.querySelectorAll('a[href^="/admin"]').length).toBeGreaterThan(0);
});

it("o input não some enquanto o turno roda — a mensagem entra na fila", async () => {
  const srv = montarServidorFalso();
  render(<PaginaChat conversationId="c1" />);
  await srv.emitir({ type: "typing", ativo: true });
  await userEvent.type(screen.getByRole("textbox"), "e o premium?{Enter}");
  // Bolha otimista, com o turno ainda em voo.
  expect(screen.getByText("e o premium?")).toBeVisible();
  expect(screen.getByTestId("digitando")).toBeVisible();
});

it("o bloco da cotação preserva o texto do renderer e não formata número", async () => {
  const srv = montarServidorFalso();
  render(<PaginaChat conversationId="c1" />);
  const bloco = [
    "Fechei sua cotação",
    "",
    "*Completo — R$ 392,25/mês*",
    "⚠️ Roubo e furto começam a valer 30 dias depois do início da vigência.",
  ].join("\n");
  await srv.emitirMensagem(0, "agente", bloco, { quote_id: "q1" });
  const cotacao = screen.getByTestId("bloco-cotacao");
  expect(cotacao).toHaveAttribute("data-quote-id", "q1");
  expect(cotacao).toHaveTextContent("R$ 392,25/mês");
  expect(cotacao).toHaveTextContent(/30 dias/);
  // Bloco com cotação vinculada não é marcado como bug.
  expect(screen.queryByTestId("marca-bug")).toBeNull();
});
