import { expect, test } from "@playwright/test";
import { popularComDumpDeExemplo } from "./ajuda/cenario";

const ROTAS = ["/chat", "/admin/conversas", "/admin/status", "/admin/handoffs"];

for (const [nome, w, h] of [
  ["1440", 1440, 900],
  ["390", 390, 844],
] as const) {
  test(`sem rolagem horizontal em ${nome}px, nas quatro telas`, async ({ page, context }) => {
    await popularComDumpDeExemplo(context);
    await page.setViewportSize({ width: w, height: h });

    for (const rota of ROTAS) {
      await page.goto(rota);
      await page.waitForLoadState("networkidle");
      const sobra = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(sobra, `${rota} rola na horizontal em ${nome}px`).toBeLessThanOrEqual(0);
    }

    await page.goto("/admin/conversas");
    await page.screenshot({
      path: `docs/evidencia-ui/05-responsivo-${nome}.png`,
      fullPage: true,
    });
  });
}
