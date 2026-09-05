/**
 * A tela de atendimento: o handoff deixa de ser uma lista que ninguém atende.
 *
 * O que estes testes travam é a diferença entre esta tela e a vista de leitura do
 * histórico. Lá o operador vê a conversa como o lead a viu, e não tem caneta; aqui ele
 * está do lado da EQUIPE — a perspectiva se inverte — e responde na mesma conversa.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { Atendimento } from "../../../web/src/admin/Atendimento";
import { montarBackendFalso } from "../fakes/backend-falso";

const T = "2026-01-01T00:00:00Z";
const CONVERSA = {
  id: "c1",
  state: "encaminhado",
  perfil: {},
  quotes: [],
  handoffs: [],
  messages: [
    { id: "m1", index: 0, autor: "lead", conteudo: "quero falar com alguém", status: "received", tipo: "text", quote_id: null, criado_em: T },
    { id: "m2", index: 1, autor: "sistema", conteudo: "Já passei sua conversa pra um atendente.", status: "sent", tipo: "text", quote_id: null, criado_em: T },
  ],
};

it("a PERSPECTIVA se inverte: o lead à esquerda, nós à direita", async () => {
  // É isto que faz dela a tela do agente e não outra cópia do histórico. A classe
  // `bolha--lead` significa "a minha bolha"; aqui quem escreve somos nós, então a
  // mensagem DO LEAD tem que aparecer como a do outro lado.
  montarBackendFalso({ conversa: CONVERSA });
  render(<Atendimento id="c1" />);

  const esteira = await screen.findByTestId("esteira-do-atendimento");
  const doLead = within(esteira).getByText(/quero falar com alguém/i).closest(".bolha");
  const nossa = within(esteira).getByText(/pra um atendente/i).closest(".bolha");

  expect(doLead?.className).toMatch(/bolha--empresa/);
  expect(nossa?.className).toMatch(/bolha--lead/);
});

it("responder grava e a resposta aparece na conversa", async () => {
  const srv = montarBackendFalso({ conversa: CONVERSA });
  const usuario = userEvent.setup();
  render(<Atendimento id="c1" />);
  await screen.findByTestId("esteira-do-atendimento");

  await usuario.type(screen.getByLabelText(/sua resposta/i), "Oi! Aqui é a equipe.");
  await usuario.click(screen.getByRole("button", { name: /enviar/i }));

  await waitFor(() => {
    expect(within(screen.getByTestId("esteira-do-atendimento"))
      .getByText(/aqui é a equipe/i)).toBeVisible();
  });
  expect(srv.postsDoOperador).toHaveLength(1);
  expect(srv.postsDoOperador[0]).toMatchObject({ text: "Oi! Aqui é a equipe." });
});

it("conversa que o AGENTE ainda conduz não aceita resposta", async () => {
  // O backend recusa com 409; a tela diz o mesmo antes de deixar tentar. Duas vozes
  // no mesmo turno deixam o lead sem saber com quem está falando.
  montarBackendFalso({ conversa: { ...CONVERSA, state: "qualificando" } });
  render(<Atendimento id="c1" />);

  expect(await screen.findByTestId("ainda-do-agente")).toBeVisible();
  expect(screen.getByLabelText(/sua resposta/i)).toBeDisabled();
  expect(screen.getByRole("button", { name: /enviar/i })).toBeDisabled();
});

it("o atendimento leva ao histórico completo, que é onde estão as provas", async () => {
  montarBackendFalso({ conversa: CONVERSA });
  render(<Atendimento id="c1" />);
  expect(await screen.findByRole("link", { name: /histórico completo/i }))
    .toHaveAttribute("href", "/historico/c1");
});

it("dá para marcar como resolvido SEM voltar para a fila", async () => {
  /*
   * A tela nasceu sem esta ação, e a falta era gritante em uso: o operador assume o
   * caso, atende, resolve o problema do lead — e não tinha como dizer que terminou.
   * Teria de voltar à fila, achar o mesmo caso no meio dos outros e só então marcar.
   * A ação pertence a quem está fazendo o trabalho, no momento em que ele acaba.
   */
  const srv = montarBackendFalso({
    conversa: {
      ...CONVERSA,
      handoffs: [{ id: "h1", conversation_id: "c1", status: "assumido",
                   trigger: "lead_pediu_atendente", disparado_por: "regra",
                   reason: "", criado_em: T }],
    },
  });
  const usuario = userEvent.setup();
  render(<Atendimento id="c1" />);
  await screen.findByTestId("esteira-do-atendimento");

  expect(screen.getByTestId("status-do-handoff")).toHaveTextContent(/assumido/);
  await usuario.click(screen.getByRole("button", { name: /marcar como resolvido/i }));

  await waitFor(() => {
    expect(srv.ultimoPatch?.[0]).toBe("/api/handoffs/h1");
  });
  expect(srv.ultimoPatch?.[1]).toMatchObject({ status: "resolvido" });
});

it("um handoff PENDENTE pode ser assumido daqui também", async () => {
  // Quem chega pela URL direta, sem passar pela fila, não deve ficar sem a ação.
  const srv = montarBackendFalso({
    conversa: {
      ...CONVERSA,
      handoffs: [{ id: "h2", conversation_id: "c1", status: "pendente",
                   trigger: "lead_pediu_atendente", disparado_por: "regra",
                   reason: "", criado_em: T }],
    },
  });
  const usuario = userEvent.setup();
  render(<Atendimento id="c1" />);
  await screen.findByTestId("esteira-do-atendimento");

  await usuario.click(screen.getByRole("button", { name: /^assumir$/i }));
  await waitFor(() => expect(srv.ultimoPatch?.[1]).toMatchObject({ status: "assumido" }));
});

it("conversa sem handoff aberto não oferece encerramento", async () => {
  // O negativo: um botão de resolver sem nada a resolver mandaria um PATCH para
  // lugar nenhum, e o erro apareceria como falha da tela.
  montarBackendFalso({
    conversa: {
      ...CONVERSA,
      handoffs: [{ id: "h3", conversation_id: "c1", status: "resolvido",
                   trigger: "lead_pediu_atendente", disparado_por: "regra",
                   reason: "", criado_em: T }],
    },
  });
  render(<Atendimento id="c1" />);
  expect(await screen.findByTestId("sem-handoff-aberto")).toBeVisible();
  expect(screen.queryByRole("button", { name: /resolvido/i })).toBeNull();
});
