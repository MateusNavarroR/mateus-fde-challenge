import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { Operacao } from "../../../web/src/App";
import { montarBackendFalso } from "../fakes/backend-falso";
import { Erro } from "../../../web/src/ui/Erro";
import { ErroApi } from "../../../web/src/api/cliente";
import { _reiniciarAutenticacao } from "../../../web/src/ui/useAutenticacao";

const ROTAS = ["/historico", "/status", "/handoffs"];

it.each(ROTAS)("%s: vazio explica e não parece erro", async (rota) => {
  montarBackendFalso({ tudoVazio: true });
  render(<Operacao rota={rota} />);
  expect(await screen.findByTestId("estado-vazio")).toBeVisible();
  expect(screen.queryByRole("alert")).toBeNull();
});

it.each(ROTAS)("%s: backend fora mostra erro com o que fazer, não tela em branco", async (rota) => {
  montarBackendFalso({ indisponivel: true });
  render(<Operacao rota={rota} />);
  const alerta = await screen.findByRole("alert");
  expect(alerta).toHaveTextContent(/docker compose|indisponível/i);
  expect(within(alerta).getByRole("button", { name: /tentar de novo/i })).toBeVisible();
});

it("401 pede o ADMIN_TOKEN em vez de repetir 'erro'", async () => {
  montarBackendFalso({ status401: true });
  render(<Operacao rota="/status" />);
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
  const { container } = render(<Operacao rota="/historico" />);
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
  render(<Operacao rota="/historico" />);

  const vazio = await screen.findByTestId("estado-vazio");
  expect(vazio).toHaveTextContent(/banco está no ar e vazio/i);

  await usuario.selectOptions(screen.getByLabelText(/estado/i), "fechado");

  const filtrado = await screen.findByTestId("estado-vazio");
  expect(filtrado).toHaveTextContent(/fechado/);
  expect(filtrado).toHaveTextContent(/filtro/i);
  expect(filtrado).not.toHaveTextContent(/banco está no ar e vazio/i);
});

/*
 * O 401 tem DUAS causas e a tela dizia sempre a mesma coisa.
 *
 * Com login configurado, um 401 é sessão expirada — e ela expira sozinha quando o
 * serviço reinicia, porque o salt do `scrypt` é sorteado a cada boot e a chave que
 * assina o cookie deriva dele. A tela oferecia um campo de `ADMIN_TOKEN` e afirmava
 * "o ADMIN_TOKEN está definido no backend": uma frase falsa sobre uma variável vazia,
 * mandando o operador procurar um segredo inexistente para um problema cuja resposta
 * é entrar de novo.
 */
it("401 com login configurado manda reautenticar, não pedir ADMIN_TOKEN", async () => {
  _reiniciarAutenticacao();
  montarBackendFalso({ auth: { usuario: "op", senha: "segredo", autenticado: false } });
  const erro = new ErroApi("nao_autorizado", "sessão ausente ou expirada", 401, null);
  render(<Erro erro={erro} aoTentarDeNovo={() => {}} />);

  expect(await screen.findByRole("link", { name: /entrar de novo/i })).toHaveAttribute(
    "href", "/entrar",
  );
  expect(screen.queryByLabelText(/ADMIN_TOKEN/)).toBeNull();
  expect(screen.getByRole("alert")).not.toHaveTextContent(/ADMIN_TOKEN está definido/);
});

it("401 SEM login configurado continua pedindo o token — a outra causa é real", async () => {
  _reiniciarAutenticacao();
  // Sem `auth` no fake, `/api/auth/estado` responde `exigido: false`: é a instalação
  // sem login, onde o campo de token é a resposta certa.
  montarBackendFalso({});
  const erro = new ErroApi("nao_autorizado", "token ausente", 401, null);
  render(<Erro erro={erro} aoTentarDeNovo={() => {}} />);

  expect(await screen.findByLabelText(/ADMIN_TOKEN/)).toBeVisible();
});
