import { expect, test } from "@playwright/test";
import { dispararCotacoes, subirCenario } from "./ajuda/cenario";

/**
 * Estado real: cenário degradado mais seis cotações seguidas, acima do
 * `breaker_limiar=5`. O disjuntor abre porque a `/quote` falhou de verdade seis
 * vezes, não porque alguém escreveu "aberto" numa fixture.
 */
test("status com a /quote em falha total e o breaker aberto", async ({ page, context }) => {
  await subirCenario("degradado", page);
  await dispararCotacoes(context, 6);

  await page.goto("/admin/status");
  await expect(page.getByTestId("breaker")).toHaveAttribute("data-estado", "aberto");
  await expect(page.getByTestId("taxa-sucesso")).toHaveText(/0\s*%/);
  await expect(page.getByTestId("p95")).not.toHaveText("0");
  // O legado ainda diz ok — é o ponto da ressalva.
  await expect(page.getByTestId("upstream")).toContainText(/ok/);
  await expect(page.getByTestId(/^tentativa-/).first()).toContainText(/50[0235]|timeout/);

  await page.screenshot({ path: "docs/evidencia-ui/02-status-breaker-aberto.png", fullPage: true });
});

test("a seção de custo está na mesma tela, com âncora própria", async ({ page }) => {
  await page.goto("/admin/status#custo");
  const secao = page.getByRole("region", { name: /custo/i });
  await expect(secao).toBeInViewport();
  await expect(secao.getByTestId("vigencia")).toContainText(/\d{4}-\d{2}-\d{2}|n\/a/);
});
