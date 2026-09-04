import { readFileSync } from "node:fs";
import { parse } from "yaml";
import { describe, expect, it } from "vitest";
import {
  AUTORES,
  ESTADOS_CONVERSA,
  MOTIVOS_RECUSA,
  OUTCOMES,
  STATUS_HANDOFF,
  STATUS_JOB,
  STATUS_MENSAGEM,
} from "../../../web/src/api/tipos";

const spec = parse(readFileSync("docs/openapi.yaml", "utf8"));
const enumDe = (nome: string): string[] => spec.components.schemas[nome].enum;

describe("os enums da UI são os do contrato congelado", () => {
  it.each([
    ["ConversationState", ESTADOS_CONVERSA],
    ["MessageStatus", STATUS_MENSAGEM],
    ["QuoteOutcome", OUTCOMES],
    ["QuoteJobStatus", STATUS_JOB],
    ["HandoffStatus", STATUS_HANDOFF],
  ] as const)("%s", (nome, nosso) => {
    expect([...nosso].sort()).toEqual([...enumDe(nome)].sort());
  });

  it("autor tem os quatro valores, e `sistema` é um deles", () => {
    const doContrato = spec.components.schemas.Message.properties.autor.enum;
    expect([...AUTORES].sort()).toEqual([...doContrato].sort());
    expect(AUTORES).toContain("sistema");
  });

  it("os cinco outcomes existem — cada um implica uma ação distinta (API-COTACAO §7)", () => {
    expect(OUTCOMES).toHaveLength(5);
  });

  it("os motivos de recusa são os três do contrato, sem `default` que esconda um novo", () => {
    const doContrato: (string | null)[] = spec.components.schemas.Quote.properties.motivo_recusa.enum;
    expect([...MOTIVOS_RECUSA].sort()).toEqual(
      doContrato.filter((v): v is string => v !== null).sort(),
    );
  });
});
