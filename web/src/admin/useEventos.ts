/**
 * **Um** socket `/api/events` para a sessão inteira, não um por tela.
 *
 * Um socket por tela faria o badge de pendentes piscar a cada navegação e o push
 * sumir justamente enquanto o avaliador troca de aba. Por isso a conexão vive
 * fora do ciclo de vida de qualquer componente: um singleton de módulo com
 * contagem de assinantes.
 *
 * O que chega é usado só pelo `type`. O corpo do frame é ignorado de propósito:
 * a tela **invalida e recarrega** do endpoint em vez de sintetizar o item, porque
 * um item montado no cliente diverge do banco na primeira mudança de schema — e
 * o admin existe para dizer a verdade sobre o banco.
 */

import { useEffect, useRef, useState } from "react";
import { conectarEventos, type Sessao, type StatusConexao } from "../api/ws";
import type { TipoEventoAdmin } from "../api/tipos";

type Ouvinte = (tipo: TipoEventoAdmin) => void;

let sessao: Sessao | null = null;
let ouvintes = new Set<Ouvinte>();
let ouvintesDeStatus = new Set<(s: StatusConexao) => void>();
let statusAtual: StatusConexao = "conectando";

function garantirSessao(): void {
  if (sessao !== null) return;
  sessao = conectarEventos({
    aoEvento: (evento) => {
      const tipo = evento.type;
      for (const o of ouvintes) o(tipo);
    },
    aoStatus: (s) => {
      statusAtual = s;
      for (const o of ouvintesDeStatus) o(s);
    },
  });
}

function liberar(): void {
  if (ouvintes.size > 0 || ouvintesDeStatus.size > 0) return;
  sessao?.fechar();
  sessao = null;
  statusAtual = "conectando";
}

/** Só para o teste: derruba o singleton entre casos. */
export function _reiniciarEventos(): void {
  sessao?.fechar();
  sessao = null;
  ouvintes = new Set();
  ouvintesDeStatus = new Set();
  statusAtual = "conectando";
}

/**
 * Assina o push. `aoEvento` recebe só o tipo — é tudo que a UI usa, e é tudo que
 * o Núcleo precisa garantir no envelope.
 */
export function useEventos(aoEvento?: (tipo: TipoEventoAdmin) => void): StatusConexao {
  const [status, setStatus] = useState<StatusConexao>(statusAtual);
  const ref = useRef(aoEvento);
  ref.current = aoEvento;

  useEffect(() => {
    const ouvinte: Ouvinte = (tipo) => ref.current?.(tipo);
    const deStatus = (s: StatusConexao) => setStatus(s);
    ouvintes.add(ouvinte);
    ouvintesDeStatus.add(deStatus);
    garantirSessao();
    setStatus(statusAtual);
    return () => {
      ouvintes.delete(ouvinte);
      ouvintesDeStatus.delete(deStatus);
      liberar();
    };
  }, []);

  return status;
}
