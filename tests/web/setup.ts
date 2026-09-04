import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";
import { _reiniciarEventos } from "../../web/src/admin/useEventos";
import { WebSocketFalso } from "./fakes/websocket-falso";

beforeEach(() => {
  WebSocketFalso.reiniciar();
});

afterEach(() => {
  cleanup();
  // O socket de eventos é um singleton de sessão: sem isto ele vazaria de um
  // caso para o outro e a contagem de sockets deixaria de significar algo.
  _reiniciarEventos();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  WebSocketFalso.reiniciar();
  try {
    localStorage.clear();
  } catch {
    /* alguns casos derrubam o localStorage de propósito */
  }
});
