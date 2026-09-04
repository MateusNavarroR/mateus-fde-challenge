import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { App } from "../../../web/src/App";
import { Capa } from "../../../web/src/ui/Capa";
import { ROTAS_AUTENTICACAO } from "../../../web/src/api/cliente";
import { montarBackendFalso } from "../fakes/backend-falso";

/**
 * A entrada e o balcão da 2ª via.
 *
 * **Nenhuma senha literal neste arquivo.** As credenciais dos casos são geradas em
 * tempo de execução — mesmo princípio do gerador semeado de PII (CLAUDE.md 13b): o
 * fluxo real é exercitado e a varredura de credenciais
 * (`tests/nucleo/test_auth.py`) não tem o que achar. Um `"admin"/"senha123"` aqui
 * seria exatamente o achado que o passe de segurança procura, escrito à mão.
 */
function credencial(): { usuario: string; senha: string } {
  const aleatorio = () => Math.random().toString(36).slice(2, 10);
  return { usuario: `op-${aleatorio()}`, senha: `${aleatorio()}${aleatorio()}` };
}

function irPara(rota: string): void {
  history.pushState(null, "", rota);
}

// ─── o caminho padrão: instalação aberta ─────────────────────────────────────

it("sem credencial configurada, a 2ª via leva direto ao registro", async () => {
  montarBackendFalso({});
  render(<Capa />);
  const via = screen.getByRole("link", { name: /registro/i });
  await waitFor(() => expect(via).toHaveAttribute("href", "/admin/conversas"));
  // E nenhum aviso sobre senha: numa instalação aberta ele só criaria a suspeita
  // de que falta um passo.
  expect(screen.queryByText(/exige credencial/i)).toBeNull();
});

it("sem credencial configurada, /admin abre sem passar por login", async () => {
  montarBackendFalso({});
  irPara("/admin/conversas");
  render(<App />);
  expect(await screen.findByRole("navigation", { name: /seções/i })).toBeVisible();
  expect(screen.queryByLabelText(/senha/i)).toBeNull();
});

it("o backend fora do ar não vira pedido de senha", async () => {
  // Pedir credencial porque a API não respondeu tranca quem tem acesso e não
  // impede quem não tem — a porta de verdade é o `exigir_admin` do backend.
  montarBackendFalso({ indisponivel: true });
  irPara("/admin/conversas");
  render(<App />);
  expect(await screen.findByRole("alert")).toHaveTextContent(/indispon/i);
  expect(screen.queryByLabelText(/senha/i)).toBeNull();
});

// ─── com credencial configurada ──────────────────────────────────────────────

it("com credencial configurada, a 2ª via leva ao balcão em vez de dar 401 seco", async () => {
  montarBackendFalso({ auth: credencial() });
  render(<Capa />);
  const via = screen.getByRole("link", { name: /registro/i });
  await waitFor(() => expect(via).toHaveAttribute("href", "/entrar"));
  expect(screen.getByText(/exige credencial/i)).toBeVisible();
  // A capa continua sendo a capa: as duas vias, com o texto de sempre. (O nome
  // acessível da 2ª via também contém "atendimento" — "o mesmo atendimento pelo
  // lado da operação" —, então quem identifica a 1ª via é o ordinal.)
  expect(screen.getByRole("link", { name: /1ª via/ })).toHaveAttribute("href", "/chat");
});

it("/admin pede credencial e não mostra o registro por trás", async () => {
  montarBackendFalso({ auth: credencial() });
  irPara("/admin/conversas");
  render(<App />);
  expect(await screen.findByLabelText(/senha/i)).toBeVisible();
  expect(screen.queryByRole("navigation", { name: /seções/i })).toBeNull();
});

it("a senha certa abre o registro; a errada não", async () => {
  const cred = credencial();
  const srv = montarBackendFalso({ auth: cred, handoffs: { items: [], pendentes: 0 } });
  irPara("/admin/conversas");
  render(<App />);

  const usuario = await screen.findByLabelText(/usu[áa]rio/i);
  const senha = screen.getByLabelText(/senha/i);
  const entrar = screen.getByRole("button", { name: /entrar/i });

  await userEvent.type(usuario, cred.usuario);
  await userEvent.type(senha, `${cred.senha}-errada`);
  await userEvent.click(entrar);

  expect(await screen.findByRole("alert")).toHaveTextContent(/inv[áa]lid/i);
  expect(srv.autenticado).toBe(false);
  expect(screen.queryByRole("navigation", { name: /seções/i })).toBeNull();

  // O campo de senha é limpo depois da recusa: o valor errado não fica na tela
  // esperando um segundo clique que repetiria o mesmo erro.
  expect(senha).toHaveValue("");

  await userEvent.type(senha, cred.senha);
  await userEvent.click(entrar);

  expect(await screen.findByRole("navigation", { name: /seções/i })).toBeVisible();
  expect(srv.autenticado).toBe(true);
});

