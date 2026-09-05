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
/** O histórico local, controlado pelo teste. É o insumo do seletor de conversas. */
let historico: { id: string; aberta_em: string }[] = [];
const retomada = vi.fn((id: string) => id);
vi.mock("../../../web/src/chat/sessao", () => ({
  abrirSessao: () => abrirSessao(),
  reiniciarSessao: () => reiniciarSessao(),
  historicoLocal: () => historico,
  retomarConversa: (id: string) => retomada(id),
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
  historico = [];
  retomada.mockClear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  abrirSessao.mockReset();
  reiniciarSessao.mockReset();
});

it("abrir uma conversa `encaminhado` já anuncia o atendimento, sem esperar o socket", async () => {
  // O estado precisa estar na tela desde o primeiro quadro. O que mudou foi a
  // consequência dele: avisa, não trava — ver `pagina-chat.test.tsx`.
  abrirSessao.mockResolvedValue({
    id: "c1",
    detalhe: { id: "c1", state: "encaminhado", perfil: {}, quotes: [], handoffs: [],
               messages: MENSAGENS },
  });

  render(<PaginaChat />);

  expect(await screen.findByText(/está com um atendente/i)).toBeVisible();
  expect(screen.getByRole("textbox", { name: /sua mensagem/i })).toBeEnabled();
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

  expect(await screen.findByText(/está com um atendente/i)).toBeVisible();

  await usuario.click(screen.getByRole("button", { name: /nova conversa/i }));

  await waitFor(() => {
    expect(screen.getByRole("textbox", { name: /sua mensagem/i })).toBeEnabled();
  });
  expect(screen.getByRole("button", { name: /anexar mídia/i })).toBeEnabled();
  // E as bolhas da conversa anterior não podem ficar: são de OUTRA conversa.
  expect(screen.queryByText(/está com um atendente/i)).toBeNull();
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


it("a conversa com atendente oferece a saída JUNTO do aviso, não só no topo", async () => {
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

  const aviso = await screen.findByText(/está com um atendente/i);
  const acao = within(aviso).getByRole("button", { name: /conversa nova/i });

  await usuario.click(acao);

  await waitFor(() => {
    expect(screen.getByRole("textbox", { name: /sua mensagem/i })).toBeEnabled();
  });
});


it("dá para escolher qual conversa continuar, entre as DESTE navegador", async () => {
  /*
   * Antes só existia a última: quem clicava em "Nova conversa" perdia a anterior de
   * vista, sem forma de voltar. Para exercitar o agente é o contrário do que se quer —
   * comparar dois caminhos exige ter os dois à mão.
   *
   * A lista vem do NAVEGADOR, e é decisão de privacidade, não de conveniência:
   * `GET /api/conversations` devolveria as conversas de TODO MUNDO, e um seletor no
   * chat público mostrando a conversa de outro lead é vazamento.
   */
  historico = [
    { id: "conv_atual", aberta_em: T },
    { id: "conv_antiga", aberta_em: T },
  ];
  abrirSessao.mockResolvedValue({
    id: "conv_atual",
    detalhe: { id: "conv_atual", state: "qualificando", perfil: {}, quotes: [],
               handoffs: [], messages: MENSAGENS },
  });

  render(<PaginaChat />);

  const seletor = await screen.findByTestId("seletor-de-conversa");
  // As duas aparecem, e nenhuma outra: este navegador só conhece estas.
  expect(within(seletor).getAllByRole("option")).toHaveLength(2);

  const usuario = userEvent.setup();
  await usuario.selectOptions(seletor, "conv_antiga");
  expect(retomada).toHaveBeenCalledWith("conv_antiga");
});


it("com UMA conversa o seletor JÁ aparece — descoberta antes do estrago", async () => {
  /*
   * A primeira versão escondia o seletor até haver duas conversas. Parecia limpo e
   * escondia de quem precisava descobrir: só se aprende que dá para voltar depois de
   * já ter perdido uma conversa de vista. Um controle que só surge quando o estrago
   * está feito não é discreto, é inútil.
   */
  historico = [{ id: "conv_unica", aberta_em: T }];
  abrirSessao.mockResolvedValue({
    id: "conv_unica",
    detalhe: { id: "conv_unica", state: "qualificando", perfil: {}, quotes: [],
               handoffs: [], messages: MENSAGENS },
  });

  render(<PaginaChat />);
  await screen.findByRole("textbox", { name: /sua mensagem/i });
  expect(screen.getByTestId("seletor-de-conversa")).toBeVisible();
  // E o rótulo é visível, não só para leitor de tela: um `select` solto ao lado de
  // "Nova conversa" não diz o que faz até alguém abri-lo.
  expect(screen.getByText("Conversa")).toBeVisible();
});

it("sem NENHUMA conversa ainda, não há o que escolher", async () => {
  historico = [];
  abrirSessao.mockResolvedValue({
    id: "conv_nova",
    detalhe: { id: "conv_nova", state: "novo", perfil: {}, quotes: [], handoffs: [],
               messages: [] },
  });

  render(<PaginaChat />);
  await screen.findByRole("textbox", { name: /sua mensagem/i });
  expect(screen.queryByTestId("seletor-de-conversa")).toBeNull();
});
