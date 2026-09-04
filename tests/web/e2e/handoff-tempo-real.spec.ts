import { expect, test } from "@playwright/test";
import { conversarUmaVez, subirCenario } from "./ajuda/cenario";

/**
 * Estado real: `QUOTE_FAILURE_RATE=1.0 docker compose up -d --force-recreate
 * quote-api`, mais uma conversa dirigida numa segunda aba. O handoff nasce de
 * uma conversa de verdade, não de uma linha injetada no banco.
 */
test("um handoff criado no backend aparece na fila sem reload", async ({ page, context }) => {
  await subirCenario("degradado", page);
  await page.goto("/admin/handoffs");
  const antes = await page.getByTestId(/^handoff-/).count();

  const navegacoes: string[] = [];
  page.on("framenavigated", (f) => navegacoes.push(f.url()));

  const lead = await context.newPage();
  await conversarUmaVez(
    lead,
    "28 anos, carro 2019, cep 07XXX-XXX, completo, começo dia 17/10",
  );

  await expect(page.getByTestId(/^handoff-/)).toHaveCount(antes + 1, { timeout: 60_000 });
  await expect(page.getByTestId("badge-pendentes")).toHaveText(String(antes + 1));
  expect(navegacoes, "a fila recarregou a página — o push não funcionou").toEqual([]);

  await page.screenshot({ path: "docs/evidencia-ui/01-handoff-tempo-real.png", fullPage: true });
});
