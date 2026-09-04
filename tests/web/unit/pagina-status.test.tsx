import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { PaginaStatus } from "../../../web/src/admin/PaginaStatus";
import { montarBackendFalso } from "../fakes/backend-falso";

it("mostra o /health do legado COM a ressalva de que ele mente", async () => {
  // O /health do legado responde 200 com 100% das cotações falhando. Exibi-lo sem
  // a nota é como se produz um monitor que mente (openapi.yaml, /api/health).
  montarBackendFalso({
    status: {
      upstream_health: {
        status: "ok",
        latency_ms: 3,
        nota: "responde 200 mesmo com 100% das cotações falhando",
      },
      janela: {
        total: 50,
        sucesso: 0,
        taxa_sucesso: 0,
        p50_ms: 3,
        p95_ms: 8004,
        por_outcome: { transient: 50 },
      },
      breaker: {
        estado: "aberto",
        falhas_consecutivas: 12,
        aberto_desde: "2026-01-01T10:00:00Z",
        reabre_em: "2026-01-01T10:00:20Z",
      },
      ultimas_tentativas: [],
    },
  });
  render(<PaginaStatus />);
  expect(await screen.findByTestId("upstream")).toHaveTextContent(/ok/);
  expect(screen.getByTestId("upstream")).toHaveTextContent(
    /mesmo com 100% das cotações falhando/,
  );
});

it("o breaker aberto é o elemento mais visível da tela", async () => {
  montarBackendFalso({
    status: {
      breaker: {
        estado: "aberto",
        falhas_consecutivas: 12,
        aberto_desde: "2026-01-01T10:00:00Z",
        reabre_em: "2026-01-01T10:00:20Z",
      },
      janela: { total: 50, sucesso: 0, taxa_sucesso: 0, p50_ms: 3, p95_ms: 8004 },
      upstream_health: { status: "ok" },
      ultimas_tentativas: [],
    },
  });
  render(<PaginaStatus />);
  const b = await screen.findByTestId("breaker");
  expect(b).toHaveAttribute("data-estado", "aberto");
  // Quando reabre, não só que abriu.
  expect(b).toHaveTextContent(/reabre/i);
  expect(b).toHaveTextContent("12");
});

it("os três estados do breaker são visualmente distintos", async () => {
  const classes = new Set<string>();
  for (const estado of ["fechado", "aberto", "meia_abertura"]) {
    montarBackendFalso({
      status: {
        breaker: { estado, falhas_consecutivas: 0 },
        janela: { total: 1, sucesso: 1, taxa_sucesso: 1, p50_ms: 3, p95_ms: 3 },
        upstream_health: { status: "ok" },
        ultimas_tentativas: [],
      },
    });
    const { unmount } = render(<PaginaStatus />);
    classes.add((await screen.findByTestId("breaker")).className);
    unmount();
  }
  expect(classes.size).toBe(3);
});

it("p95 é exibido junto de p50 e taxa de sucesso", async () => {
  montarBackendFalso({
    status: {
      janela: {
        total: 50,
        sucesso: 45,
        taxa_sucesso: 0.9,
        p50_ms: 120,
        p95_ms: 8004,
        por_outcome: { ok: 45, timeout: 3, transient: 2 },
      },
      breaker: { estado: "fechado", falhas_consecutivas: 0 },
      upstream_health: { status: "ok" },
      ultimas_tentativas: [],
    },
  });
  render(<PaginaStatus />);
  expect(await screen.findByTestId("taxa-sucesso")).toHaveTextContent("90");
  expect(screen.getByTestId("p50")).toHaveTextContent(/120/);
  // As lentas de 8 s aparecem — é justamente o que se quer ver.
  expect(screen.getByTestId("p95")).toHaveTextContent(/8[.,]0\s*s|8004/);
  expect(screen.getByTestId("por-outcome")).toHaveTextContent(/timeout/);
});

it("cada tentativa recente leva à conversa que a originou", async () => {
  montarBackendFalso({
    status: {
      ultimas_tentativas: [
        {
          id: "a1",
          attempt: 2,
          http_status: null,
          latency_ms: 12_000,
          outcome: "timeout",
          criado_em: "2026-01-01T10:00:00Z",
          quote_id: "q1",
          conversation_id: "c7",
        },
      ],
      janela: { total: 1, sucesso: 0, taxa_sucesso: 0, p50_ms: 12000, p95_ms: 12000 },
      breaker: { estado: "fechado", falhas_consecutivas: 1 },
      upstream_health: { status: "ok" },
    },
  });
  render(<PaginaStatus />);
  expect(await screen.findByRole("link", { name: /c7/ })).toHaveAttribute(
    "href",
    "/admin/conversas/c7",
  );
});

it("upstream inalcançável não some da tela nem vira zero", async () => {
  montarBackendFalso({
    status: {
      upstream_health: { status: "unreachable", latency_ms: null },
      janela: { total: 0, sucesso: 0, taxa_sucesso: 0, p50_ms: 0, p95_ms: 0 },
      breaker: { estado: "aberto", falhas_consecutivas: 5 },
      ultimas_tentativas: [],
    },
  });
  render(<PaginaStatus />);
  expect(await screen.findByTestId("upstream")).toHaveTextContent(/inalcanç/i);
});
