import { readFileSync } from "node:fs";
import { render, screen, within } from "@testing-library/react";
import { expect, it } from "vitest";
import { PaginaStatus } from "../../../web/src/admin/PaginaStatus";
import { montarBackendFalso } from "../fakes/backend-falso";

const usageMinimo = () => ({
  total: {
    tokens_in: 900,
    tokens_out: 120,
    cache_read: 700,
    cache_write: 200,
    taxa_acerto_cache: 0.7,
    custo_usd: 0.0031,
    pricing_vigencia: "2026-01-15",
    latency_p50_ms: 800,
  },
  por_provider: [],
  por_conversa: [],
});

const usageComCusto = (vigencia: string) => ({
  ...usageMinimo(),
  total: { ...usageMinimo().total, pricing_vigencia: vigencia },
});

it("é uma seção com título próprio e âncora, não um rodapé", async () => {
  montarBackendFalso({ usage: usageMinimo() });
  render(<PaginaStatus />);
  const secao = await screen.findByRole("region", { name: /custo/i });
  expect(secao).toHaveAttribute("id", "custo");
  expect(within(secao).getByRole("heading", { level: 2 })).toBeVisible();
});

it("cache_read nulo mostra n/a, NUNCA 0 %", async () => {
  // O Ollama não popula cache_read. Zero diria "o cache não acertou"; a verdade é
  // "não existe cache neste caminho" (CLAUDE.md 26, migração 0002).
  montarBackendFalso({
    usage: {
      total: {
        tokens_in: 900,
        tokens_out: 120,
        cache_read: null,
        cache_write: null,
        taxa_acerto_cache: null,
        custo_usd: null,
        pricing_vigencia: null,
        latency_p50_ms: 800,
      },
      por_provider: [],
      por_conversa: [],
    },
  });
  render(<PaginaStatus />);
  const secao = await screen.findByRole("region", { name: /custo/i });
  expect(within(secao).getByTestId("taxa-cache")).toHaveTextContent("n/a");
  expect(within(secao).getByTestId("taxa-cache")).not.toHaveTextContent("0");
  expect(within(secao).getByTestId("custo-total")).toHaveTextContent("n/a");
});

it("cache_read zero de verdade mostra 0 % — n/a e zero são coisas diferentes", async () => {
  montarBackendFalso({
    usage: {
      total: {
        tokens_in: 900,
        tokens_out: 120,
        cache_read: 0,
        cache_write: 0,
        taxa_acerto_cache: 0,
        custo_usd: 0.004,
        pricing_vigencia: "2026-01-15",
        latency_p50_ms: 800,
      },
      por_provider: [],
      por_conversa: [],
    },
  });
  render(<PaginaStatus />);
  expect(
    within(await screen.findByRole("region", { name: /custo/i })).getByTestId("taxa-cache"),
  ).toHaveTextContent("0");
});

it("mostra Anthropic e Ollama lado a lado, cada um com o seu tratamento de cache", async () => {
  montarBackendFalso({
    usage: {
      total: {
        tokens_in: 3000,
        tokens_out: 400,
        cache_read: 2100,
        cache_write: 900,
        taxa_acerto_cache: 0.7,
        custo_usd: 0.0123,
        pricing_vigencia: "2026-01-15",
        latency_p50_ms: 900,
      },
      por_provider: [
        { provider: "anthropic", tokens_in: 2000, tokens_out: 300, cache_read: 2100, cache_write: 900, taxa_acerto_cache: 0.7, custo_usd: 0.0123, pricing_vigencia: "2026-01-15", latency_p50_ms: 900 },
        { provider: "ollama", tokens_in: 1000, tokens_out: 100, cache_read: null, cache_write: null, taxa_acerto_cache: null, custo_usd: null, pricing_vigencia: null, latency_p50_ms: 1500 },
      ],
      por_conversa: [],
    },
  });
  render(<PaginaStatus />);
  const secao = await screen.findByRole("region", { name: /custo/i });
  expect(within(secao).getByRole("row", { name: /anthropic/i })).toHaveTextContent("70");
  expect(within(secao).getByRole("row", { name: /ollama/i })).toHaveTextContent("n/a");
});

it("o custo mostra a vigência do preço — sem procedência é um número solto", async () => {
  montarBackendFalso({ usage: usageComCusto("2026-01-15") });
  render(<PaginaStatus />);
  expect(
    within(await screen.findByRole("region", { name: /custo/i })).getByTestId("vigencia"),
  ).toHaveTextContent("2026-01-15");
});

it("a tela NÃO recalcula custo a partir de tabela de preço", () => {
  // O custo vem calculado do backend (CLAUDE.md 26). Duas origens de preço é como
  // um custo histórico deixa de ser auditável.
  const fonte = readFileSync("web/src/admin/PainelCusto.tsx", "utf8");
  expect(fonte).not.toMatch(/model_pricing|per_million|\* *1_?000_?000|preco_por_token/i);
});

it("o custo por conversa liga para o detalhe da conversa", async () => {
  montarBackendFalso({
    usage: {
      total: usageMinimo().total,
      por_provider: [],
      por_conversa: [
        { conversation_id: "c7", turnos: 6, tokens_in: 900, tokens_out: 200, cache_read: 700, cache_write: 200, taxa_acerto_cache: 0.78, custo_usd: 0.0031, pricing_vigencia: "2026-01-15", latency_p50_ms: 800 },
      ],
    },
  });
  render(<PaginaStatus />);
  expect(await screen.findByRole("link", { name: /c7/ })).toHaveAttribute(
    "href",
    "/admin/conversas/c7",
  );
});

it("sem nenhum turno gravado, a seção existe e explica — não some", async () => {
  montarBackendFalso({
    usage: {
      total: {
        tokens_in: 0,
        tokens_out: 0,
        cache_read: null,
        cache_write: null,
        taxa_acerto_cache: null,
        custo_usd: null,
        pricing_vigencia: null,
        latency_p50_ms: null,
      },
      por_provider: [],
      por_conversa: [],
    },
  });
  render(<PaginaStatus />);
  const secao = await screen.findByRole("region", { name: /custo/i });
  expect(within(secao).getByTestId("estado-vazio")).toBeVisible();
});
