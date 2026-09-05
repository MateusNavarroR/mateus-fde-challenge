import { useCallback, useId, useState } from "react";
import { api } from "../api/cliente";
import { ESTADOS_CONVERSA } from "../api/tipos";
import type { ConversationSummary, PaginaConversas as Pagina, StatusJob } from "../api/tipos";
import { Erro } from "../ui/Erro";
import { Vazio } from "../ui/Vazio";
import { instante } from "../ui/formatar";
import { useRecurso } from "../ui/useRecurso";

/**
 * `refused` e `failed` precisam ser distinguíveis à primeira vista.
 *
 * Recusa é desfecho de **negócio** e não gera handoff; `failed` é
 * indisponibilidade e gera. Empilhar os dois no mesmo cinza apagaria a decisão
 * mais importante do produto — por isso cores diferentes, não dois tons.
 */
const SELO_COTACAO: Record<StatusJob, { texto: string; classe: string }> = {
  pending: { texto: "cotando", classe: "selo selo--espera" },
  ok: { texto: "cotada", classe: "selo selo--ok" },
  refused: { texto: "recusada", classe: "selo selo--recusa" },
  failed: { texto: "falhou", classe: "selo selo--falha" },
};

export function PaginaConversas() {
  const idFiltro = useId();
  const [estado, setEstado] = useState<string>("");
  const [cursor, setCursor] = useState<string | undefined>(undefined);
  const [acumulado, setAcumulado] = useState<ConversationSummary[]>([]);

  const carregar = useCallback(async (): Promise<Pagina> => {
    const p = await api.conversas({
      ...(estado ? { state: estado } : {}),
      ...(cursor ? { cursor } : {}),
    });
    setAcumulado((antes) => (cursor ? [...antes, ...p.items] : p.items));
    return p;
  }, [estado, cursor]);

  const { dado, erro, carregando, recarregar } = useRecurso<Pagina>(carregar, [estado, cursor]);

  if (erro) return <Erro erro={erro} aoTentarDeNovo={recarregar} />;

  const linhas = acumulado;

  return (
    <section>
      <div className="pagina__topo">
        <div>
          <h1 className="pagina__titulo">Histórico de mensagens</h1>
          <p className="pagina__subtitulo">
            Tudo que o agente conduziu, com o desfecho da última cotação. A linha leva ao
            detalhe, com cada mensagem por id, índice, autor e status.
          </p>
          <p className="pagina__subtitulo">
            {/* Dizer que é só leitura evita a pergunta antes dela nascer: não há
                aqui nenhum botão que responda pelo agente, e isso é decisão — quem
                assume uma conversa faz isso na fila de handoff. */}
            <strong>Só leitura.</strong> É por aqui que uma conversa vinda do
            WhatsApp seria lida pela operação. Para agir sobre um caso, a fila está em{" "}
            <a href="/handoffs">Handoffs</a>.
          </p>
        </div>
      </div>

      <div className="filtros">
        <span className="campo">
          <label className="rotulo" htmlFor={idFiltro}>
            Estado
          </label>
          {/* Os valores saem do enum do contrato — nunca digitados à mão aqui. */}
          <select
            id={idFiltro}
            value={estado}
            onChange={(e) => {
              setCursor(undefined);
              setAcumulado([]);
              setEstado(e.target.value);
            }}
          >
            <option value="">todos</option>
            {ESTADOS_CONVERSA.map((e) => (
              <option key={e} value={e}>
                {e}
              </option>
            ))}
          </select>
        </span>
      </div>

      {/*
        Dois vazios diferentes, e confundi-los foi um achado da vistoria: com 14
        conversas no banco e o filtro em `fechado`, a tela dizia "o banco está no ar e
        VAZIO" e mandava abrir o `/chat` para criar uma. O próximo passo certo era
        limpar o filtro, e a tela apontava para o lado oposto.

        "Nenhum resultado" e "nenhum dado" pedem ações contrárias. Quem está filtrando
        sabe que filtrou; o que ele não sabe é que o filtro é a causa.
      */}
      {linhas.length === 0 && !carregando ? (
        estado ? (
          <Vazio titulo={`Nenhuma conversa em «${estado}»`}>
            O filtro está ativo e nada casou com ele. Volte para{" "}
            <strong>todos</strong> para ver a lista inteira — pode haver conversas em
            outros estados.
          </Vazio>
        ) : (
          <Vazio titulo="Nenhuma conversa ainda">
            O banco está no ar e vazio. Abra <code>/chat</code>, mande uma mensagem, e
            ela aparece aqui com id, estado e o desfecho da cotação.
          </Vazio>
        )
      ) : (
        <table className="tabela" role="table">
          <thead>
            <tr>
              <th scope="col">Conversa</th>
              <th scope="col">Estado</th>
              <th scope="col">Msgs</th>
              <th scope="col">Última cotação</th>
              <th scope="col">Última mensagem</th>
              <th scope="col">Atualizada</th>
            </tr>
          </thead>
          <tbody>
            {linhas.map((c) => {
              const selo = c.ultima_cotacao_status ? SELO_COTACAO[c.ultima_cotacao_status] : null;
              return (
                <tr key={c.id}>
                  <td data-rotulo="Conversa">
                    <a href={`/admin/conversas/${c.id}`}>{c.id}</a>
                    {c.handoff_pendente ? (
                      <span
                        className="selo selo--falha"
                        data-testid="marca-handoff-pendente"
                        title="handoff pendente"
                      >
                        handoff
                      </span>
                    ) : null}
                  </td>
                  <td data-rotulo="Estado">
                    <span className="selo selo--neutro">{c.state}</span>
                  </td>
                  <td data-rotulo="Msgs" className="num">
                    {c.total_mensagens}
                  </td>
                  <td data-rotulo="Última cotação">
                    {selo ? (
                      <span className={selo.classe} data-testid="selo-cotacao">
                        {selo.texto}
                      </span>
                    ) : (
                      <span className="rotulo">sem cotação</span>
                    )}
                  </td>
                  <td data-rotulo="Última mensagem">{c.ultima_mensagem ?? "—"}</td>
                  <td data-rotulo="Atualizada" className="num">
                    {instante(c.atualizado_em)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {dado?.next_cursor ? (
        <button
          type="button"
          className="botao botao--discreto"
          onClick={() => setCursor(dado.next_cursor ?? undefined)}
        >
          Carregar mais
        </button>
      ) : null}
    </section>
  );
}
