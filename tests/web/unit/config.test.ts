import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import config from "../../../web/vite.config";

/**
 * O invariante 14b não é sobre o compose só: um `vite dev` publica em localhost
 * por default, mas `vite preview` e qualquer `--host` acidental furam isso. O
 * teste trava a configuração no arquivo, que é onde alguém a mudaria.
 */
describe("configuração do vite", () => {
  it("publica só em 127.0.0.1, nunca em 0.0.0.0 (CLAUDE.md 14b)", () => {
    expect(config.server?.host).toBe("127.0.0.1");
    expect(config.preview?.host).toBe("127.0.0.1");
  });

  it("não deixa host aberto em nenhum script do package.json", () => {
    const pkg = JSON.parse(readFileSync("web/package.json", "utf8"));
    for (const [nome, cmd] of Object.entries<string>(pkg.scripts)) {
      expect(cmd, nome).not.toMatch(/--host(\s|=|$)/);
      expect(cmd, nome).not.toContain("0.0.0.0");
    }
  });

  it("proxya /api para o backend local, para haver uma origem só", () => {
    const proxy = config.server?.proxy as Record<string, { target: string; ws?: boolean }>;
    expect(proxy["/api"]?.target).toBe("http://127.0.0.1:8080");
    // Sem isto o WebSocket não passa pelo dev server.
    expect(proxy["/api"]?.ws).toBe(true);
  });
});
