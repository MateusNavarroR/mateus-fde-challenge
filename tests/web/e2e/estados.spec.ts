import { expect, test } from "@playwright/test";
import { pararBackend, recriarBancoVazio, religarBackend } from "./ajuda/cenario";

/**
 * Estado real: `docker compose down -v && docker compose up -d` — banco
 * recriado, zero linha. É o primeiro estado que o avaliador vê depois de subir o
 * compose, e é por isso que ele precisa explicar em vez de parecer defeito.
 */
test("estados vazios com o banco recém-criado", async ({ page }) => {
  await recriarBancoVazio(page);

  for (const rota of ["/admin/conversas", "/admin/status", "/admin/handoffs"]) {
    await page.goto(rota);
    await expect(page.getByTestId("estado-vazio")).toBeVisible();
    // Vazio não é erro.
    await expect(page.getByRole("alert")).toHaveCount(0);
  }

  await page.goto("/admin/conversas");
  await page.screenshot({ path: "docs/evidencia-ui/06-estados-vazios.png", fullPage: true });
});

/** Estado real: `docker compose stop app`, com o front no ar. */
test("estados de erro com o backend parado", async ({ page }) => {
  pararBackend();

  await page.goto("/admin/status");
  await expect(page.getByRole("alert")).toContainText(/indisponível|docker compose/i);

  await page.goto("/chat");
  await expect(page.getByRole("status")).toContainText(/reconectando/i);

  await page.screenshot({ path: "docs/evidencia-ui/07-estados-de-erro.png", fullPage: true });
  await religarBackend(page);
});
