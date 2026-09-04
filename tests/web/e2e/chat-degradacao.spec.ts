import { expect, test } from "@playwright/test";
import { subirCenario } from "./ajuda/cenario";

/**
 * Estado real que produz esta evidência:
 *
 *   QUOTE_FAILURE_RATE=1.0 QUOTE_SLOW_RATE=0 QUOTE_SEED=42 \
 *     docker compose up -d --force-recreate quote-api
 *
 * O `--force-recreate` é obrigatório: o RNG do legado é um fluxo global do
 * processo, e sem restart a seed não significa nada.
 */
test("degradação visível: aviso, reforço e encaminhamento em um turno só", async ({ page }) => {
  await subirCenario("degradado", page);
  await page.goto("/chat");
  await page.getByRole("button", { name: /nova conversa/i }).click();

  const t0 = Date.now();
  await page
    .getByRole("textbox")
    .fill("tenho 28 anos, carro 2019, cep 07XXX-XXX, começo dia 17/10, quero o completo");
  await page.getByRole("textbox").press("Enter");

  await expect(page.getByTestId("digitando")).toBeVisible();

  await expect(
    page.getByText("Tô buscando o valor no sistema e ele tá lento agora. Já te trago, tá?"),
  ).toBeVisible({ timeout: 15_000 });
  // O aviso não é imediato…
  expect(Date.now() - t0).toBeGreaterThan(5_000);
  // …e o turno não terminou.
  await expect(page.getByTestId("digitando")).toBeVisible();

  await expect(
    page.getByText(
      "Ainda tô aqui, viu? O sistema não me devolveu ainda. Assim que sair eu te mando.",
    ),
  ).toBeVisible({ timeout: 25_000 });
  await expect(page.getByTestId("digitando")).toBeVisible();

  await expect(page.getByText(/Não consegui confirmar o valor agora/)).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByText(/Já passei sua conversa pra um atendente da equipe/)).toBeVisible();
  await expect(page.getByRole("textbox")).toBeDisabled();
  await expect(page.getByTestId("digitando")).toBeHidden();

  // Nenhum valor monetário apareceu em nenhum momento do caminho degradado.
  await expect(page.getByText(/R\$/)).toHaveCount(0);

  await page.screenshot({ path: "docs/evidencia-ui/03-chat-degradacao.png", fullPage: true });
});

test("a reconexão traz de volta o que chegou com o socket caído", async ({ page, context }) => {
  await subirCenario("degradado", page);
  await page.goto("/chat");
  await page.getByRole("button", { name: /nova conversa/i }).click();
  await page.getByRole("textbox").fill("quero cotar, 28 anos, carro 2019");
  await page.getByRole("textbox").press("Enter");

  await context.setOffline(true);
  await expect(page.getByRole("status")).toContainText(/reconectando/i);
  // ① e ② são emitidos com a tela cega.
  await page.waitForTimeout(25_000);
  await context.setOffline(false);

  await expect(
    page.getByText("Tô buscando o valor no sistema e ele tá lento agora. Já te trago, tá?"),
  ).toBeVisible({ timeout: 30_000 });
  await expect(
    page.getByText(
      "Ainda tô aqui, viu? O sistema não me devolveu ainda. Assim que sair eu te mando.",
    ),
  ).toBeVisible();
});