it("a recusa não distingue usuário inexistente de senha errada", async () => {
  const cred = credencial();
  montarBackendFalso({ auth: cred });
  irPara("/admin/conversas");
  render(<App />);

  await userEvent.type(await screen.findByLabelText(/usu[áa]rio/i), `${cred.usuario}-outro`);
  await userEvent.type(screen.getByLabelText(/senha/i), cred.senha);
  await userEvent.click(screen.getByRole("button", { name: /entrar/i }));

  expect(await screen.findByRole("alert")).toHaveTextContent("usuário ou senha inválidos");
});

it("encerrar a sessão devolve o balcão", async () => {
  const cred = credencial();
  const srv = montarBackendFalso({
    auth: { ...cred, autenticado: true },
    handoffs: { items: [], pendentes: 0 },
  });
  irPara("/admin/conversas");
  render(<App />);

  const sair = await screen.findByRole("button", { name: /encerrar/i });
  await userEvent.click(sair);

  expect(await screen.findByLabelText(/senha/i)).toBeVisible();
  expect(srv.autenticado).toBe(false);
});

it("numa instalação aberta não há botão de encerrar sessão", async () => {
  // Ele prometeria um controle inexistente — e sugeriria um login que ninguém fez.
  montarBackendFalso({ handoffs: { items: [], pendentes: 0 } });
  irPara("/admin/conversas");
  render(<App />);
  expect(await screen.findByRole("navigation", { name: /seções/i })).toBeVisible();
  expect(screen.queryByRole("button", { name: /encerrar/i })).toBeNull();
});

// ─── as promessas da tela ────────────────────────────────────────────────────

it("a senha vai por POST e nunca pela URL", async () => {
  const cred = credencial();
  const srv = montarBackendFalso({ auth: cred });
  irPara("/entrar");
  render(<App />);

  await userEvent.type(await screen.findByLabelText(/usu[áa]rio/i), cred.usuario);
  await userEvent.type(screen.getByLabelText(/senha/i), cred.senha);
  await userEvent.click(screen.getByRole("button", { name: /entrar/i }));

  await waitFor(() => expect(srv.autenticado).toBe(true));
  // Uma senha em query string acaba no log do servidor, no histórico do navegador
  // e no `Referer` da próxima página.
  expect(srv.ultimaUrl).not.toContain(cred.senha);
  expect(globalThis.location.search).toBe("");
});

it("nada da sessão é guardado no localStorage", async () => {
  const cred = credencial();
  montarBackendFalso({ auth: cred });
  irPara("/entrar");
  render(<App />);

  await userEvent.type(await screen.findByLabelText(/usu[áa]rio/i), cred.usuario);
  await userEvent.type(screen.getByLabelText(/senha/i), cred.senha);
  await userEvent.click(screen.getByRole("button", { name: /entrar/i }));
  await screen.findByRole("navigation", { name: /seções/i });

  // O ponto de trocar o token pela senha era tirar o segredo do alcance do
  // JavaScript da página. Guardar qualquer coisa aqui desfaria isso.
  const guardado = Object.entries(localStorage);
  for (const [, valor] of guardado) {
    expect(String(valor)).not.toContain(cred.senha);
    expect(String(valor)).not.toContain(cred.usuario);
  }
});

it("o campo de senha é de senha, e o navegador sabe qual é qual", async () => {
  montarBackendFalso({ auth: credencial() });
  irPara("/entrar");
  render(<App />);

  const senha = await screen.findByLabelText(/senha/i);
  expect(senha).toHaveAttribute("type", "password");
  expect(senha).toHaveAttribute("autocomplete", "current-password");
  expect(screen.getByLabelText(/usu[áa]rio/i)).toHaveAttribute("autocomplete", "username");
});

it("a tela diz o que fazer quando não há login: não há recuperação de senha", async () => {
  montarBackendFalso({ auth: credencial() });
  irPara("/entrar");
  render(<App />);

  // Um "esqueci minha senha" que não leva a lugar nenhum é pior que a ausência
  // dele: a credencial é variável de ambiente de quem subiu o serviço.
  // `ADMIN_USER` aparece duas vezes: na linha que explica de onde vem a credencial
  // e no rodapé que explica o que acontece sem ela. As duas são intencionais.
  expect((await screen.findAllByText(/ADMIN_USER/)).length).toBeGreaterThan(0);
  expect(screen.queryByRole("link", { name: /esqueci/i })).toBeNull();
  // E o balcão não é um beco: dá para voltar à 1ª via.
  expect(screen.getByRole("link", { name: /1ª via/i })).toHaveAttribute("href", "/chat");
});

it("as rotas de autenticação são exatamente três e saem do mesmo inventário", () => {
  // Nenhum componente escreve "/api/..." no meio do JSX — é assim que uma rota
  // escapa do inventário.
  expect(Object.keys(ROTAS_AUTENTICACAO).sort()).toEqual(["entrar", "estado", "sair"]);
  for (const fn of Object.values(ROTAS_AUTENTICACAO)) {
    expect(fn()).toMatch(/^\/api\/auth\//);
  }
});
