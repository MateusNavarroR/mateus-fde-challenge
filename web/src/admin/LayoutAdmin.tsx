import type { ReactNode } from "react";
import { api } from "../api/cliente";
import type { FilaHandoffs } from "../api/tipos";
import { useRecurso } from "../ui/useRecurso";
import { Casca } from "../ui/Casca";
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
 * Sobre a assimetria com o chat (`DECISOES-FECHADAS.md` §8), há uma distinção que
 * custou um bug de usabilidade para ficar clara:
 *
 * 1. **Não existe deep link de uma CONVERSA para o chat.** Por ele o avaliador
 *    assumiria o lugar do lead numa conversa que já tem handoff, e isso não tem
 *    resposta boa. Há um teste negativo, porque é o tipo de link que alguém
 *    adiciona "por simetria" seis meses depois.
 * 2. **Existe navegação para o chat**, aqui na barra. Sem ela o admin é um beco
 *    sem saída — quem entra não volta. E ela não recria o problema do item 1: o
 *    `/chat` retoma a sessão do próprio navegador, então leva o avaliador de volta
 *    à conversa **dele**, nunca à de outro lead.
 * 3. **Zero não vira badge.** Um "0" ali é ruído, não informação.
 */
export function LayoutAdmin({ rota, children }: { rota: string; children?: ReactNode }) {
  const fila = useRecurso<FilaHandoffs>(() => api.handoffs({ limit: 1 }), []);

  // Um admin que perdeu o push e não avisa é pior que um admin sem push: o
  // operador passa a confiar numa fila parada.
  const conexao = useEventos((tipo) => {
    if (tipo === "handoff.created" || tipo === "handoff.updated") fila.recarregar();
  });

  const pendentes = fila.dado?.pendentes ?? 0;

  const separadores = (
    <nav className="separadores" aria-label="Seções da operação">
      {ABAS.map((aba) => {
        const atual = rota.startsWith(aba.href);
        return (
          <a
            key={aba.href}
            className="separador"
            href={aba.href}
            aria-current={atual ? "page" : undefined}
            data-atual={atual ? "sim" : "nao"}
          >
            {aba.nome}
            {aba.href === "/admin/handoffs" && pendentes > 0 ? (
              <span className="separador__contagem">{pendentes}</span>
            ) : null}
          </a>
        );
      })}
    </nav>
  );

  const estado = (
    <>
      {pendentes > 0 ? (
        <span className="badge-pendentes" data-testid="badge-pendentes">
          {pendentes}
          <span className="so-leitor"> handoffs pendentes</span>
        </span>
      ) : null}
      <span
        className={
          conexao === "conectado"
            ? "admin__conexao pilula"
            : "admin__conexao pilula pilula--atencao"
        }
        data-testid="conexao-eventos"
      >
        {conexao === "conectado" ? "recebendo em tempo real" : "sem conexão em tempo real"}
      </span>
    </>
  );

  return (
    <Casca via="admin" separadores={separadores} estado={estado}>
      <div className="admin__conteudo">{children}</div>
    </Casca>
  );
}
