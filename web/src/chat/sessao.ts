/**
 * Sessão do lead: **retoma ao carregar, cria por botão**.
 *
 * `DECISOES-FECHADAS.md` §8: sempre-nova é o comportamento certo do botão, não
 * do carregamento. A demonstração é uma janela de 37 s, e apertar F5 por
 * impaciência é o gesto mais provável do mundo — um carregamento que sempre cria
 * conversa destruiria exatamente o que se quer mostrar.
 */

import { ErroApi, ROTAS, api, post } from "../api/cliente";
import type { Conversation, ConversationDetail } from "../api/tipos";

export const CHAVE = "autoseguro.conversation_id";

type Deps = {
  post: (url: string, corpo: unknown) => Promise<{ id: string }>;
  getConversa?: (id: string) => Promise<{ id: string } | null>;
};

function ler(): string | null {
  try {
    const v = localStorage.getItem(CHAVE);
    return v && v.length > 0 ? v : null;
  } catch {
    // localStorage indisponível não pode quebrar a tela: a conversa segue,
    // só não sobrevive ao reload.
    return null;
  }
}

function gravar(id: string): void {
  try {
    localStorage.setItem(CHAVE, id);
  } catch {
    /* idem */
  }
}

function esquecer(): void {
  try {
    localStorage.removeItem(CHAVE);
  } catch {
    /* idem */
  }
}

const CHAVE_SESSAO = "autoseguro:sessao";

/**
 * Identificador desta sessão de navegador. Aleatório, gerado localmente, sem nenhum
 * dado do lead.
 *
 * O instinto original — não mandar `external_ref` de jeito nenhum, para que ele não
 * possa carregar telefone — estava certo sobre o risco e errado sobre a solução: o
 * backend caía num literal fixo, e a `UNIQUE (channel, external_ref)` fazia a segunda
 * conversa daquele banco falhar com 500, para sempre.
 *
 * Mandar um id de sessão aleatório mantém a garantia (não há dado do lead aqui) e
 * ainda dá semântica ao campo: **mesma sessão de navegador, mesma conversa**, que é
 * exatamente a retomada. "Nova conversa" gera sessão nova, logo conversa nova.
 */
function idDeSessao(): string {
  try {
    const gravado = localStorage.getItem(CHAVE_SESSAO);
    if (gravado !== null && gravado !== "") return gravado;
  } catch {
    /* localStorage indisponível: o id vira efêmero, e o backend gera o dele */
  }
  const novo =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `s-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  try {
    localStorage.setItem(CHAVE_SESSAO, novo);
  } catch {
    /* idem */
  }
  return novo;
}

function novaSessao(): string {
  try {
    localStorage.removeItem(CHAVE_SESSAO);
  } catch {
    /* idem */
  }
  return idDeSessao();
}

export async function abrirOuRetomar(deps: Deps): Promise<string> {
  const gravado = ler();
  if (gravado !== null && deps.getConversa) {
    const existente = await deps.getConversa(gravado);
    // Se a gravada já não existe no backend (banco recriado), cria outra.
    if (existente !== null && existente !== undefined) return gravado;
  }
  const criada = await deps.post(ROTAS.conversas(), {
    channel: "web",
    external_ref: idDeSessao(),
  });
  gravar(criada.id);
  return criada.id;
}

export async function novaConversa(deps: Pick<Deps, "post">): Promise<string> {
  esquecer();
  // Sessão nova ⇒ `external_ref` novo ⇒ conversa nova, sem colidir com a anterior.
  const criada = await deps.post(ROTAS.conversas(), {
    channel: "web",
    external_ref: novaSessao(),
  });
  gravar(criada.id);
  return criada.id;
}

/**
 * O que a tela usa. Ao retomar, o histórico vem de `GET /api/conversations/{id}`
 * — já mascarado, já ordenado por `index` — **antes** de o socket abrir, e o
 * `hello` sai com o `last_index` desse histórico: assim a reconexão não pede de
 * volta o que a tela acabou de buscar.
 */
export async function abrirSessao(): Promise<{ id: string; detalhe: ConversationDetail | null }> {
  let detalhe: ConversationDetail | null = null;

  const id = await abrirOuRetomar({
    post: (url, corpo) => post<Conversation>(url, corpo),
    getConversa: async (gravado) => {
      try {
        detalhe = await api.conversa(gravado);
        return detalhe;
      } catch (e) {
        if (e instanceof ErroApi && e.tipo === "nao_encontrado") {
          detalhe = null;
          return null;
        }
        throw e;
      }
    },
  });

  return { id, detalhe };
}

export async function reiniciarSessao(): Promise<string> {
  return novaConversa({ post: (url, corpo) => post<Conversation>(url, corpo) });
}
