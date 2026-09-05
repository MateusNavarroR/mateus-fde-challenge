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

it("encaminhado AVISA e não trava — quem encerrou foi o agente, não a conversa", async () => {
  /*
   * Este teste travava o comportamento contrário, e estava certo enquanto ninguém
   * podia assumir a fila: sem atendimento humano, um campo aberto deixaria o lead
   * falando sozinho.
   *
   * Com o atendimento implementado, travar vira um beco: o operador escreve "oi, aqui
   * é a Ana" e o lead não tem como responder. `encaminhado` significa que o AGENTE
   * encerrou a participação — a guarda no topo de `responder` garante que nada do que
   * o lead escrever daqui em diante vai ao modelo. É mensagem para a pessoa que
   * assumiu, e é ela quem lê.
   */
  const srv = montarServidorFalso();
  render(<PaginaChat conversationId="c1" />);
  await srv.emitir({ type: "state", state: "encaminhado" });

  expect(screen.getByRole("textbox")).toBeEnabled();
  // E diz o que mudou: sem isto, o lead não sabe que trocou de interlocutor.
  expect(screen.getByText(/atendente/i)).toBeVisible();
  expect(screen.getByText(/quem responde daqui em diante é uma pessoa/i)).toBeVisible();
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

it("o link para o admin leva à conversa corrente, numa rota VIVA", () => {
  // `/admin/conversas/{id}` era a rota antiga: ela só resolvia por redirecionamento,
  // e o mapa de legado casava por igualdade — a forma COM id caía no Painel. Aponta
  // direto para a rota atual.
  //
  // O trecho "e não existe o inverso" saiu do nome: a ponte `admin → chat` passou a
  // existir, com a distinção que a decisão §8 de fato protegia — ver
  // `detalhe-conversa.test.tsx`.
  montarServidorFalso();
  render(<PaginaChat conversationId="c1" />);
  expect(screen.getByRole("link", { name: /ver esta conversa no admin/i })).toHaveAttribute(
    "href",
    "/historico/c1",
  );
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

  // A ênfase do template é estilo WhatsApp (`*assim*`), porque o canal imita o
  // WhatsApp. Achado na vistoria: o bloco renderizava a linha crua e o lead lia
  // `*Completo — R$ 392,25/mês*` COM os asteriscos — na linha mais importante do
  // produto. Este teste passava porque `toHaveTextContent` ignora os marcadores.
  expect(cotacao.textContent).not.toMatch(/\*/);
  expect(cotacao.querySelector("em")).toHaveTextContent("Completo — R$ 392,25/mês");

  // E o número segue sem ser reformatado: o valor é byte a byte o do renderer.
  expect(cotacao).toHaveTextContent("392,25");
  expect(cotacao).not.toHaveTextContent("392.25");
  // Bloco com cotação vinculada não é marcado como bug.
  expect(screen.queryByTestId("marca-bug")).toBeNull();
});
