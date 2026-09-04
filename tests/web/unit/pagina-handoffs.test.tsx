import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { PaginaHandoffs } from "../../../web/src/admin/PaginaHandoffs";
import { montarBackendFalso } from "../fakes/backend-falso";

const T = "2026-01-01T00:00:00Z";

it("cada item mostra o gatilho, o motivo e quem disparou", async () => {
  montarBackendFalso({
    handoffs: {
      pendentes: 1,
      items: [
        {
          id: "h1",
          conversation_id: "c7",
          trigger: "cotacao_indisponivel",
          reason: "job de cotação terminou failed",
          summary: null,
          disparado_por: "regra",
          quote_id: "q1",
          ultima_cotacao: null,
          status: "pendente",
          criado_em: T,
          assumido_em: null,
          resolved_at: null,
        },
      ],
    },
  });
  render(<PaginaHandoffs />);
  const item = await screen.findByTestId("handoff-h1");
  expect(
    within(item).getByText(/cotacao_indisponivel|cotação indisponível/i),
  ).toBeVisible();
  expect(within(item).getByTestId("disparado-por")).toHaveTextContent(/regra/);
});

it("distingue gatilho de regra de decisão do modelo", async () => {
  // Um gatilho determinístico e uma decisão do modelo produzem o mesmo sinal, e a
  // fila distingue os dois (openapi.yaml, Handoff.disparado_por).
  montarBackendFalso({
    handoffs: {
      pendentes: 2,
      items: [
        { id: "h1", disparado_por: "regra", trigger: "cotacao_indisponivel", status: "pendente", conversation_id: "c1", reason: "", criado_em: T },
        { id: "h2", disparado_por: "modelo", trigger: "assunto_sensivel", status: "pendente", conversation_id: "c2", reason: "", criado_em: T },
      ],
    },
  });
  render(<PaginaHandoffs />);
  const [a, b] = await screen.findAllByTestId("disparado-por");
  expect(a!.textContent).not.toBe(b!.textContent);
});

it("assumir e resolver chamam o PATCH e refletem na hora", async () => {
  const srv = montarBackendFalso({
    handoffs: {
      pendentes: 1,
      items: [
        { id: "h1", status: "pendente", conversation_id: "c1", trigger: "lead_pediu", disparado_por: "regra", reason: "", criado_em: T },
      ],
    },
  });
  render(<PaginaHandoffs />);
  await userEvent.click(await screen.findByRole("button", { name: /assumir/i }));
  expect(srv.ultimoPatch).toEqual(["/api/handoffs/h1", { status: "assumido" }]);
  expect(await screen.findByRole("button", { name: /resolver/i })).toBeVisible();
});

it("não oferece transição inválida — resolvido não volta", async () => {
  montarBackendFalso({
    handoffs: {
      pendentes: 0,
      items: [
        { id: "h1", status: "resolvido", conversation_id: "c1", trigger: "lead_pediu", disparado_por: "regra", reason: "", criado_em: T },
      ],
    },
  });
  render(<PaginaHandoffs />);
  const item = await screen.findByTestId("handoff-h1");
  expect(within(item).queryByRole("button", { name: /assumir|resolver/i })).toBeNull();
});

it("409 do backend aparece como mensagem, e o item volta ao estado real", async () => {
  montarBackendFalso({
    handoffs: {
      pendentes: 1,
      items: [
        { id: "h1", status: "pendente", conversation_id: "c1", trigger: "guardrail", disparado_por: "regra", reason: "", criado_em: T },
      ],
    },
    patchErro: 409,
  });
  render(<PaginaHandoffs />);
  await userEvent.click(await screen.findByRole("button", { name: /assumir/i }));
  expect(await screen.findByRole("alert")).toBeVisible();
  expect(await screen.findByRole("button", { name: /assumir/i })).toBeVisible();
});

it("um handoff criado no backend entra na fila SEM reload", async () => {
  const srv = montarBackendFalso({ handoffs: { pendentes: 0, items: [] } });
  render(<PaginaHandoffs />);
  expect(await screen.findByTestId("estado-vazio")).toBeVisible();
  srv.responderComHandoff({
    id: "h9",
    status: "pendente",
    conversation_id: "c9",
    trigger: "cotacao_indisponivel",
    disparado_por: "regra",
    reason: "",
    criado_em: T,
  });
  await srv.push({ type: "handoff.created", handoff: { id: "h9" } });
  expect(await screen.findByTestId("handoff-h9")).toBeVisible();
});

it("o push recarrega do backend, não monta o item a partir do frame", async () => {
  // Item montado no cliente diverge do banco na primeira mudança de schema — e o
  // admin existe para dizer a verdade sobre o banco.
  const srv = montarBackendFalso({ handoffs: { pendentes: 0, items: [] } });
  render(<PaginaHandoffs />);
  await screen.findByTestId("estado-vazio");
  const antes = srv.chamadas("/api/handoffs");
  await srv.push({ type: "handoff.created", handoff: { id: "h9" } });
  expect(srv.chamadas("/api/handoffs")).toBe(antes + 1);
});

it("cada item leva à conversa de origem — e não ao /chat", async () => {
  montarBackendFalso({
    handoffs: {
      pendentes: 1,
      items: [
        { id: "h1", conversation_id: "c7", status: "pendente", trigger: "guardrail", disparado_por: "regra", reason: "", criado_em: T },
      ],
    },
  });
  const { container } = render(<PaginaHandoffs />);
  expect(await screen.findByRole("link", { name: /c7/ })).toHaveAttribute(
    "href",
    "/admin/conversas/c7",
  );
  expect(container.querySelectorAll('a[href^="/chat"]')).toHaveLength(0);
});

it("`cotacao_recusada` não tem rótulo na fila — recusa não vira handoff", async () => {
  // Os sete gatilhos são os da tabela fechada (§3). Recusa é desfecho de negócio.
  const { GATILHOS_HANDOFF } = await import("../../../web/src/api/tipos");
  expect(GATILHOS_HANDOFF).toHaveLength(7);
  expect([...GATILHOS_HANDOFF]).not.toContain("cotacao_recusada");
});
