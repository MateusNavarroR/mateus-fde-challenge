/**
 * O F5 numa conversa já encaminhada.
 *
 * Este arquivo existe porque um teste de reducer NÃO teria pego o bug: o reducer
 * sempre soube travar a entrada quando recebe `state: "encaminhado"` no histórico —
 * quem nunca lhe passava o estado era a tela. Provar a unidade e não a fiação é
 * exatamente como `MIDIA_SEM_TEXTO` ficou inalcançável em produção com o teste
 * verde. Por isso a asserção é feita sobre a TELA montada.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { WebSocketFalso } from "../fakes/websocket-falso";

const abrirSessao = vi.fn();
const reiniciarSessao = vi.fn();
vi.mock("../../../web/src/chat/sessao", () => ({
  abrirSessao: () => abrirSessao(),
  reiniciarSessao: () => reiniciarSessao(),
  CHAVE: "autoseguro.conversation_id",
}));

const { PaginaChat } = await import("../../../web/src/chat/PaginaChat");

const T = "2026-01-01T00:00:00Z";
const MENSAGENS = [
  { id: "m1", index: 0, autor: "lead", tipo: "image", conteudo: "foto.jpg",
    status: "received", quote_id: null, criado_em: T },
  { id: "m2", index: 1, autor: "sistema", tipo: "text",
    conteudo: "Já passei sua conversa pra um atendente da equipe.",
    status: "sent", quote_id: null, criado_em: T },
];

beforeEach(() => {
  WebSocketFalso.reiniciar();
  vi.stubGlobal("WebSocket", WebSocketFalso);
});

afterEach(() => {
  vi.unstubAllGlobals();
  abrirSessao.mockReset();
  reiniciarSessao.mockReset();
});

it("abrir uma conversa `encaminhado` já mostra a tela travada, sem esperar o socket", async () => {
  // O socket não recebe nenhum frame de propósito: numa conversa terminal o backend
  // para de responder, então o frame `state` NUNCA chega. Se a tela dependesse dele,
  // o lead veria "conversa aberta" e digitaria no vazio — que foi o que aconteceu.
  abrirSessao.mockResolvedValue({
    id: "c1",
    detalhe: { id: "c1", state: "encaminhado", perfil: {}, quotes: [], handoffs: [],
               messages: MENSAGENS },
  });

  render(<PaginaChat />);

  await waitFor(() => {
    expect(screen.getByRole("textbox", { name: /sua mensagem/i })).toBeDisabled();
  });
  expect(screen.getByText(/A equipe assume daqui/i)).toBeVisible();
});

it("uma conversa em andamento continua com a entrada liberada", async () => {
  // O negativo: travar por engano é pior do que não travar, porque o lead não tem
  // como reclamar — o campo simplesmente não aceita.
  abrirSessao.mockResolvedValue({
    id: "c1",
    detalhe: { id: "c1", state: "qualificando", perfil: {}, quotes: [], handoffs: [],
               messages: [MENSAGENS[0]] },
  });

  render(<PaginaChat />);

  await waitFor(() => {
    expect(screen.getByRole("textbox", { name: /sua mensagem/i })).toBeEnabled();
  });
});


it("«Nova conversa» depois de um handoff devolve um compositor VIVO", async () => {
  // Pré-existente e encontrado clicando: o estado do hook não se reiniciava quando
  // a conversa mudava, então `entradaBloqueada` era herdado da conversa anterior. O
  // lead saía de um handoff, pedia uma conversa nova e recebia um campo morto —
  // sem mensagem de erro, porque do ponto de vista da tela nada tinha falhado.
  abrirSessao.mockResolvedValue({
    id: "c1",
    detalhe: { id: "c1", state: "encaminhado", perfil: {}, quotes: [], handoffs: [],
               messages: MENSAGENS },
  });
  reiniciarSessao.mockResolvedValue("c2");

  const usuario = userEvent.setup();
  render(<PaginaChat />);

  await waitFor(() => {
    expect(screen.getByRole("textbox", { name: /sua mensagem/i })).toBeDisabled();
  });

  await usuario.click(screen.getByRole("button", { name: /nova conversa/i }));

  await waitFor(() => {
    expect(screen.getByRole("textbox", { name: /sua mensagem/i })).toBeEnabled();
  });
  expect(screen.getByRole("button", { name: /anexar mídia/i })).toBeEnabled();
  // E as bolhas da conversa anterior não podem ficar: são de OUTRA conversa.
  expect(screen.queryByText(/A equipe assume daqui/i)).toBeNull();
});


it("a bolha de mídia se anuncia como anexo, não como texto digitado", async () => {
  // Sem o rótulo, "foto.jpg" aparece igual a uma mensagem em que o lead tivesse
  // escrito essa string — e é o mesmo transcript que o operador lê no admin.
  abrirSessao.mockResolvedValue({
    id: "c1",
    detalhe: { id: "c1", state: "qualificando", perfil: {}, quotes: [], handoffs: [],
               messages: [MENSAGENS[0]] },
  });

  render(<PaginaChat />);

  const marca = await screen.findByTestId("marca-anexo");
  expect(marca).toHaveTextContent(/imagem anexada/i);
});

it("uma mensagem de texto NÃO ganha rótulo de anexo", async () => {
  abrirSessao.mockResolvedValue({
    id: "c1",
    detalhe: { id: "c1", state: "qualificando", perfil: {}, quotes: [], handoffs: [],
               messages: [MENSAGENS[1]] },
  });

  render(<PaginaChat />);

  await screen.findByText(/atendente da equipe/i);
  expect(screen.queryByTestId("marca-anexo")).toBeNull();
});


it("a conversa travada oferece a saída JUNTO do campo, não só no topo", async () => {
  // Achado na vistoria: entrando pela capa — que promete "fale com o agente e peça
  // uma cotação" — dá para cair numa conversa `encaminhado` de sessão anterior, com
  // o campo morto. A saída existia, a três centímetros dali e sem relação visual com
  // o problema. A pergunta 2 da vistoria não falhava (não era beco sem saída), mas a
  // promessa da capa não batia com o destino.
  abrirSessao.mockResolvedValue({
    id: "c1",
    detalhe: { id: "c1", state: "encaminhado", perfil: {}, quotes: [], handoffs: [],
               messages: MENSAGENS },
  });
  reiniciarSessao.mockResolvedValue("c2");

  const usuario = userEvent.setup();
  render(<PaginaChat />);

  const aviso = await screen.findByText(/o campo abaixo está travado/i);
  const acao = within(aviso).getByRole("button", { name: /conversa nova/i });

  await usuario.click(acao);

  await waitFor(() => {
    expect(screen.getByRole("textbox", { name: /sua mensagem/i })).toBeEnabled();
  });
});
