import type { ReactNode } from "react";
import { api } from "../api/cliente";
import type { FilaHandoffs } from "../api/tipos";
import { useRecurso } from "../ui/useRecurso";
import { useEventos } from "./useEventos";

const ABAS = [
  { href: "/admin/conversas", nome: "Conversas" },
  { href: "/admin/status", nome: "Status" },
  { href: "/admin/handoffs", nome: "Handoffs" },
] as const;

/**
 * O layout carrega o badge de pendentes e mantém o socket de eventos. O badge é
 * visível de **qualquer** tela — é o que faz a fila ser operada em vez de
 * consultada.
 *
 * Duas ausências deliberadas:
 *
 * 1. **Não existe link `admin → chat`** (`DECISOES-FECHADAS.md` §8). Por ele o
 *    avaliador assumiria o lugar do lead numa conversa que já tem handoff, e
 *    isso não tem resposta boa. O inverso existe e é a demonstração inteira da
 *    rastreabilidade. Há um teste negativo para isto, porque é o tipo de link
 *    que alguém adiciona "por simetria" seis meses depois.
 * 2. **Zero não vira badge.** Um "0" ali é ruído, não informação.
 */
export function LayoutAdmin({ rota, children }: { rota: string; children?: ReactNode }) {
  const fila = useRecurso<FilaHandoffs>(() => api.handoffs({ limit: 1 }), []);

  // Um admin que perdeu o push e não avisa é pior que um admin sem push: o
  // operador passa a confiar numa fila parada.
  const conexao = useEventos((tipo) => {
    if (tipo === "handoff.created" || tipo === "handoff.updated") fila.recarregar();
  });

  const pendentes = fila.dado?.pendentes ?? 0;

  return (
    <div className="admin">
      <header className="admin__barra">
        <p className="admin__marca">AutoSeguro</p>
        <nav className="admin__nav" aria-label="Telas de operação">
          {ABAS.map((aba) => (
            <a
              key={aba.href}
              href={aba.href}
              aria-current={rota.startsWith(aba.href) ? "page" : undefined}
            >
              {aba.nome}
            </a>
          ))}
        </nav>
        {pendentes > 0 ? (
          <span className="badge-pendentes" data-testid="badge-pendentes">
            {pendentes}
            <span className="so-leitor"> handoffs pendentes</span>
          </span>
        ) : null}
        <span
          className={
            conexao === "conectado" ? "admin__conexao pilula" : "admin__conexao pilula pilula--atencao"
          }
          data-testid="conexao-eventos"
        >
          {conexao === "conectado" ? "recebendo em tempo real" : "sem conexão em tempo real"}
        </span>
      </header>
      <div className="admin__conteudo">{children}</div>
    </div>
  );
}
