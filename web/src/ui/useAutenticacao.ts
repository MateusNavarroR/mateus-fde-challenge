import { useCallback, useEffect, useState } from "react";
import { api, type EstadoAuth } from "../api/cliente";

/**
 * O estado de autenticação, **compartilhado entre telas** e consultado uma vez.
 *
 * Por que um singleton de módulo e não um `useRecurso` por componente: três lugares
 * precisam da mesma resposta ao mesmo tempo — a capa (para saber para onde aponta a
 * 2ª via), o roteador (para decidir entre `/admin` e o login) e a própria tela de
 * login (para saber se já entrou). Três `useRecurso` fariam três chamadas e, pior,
 * poderiam discordar por uma fração de segundo: a capa oferecendo o admin enquanto o
 * roteador já decidiu pedir senha.
 *
 * O estado **desconhecido** é o terceiro, e é o que evita o defeito mais feio desta
 * tela: mostrar o login por um instante para quem não precisa dele. Enquanto a
 * resposta não chega, ninguém decide nada.
 */

export type Autenticacao =
  | { situacao: "desconhecido" }
  | { situacao: "conhecido"; exigido: boolean; autenticado: boolean };

/** Backend fora do ar não é "precisa de login": é indisponibilidade, e a tela de
 * erro que já existe sabe dizer isso melhor do que um formulário de senha. */
const OTIMISTA: Autenticacao = { situacao: "conhecido", exigido: false, autenticado: true };

let cache: Autenticacao = { situacao: "desconhecido" };
let emVoo: Promise<void> | null = null;
const ouvintes = new Set<(a: Autenticacao) => void>();

function publicar(novo: Autenticacao): void {
  cache = novo;
  for (const ouvinte of ouvintes) ouvinte(novo);
}

function consultar(): Promise<void> {
  // Uma consulta por vez, mesmo com cinco componentes montando juntos.
  emVoo ??= api
    .estadoAutenticacao()
    .then((e: EstadoAuth) =>
      publicar({ situacao: "conhecido", exigido: e.exigido, autenticado: e.autenticado }),
    )
    .catch(() => {
      // Qualquer falha — backend parado, 404 de uma instalação sem as rotas de
      // login — cai no otimista. Nunca no pessimista: pedir senha porque a API não
      // respondeu tranca quem tem acesso e não impede quem não tem, já que a porta
      // de verdade é o `exigir_admin` do backend, não esta tela.
      publicar(OTIMISTA);
    })
    .finally(() => {
      emVoo = null;
    });
  return emVoo;
}

/** Força uma releitura — depois de entrar ou sair, o estado mudou no servidor. */
export function reconsultarAutenticacao(): Promise<void> {
  publicar({ situacao: "desconhecido" });
  return consultar();
}

/** Só para os testes: devolve o módulo ao estado de quem acabou de abrir a aba. */
export function _reiniciarAutenticacao(): void {
  cache = { situacao: "desconhecido" };
  emVoo = null;
  ouvintes.clear();
}

export function useAutenticacao(): Autenticacao {
  const [estado, setEstado] = useState<Autenticacao>(cache);

  useEffect(() => {
    ouvintes.add(setEstado);
    setEstado(cache);
    if (cache.situacao === "desconhecido") void consultar();
    return () => {
      ouvintes.delete(setEstado);
    };
  }, []);

  return estado;
}

/** Encerra a sessão e devolve a decisão ao servidor. */
export function useSair(): () => Promise<void> {
  return useCallback(async () => {
    try {
      await api.sair();
    } finally {
      // Mesmo que o logout falhe, reconsultar é o certo: quem manda no estado é o
      // cookie que o servidor enxerga, nunca o que esta aba acha que aconteceu.
      await reconsultarAutenticacao();
    }
  }, []);
}
