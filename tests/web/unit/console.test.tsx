/**
 * A casca da operação — a guia lateral colapsável.
 *
 * ⚠️ **Este arquivo testava a casca ANTERIOR e continuava verde.** Depois da
 * reestruturação, `LayoutAdmin` e `Casca` ficaram sem nenhum importador em
 * `web/src`, e 28 casos de teste (aqui, em `estados` e em `login`) seguiam
 * garantindo o comportamento de código que não roda mais. A suíte não estava
 * cega para a fiação: estava provando a fiação de ontem — que é pior, porque
 * parece cobertura.
 *
 * As invariantes valem igual; o alvo mudou.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it } from "vitest";
import { Console, SECOES } from "../../../web/src/ui/Console";
import { App } from "../../../web/src/App";
import { _reiniciarAutenticacao } from "../../../web/src/ui/useAutenticacao";
import { montarBackendFalso } from "../fakes/backend-falso";

const CHAVE_COLAPSO = "autoseguro.barra_colapsada";

beforeEach(() => localStorage.removeItem(CHAVE_COLAPSO));
afterEach(() => localStorage.removeItem(CHAVE_COLAPSO));

it("a contagem de pendentes aparece de qualquer seção", async () => {
  montarBackendFalso({ handoffs: { items: [], pendentes: 3 } });
  for (const s of SECOES) {
    const { unmount } = render(<Console rota={s.href} />);
    expect(
      await screen.findByTestId("contagem-pendentes"), s.href,
    ).toHaveTextContent("3");
    unmount();
  }
});

it("zero não vira contagem — zero é ruído, não informação", async () => {
  montarBackendFalso({ handoffs: { items: [], pendentes: 0 } });
  render(<Console rota="/painel" />);
  expect(await screen.findByRole("navigation", { name: /seções/i })).toBeVisible();
  expect(screen.queryByTestId("contagem-pendentes")).toBeNull();
});

it("a contagem sobe no push, sem recarregar", async () => {
  const srv = montarBackendFalso({ handoffs: { items: [], pendentes: 1 } });
  render(<Console rota="/painel" />);
  expect(await screen.findByTestId("contagem-pendentes")).toHaveTextContent("1");
  srv.responderComPendentes(2);
  await srv.push({ type: "handoff.created", handoff: { id: "h9", status: "pendente" } });
  expect(await screen.findByTestId("contagem-pendentes")).toHaveTextContent("2");
});

it("as cinco seções se ligam entre si", () => {
  montarBackendFalso({});
  render(<Console rota="/painel" />);
  const nav = screen.getByRole("navigation", { name: /seções/i });
  for (const s of SECOES) {
    expect(
      within(nav).getByRole("link", { name: new RegExp(s.nome, "i") }),
    ).toHaveAttribute("href", s.href);
  }
});

it("a seção atual se anuncia ao olho, e não só ao leitor de tela", () => {
  // `aria-current` resolve para leitor de tela e não resolve para quem enxerga.
  // A guia ativa recebe a classe que a faz avançar sobre o conteúdo, como aba de
  // pasta puxada para fora — é ela que este teste trava.
  montarBackendFalso({});
  render(<Console rota="/handoffs" />);
  const nav = screen.getByRole("navigation", { name: /seções/i });
  const ativa = within(nav).getByRole("link", { name: /handoffs/i });
  expect(ativa).toHaveAttribute("aria-current", "page");
  expect(ativa.className).toMatch(/guia__secao--atual/);
  const outra = within(nav).getByRole("link", { name: /^painel$/i });
  expect(outra).not.toHaveAttribute("aria-current");
  expect(outra.className).not.toMatch(/--atual/);
});

it("o detalhe de uma conversa mantém o Histórico como seção atual", () => {
  // Sem isto, abrir uma conversa apagava a marca da seção e o operador perdia a
  // referência de onde está — que é o problema que a guia veio resolver.
  montarBackendFalso({});
  render(<Console rota="/historico/conv_x" />);
  const nav = screen.getByRole("navigation", { name: /seções/i });
  expect(within(nav).getByRole("link", { name: /histórico/i })).toHaveAttribute(
    "aria-current", "page",
  );
});

it("colapsar preserva o nome acessível de cada seção", async () => {
  // Colapsada só resta o ordinal, e a contagem de pendentes é `aria-hidden`. Sem
  // `aria-label` no link, quem navega por leitor perdia o nome exatamente na
  // seção que tem trabalho esperando.
  montarBackendFalso({ handoffs: { items: [], pendentes: 4 } });
  const usuario = userEvent.setup();
  render(<Console rota="/painel" />);
  await screen.findByTestId("contagem-pendentes");

  await usuario.click(screen.getByRole("button", { name: /recolher/i }));

  const nav = screen.getByRole("navigation", { name: /seções/i });
  for (const s of SECOES) {
    expect(within(nav).getByRole("link", { name: new RegExp(s.nome, "i") })).toBeVisible();
  }
});

it("o colapso sobrevive a uma remontagem — é preferência, não estado de tela", async () => {
  montarBackendFalso({});
  const usuario = userEvent.setup();
  const { unmount } = render(<Console rota="/painel" />);
  await usuario.click(screen.getByRole("button", { name: /recolher/i }));
  unmount();

  render(<Console rota="/painel" />);
  expect(screen.getByRole("button", { name: /expandir/i })).toBeVisible();
});

it("um socket de eventos para a sessão inteira, não um por tela", async () => {
  // `async` porque o socket de eventos passou a esperar o estado de autenticação:
  // sem sessão ele não abre, e antes disso não dá para saber se há uma. O que o
  // teste trava continua sendo o mesmo — UM socket, não um por tela.
  const srv = montarBackendFalso({});
  const { rerender } = render(<Console rota="/painel" />);
  await screen.findByRole("navigation", { name: /seções/i });
  rerender(<Console rota="/handoffs" />);
  rerender(<Console rota="/status" />);
  await waitFor(() => expect(srv.socketsAbertos).toBe(1));
});

it("o simulador ANÔNIMO não abre o socket da operação", async () => {
  // Ele é público — um lead não faz login para pedir cotação — e `/api/events` exige
  // sessão. Sem esta guarda, o cliente reconectava em laço com backoff, para sempre,
  // contra uma rota que nunca ia abrir.
  _reiniciarAutenticacao();
  const srv = montarBackendFalso({
    auth: { usuario: `op-${Math.random().toString(36).slice(2)}`,
            senha: Math.random().toString(36).slice(2), autenticado: false },
  });
  render(<Console rota="/simulador" />);
  await screen.findByRole("navigation", { name: /seções/i });
  await waitFor(() => expect(srv.socketsAbertos).toBe(0));
});

/*
 * As rotas antigas COM id. O mapa de legado casa por igualdade, e por isso
 * `/admin/conversas` abria enquanto `/admin/conversas/conv_x` — a única forma que de
 * fato aparecia num link, o do handoff para a sua conversa — não casava nada, não era
 * seção, e caía no fallback: o Painel. Quem clicava era mandado de volta ao começo,
 * sem erro e sem explicação.
 */
it("uma rota antiga COM id resolve para a nova, e não para o Painel", async () => {
  montarBackendFalso({});
  history.replaceState(null, "", "/admin/conversas/conv_x");
  render(<App />);
  await screen.findByRole("navigation", { name: /seções/i });
  expect(location.pathname).toBe("/historico/conv_x");
});
