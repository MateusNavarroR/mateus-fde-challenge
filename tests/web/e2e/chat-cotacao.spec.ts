import { expect, test } from "@playwright/test";
import { subirCenario } from "./ajuda/cenario";

/**
 * Estado real que produz esta evidência:
 *
 *   QUOTE_FAILURE_RATE=0 QUOTE_SLOW_RATE=0 \
 *     docker compose up -d --force-recreate quote-api
 */
test("a cotação sai com preço, carência e pro-rata", async ({ page }) => {
  await subirCenario("feliz", page);
  await page.goto("/chat");
  await page.getByRole("button", { name: /nova conversa/i }).click();
  await page
    .getByRole("textbox")
    .fill("28 anos, carro 2019, cep 07XXX-XXX, plano completo, começo dia 17/10");
  await page.getByRole("textbox").press("Enter");

  const bloco = page.getByTestId("bloco-cotacao");
  await expect(bloco).toBeVisible({ timeout: 20_000 });
  await expect(bloco).toContainText(/R\$ ?\d/); // preço
  await expect(bloco).toContainText(/30 dias/); // carência — invariante 2
  await expect(bloco).toContainText(/Franquia/i); // sempre
  await expect(bloco).toContainText(/proporcional|integral/); // pro-rata, ou a ausência dela
  await expect(bloco).not.toContainText(/CEP|agravo/i); // agravo nunca é mencionado

  await expect(bloco).toHaveAttribute("data-quote-id", /.+/);
  await expect(page.getByTestId("marca-bug")).toHaveCount(0);

  await page.screenshot({ path: "docs/evidencia-ui/04-chat-cotacao.png", fullPage: true });
});
