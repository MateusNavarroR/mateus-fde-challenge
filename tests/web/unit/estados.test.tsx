import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { Admin } from "../../../web/src/admin/Admin";
import { montarBackendFalso } from "../fakes/backend-falso";

const ROTAS = ["/admin/conversas", "/admin/status", "/admin/handoffs"];

it.each(ROTAS)("%s: vazio explica e não parece erro", async (rota) => {
  montarBackendFalso({ tudoVazio: true });
  render(<Admin rota={rota} />);
  expect(await screen.findByTestId("estado-vazio")).toBeVisible();
  expect(screen.queryByRole("alert")).toBeNull();
});

it.each(ROTAS)("%s: backend fora mostra erro com o que fazer, não tela em branco", async (rota) => {
  montarBackendFalso({ indisponivel: true });
  render(<Admin rota={rota} />);
  const alerta = await screen.findByRole("alert");
  expect(alerta).toHaveTextContent(/docker compose|indisponível/i);
  expect(within(alerta).getByRole("button", { name: /tentar de novo/i })).toBeVisible();
});

it("401 pede o ADMIN_TOKEN em vez de repetir 'erro'", async () => {
  montarBackendFalso({ status401: true });
  render(<Admin rota="/admin/status" />);
  // Exato: "Custo e uso de tokens" também casaria com /token/i.
  expect(await screen.findByLabelText("ADMIN_TOKEN")).toBeVisible();
});

it.each([
  [1440, 900],
  [390, 844],
])("não há rolagem horizontal em %ix%i", async (w, h) => {
  window.innerWidth = w;
  window.innerHeight = h;
  montarBackendFalso({ populado: true });
  const { container } = render(<Admin rota="/admin/conversas" />);
  await screen.findByRole("table");
  const raiz = container.firstElementChild as HTMLElement;
  // Piso, não teto: o jsdom não faz layout. O Playwright confere no navegador.
  expect(raiz.scrollWidth).toBeLessThanOrEqual(raiz.clientWidth);
});

it("filtro sem resultado NÃO diz que o banco está vazio", async () => {
  // Achado na vistoria: com 14 conversas no banco e o filtro em `fechado`, a tela
  // dizia "o banco está no ar e vazio" e mandava abrir o /chat para criar uma
  // conversa. O próximo passo certo era limpar o filtro, e a tela apontava para o
  // lado oposto — a pergunta 3 da vistoria ("algum estado vazio deixa de explicar o
  // que fazer?") falhando.
  const usuario = userEvent.setup();
  montarBackendFalso({ tudoVazio: true });
  render(<Admin rota="/admin/conversas" />);

  const vazio = await screen.findByTestId("estado-vazio");
  expect(vazio).toHaveTextContent(/banco está no ar e vazio/i);

  await usuario.selectOptions(screen.getByLabelText(/estado/i), "fechado");

  const filtrado = await screen.findByTestId("estado-vazio");
  expect(filtrado).toHaveTextContent(/fechado/);
  expect(filtrado).toHaveTextContent(/filtro/i);
  expect(filtrado).not.toHaveTextContent(/banco está no ar e vazio/i);
});
