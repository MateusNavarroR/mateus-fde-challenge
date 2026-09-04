import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import type { BrowserContext, Page } from "@playwright/test";

/**
 * Os auxiliares que produzem **estado real**.
 *
 * Cada evidência declara o comando que a produz, e o teste falha se o estado não
 * aparecer. Screenshot com dado de exemplo não vale: é a diferença entre provar
 * e ilustrar.
 *
 * O restart do container da `/quote` não é zelo: o RNG do legado é um fluxo
 * global e contínuo do **processo**, então sem `--force-recreate` a seed não
 * significa nada (CLAUDE.md, reprodutibilidade).
 */

export type Cenario = "degradado" | "feliz";

const AMBIENTE: Record<Cenario, Record<string, string>> = {
  // 100 % das cotações falham: é o cenário que torna a degradação visível.
  degradado: { QUOTE_FAILURE_RATE: "1.0", QUOTE_SLOW_RATE: "0", QUOTE_SEED: "42" },
  feliz: { QUOTE_FAILURE_RATE: "0", QUOTE_SLOW_RATE: "0", QUOTE_SEED: "42" },
};

function compose(args: string[], env: Record<string, string> = {}): void {
  execFileSync("docker", ["compose", ...args], {
    stdio: "inherit",
    env: { ...process.env, ...env },
    timeout: 180_000,
  });
}

async function esperarBackend(page: Page, tentativas = 60): Promise<void> {
  for (let i = 0; i < tentativas; i += 1) {
    try {
      const r = await page.request.get("/api/health");
      if (r.ok()) return;
    } catch {
      /* ainda subindo */
    }
    await page.waitForTimeout(1_000);
  }
  throw new Error("o backend não respondeu /api/health a tempo");
}

export async function subirCenario(cenario: Cenario, page?: Page): Promise<void> {
  compose(["up", "-d", "--force-recreate", "quote-api"], AMBIENTE[cenario]);
  if (page) await esperarBackend(page);
}

export async function recriarBancoVazio(page?: Page): Promise<void> {
  compose(["down", "-v"]);
  compose(["up", "-d"]);
  if (page) await esperarBackend(page);
}

export function pararBackend(): void {
  compose(["stop", "app"]);
}

export async function religarBackend(page?: Page): Promise<void> {
  compose(["start", "app"]);
  if (page) await esperarBackend(page);
}

/** Uma conversa real, conduzida pela UI. Nada aqui é injetado no banco. */
export async function conversarUmaVez(page: Page, fala: string): Promise<void> {
  await page.goto("/chat");
  await page.getByRole("button", { name: /nova conversa/i }).click();
  await page.getByRole("textbox").fill(fala);
  await page.getByRole("textbox").press("Enter");
}

export async function dispararCotacoes(contexto: BrowserContext, quantas: number): Promise<void> {
  // Em série, sempre: as suítes que dependem de QUOTE_SEED nunca rodam em
  // paralelo, e o breaker conta falhas consecutivas.
  for (let i = 0; i < quantas; i += 1) {
    const p = await contexto.newPage();
    await conversarUmaVez(p, "tenho 28 anos, carro 2019, plano completo, começo dia 17/10");
    await p.waitForTimeout(2_000);
    await p.close();
  }
}

/**
 * `scripts/seed_demo.sh` é dependência declarada do Núcleo e ainda não existe.
 * Enquanto não existir, as telas são populadas do único jeito honesto: com
 * conversas de verdade, conduzidas pela UI.
 */
export async function popularComDumpDeExemplo(contexto: BrowserContext): Promise<void> {
  if (existsSync("scripts/seed_demo.sh")) {
    execFileSync("bash", ["scripts/seed_demo.sh"], { stdio: "inherit", timeout: 180_000 });
    return;
  }
  await dispararCotacoes(contexto, 2);
}
