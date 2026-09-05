import { useState } from "react";
import { ErroApi, api } from "../api/cliente";
import type { FilaHandoffs, StatusHandoff } from "../api/tipos";
import { Erro } from "../ui/Erro";
import { Vazio } from "../ui/Vazio";
import { instante } from "../ui/formatar";
import { useRecurso } from "../ui/useRecurso";
import { useEventos } from "./useEventos";

/**
 * Os **sete** gatilhos da tabela fechada (`DECISOES-FECHADAS.md` §3).
 *
 * `cotacao_recusada` não está aqui, e a ausência é a decisão: **recusa não vira
 * handoff**. Ela é desfecho de negócio, registrado na conversa, sem prometer
 * contato que ninguém fará.
 */
const GATILHO: Record<string, string> = {
  assunto_sensivel: "assunto sensível",
  guardrail: "guardrail",
  lead_pediu: "o lead pediu uma pessoa",
  cotacao_indisponivel: "cotação indisponível",
  extracao_falhou: "extração falhou duas vezes",
  objecao_fora_da_alcada: "objeção fora da alçada",
  midia_sem_texto: "mídia sem texto",
};

/**
 * Um gatilho determinístico e uma decisão do modelo produzem o mesmo sinal — e a
 * fila distingue os dois, porque o operador precisa saber se está olhando uma
 * regra que disparou ou um julgamento que pode ter errado.
 */
const ORIGEM: Record<string, string> = {
  regra: "regra determinística",
  modelo: "decisão do modelo",
};

const PROXIMOS: Record<StatusHandoff, StatusHandoff[]> = {
  pendente: ["assumido", "resolvido"],
  assumido: ["resolvido"],
  // Terminal. Resolvido não volta para pendente — a tela nem oferece.
  resolvido: [],
};

const ACAO: Record<StatusHandoff, string> = {
  pendente: "Devolver",
  assumido: "Assumir",
  resolvido: "Resolver",
};

export function PaginaHandoffs() {
  const [falhaNaTransicao, setFalhaNaTransicao] = useState<string | null>(null);
  const fila = useRecurso<FilaHandoffs>(() => api.handoffs(), []);

  /*
   * O push **invalida e recarrega**; nunca sintetiza o item a partir do frame.
   * Um item montado no cliente diverge do que o banco tem na primeira mudança de
   * schema, e o admin existe para dizer a verdade sobre o banco.
   */
  useEventos((tipo) => {
    if (tipo === "handoff.created" || tipo === "handoff.updated") fila.recarregar();
  });

  const transicionar = (id: string, status: StatusHandoff) => {
    setFalhaNaTransicao(null);
    void api
      .transicionarHandoff(id, status)
      .then(() => fila.recarregar())
      .catch((e: unknown) => {
        // O backend é a autoridade sobre o estado: em 409 a mensagem dele
        // aparece e o item volta ao que o banco diz.
        setFalhaNaTransicao(
          e instanceof ErroApi ? e.message : "Não consegui aplicar essa transição.",
        );
        fila.recarregar();
      });
  };

  if (fila.erro) return <Erro erro={fila.erro} aoTentarDeNovo={fila.recarregar} />;

  const itens = fila.dado?.items ?? [];

  return (
    <section>
      <div className="pagina__topo">
        <div>
          <h1 className="pagina__titulo">Fila de handoff</h1>
          <p className="pagina__subtitulo">
            Cada item mostra qual regra disparou — não uma frase gerada. A fila entra em
            tempo real, sem recarregar a página.
          </p>
        </div>
      </div>

      {falhaNaTransicao !== null ? (
        <div className="erro" role="alert">
          <p className="erro__titulo">A transição não foi aplicada</p>
          <p className="erro__texto">{falhaNaTransicao}</p>
        </div>
      ) : null}

      {itens.length === 0 && !fila.carregando ? (
        <Vazio titulo="Nenhum handoff na fila">
          Nada pendente. Um caso novo aparece aqui sozinho, sem recarregar — os gatilhos
          são os sete da tabela de decisões, e recusa de cotação não é um deles.
        </Vazio>
      ) : null}

      {itens.map((h) => (
        <article className={`handoff handoff--${h.status}`} data-testid={`handoff-${h.id}`} key={h.id}>
          <div className="handoff__topo">
            <span
              className={
                h.status === "pendente"
                  ? "selo selo--falha"
                  : h.status === "assumido"
                    ? "selo selo--espera"
                    : "selo selo--ok"
              }
            >
              {h.status}
            </span>
            <strong>{GATILHO[h.trigger] ?? h.trigger}</strong>
            <span className="selo selo--neutro" data-testid="disparado-por">
              {ORIGEM[h.disparado_por] ?? h.disparado_por}
            </span>
            <a href={`/historico/${h.conversation_id}`}>{h.conversation_id}</a>
            <span className="rotulo">{instante(h.criado_em)}</span>
          </div>

          {h.reason ? <p className="vazio__texto">{h.reason}</p> : null}
          {h.summary ? <p className="vazio__texto">{h.summary}</p> : null}

          <div className="handoff__acoes">
            {PROXIMOS[h.status].map((proximo) => (
              <button
                key={proximo}
                type="button"
                className={proximo === "resolvido" ? "botao botao--discreto" : "botao"}
                onClick={() => {
                  void transicionar(h.id, proximo);
                  // ASSUMIR ABRE A CONVERSA, e antes só mudava um rótulo.
                  //
                  // "Assumir" que apenas troca um status é um botão que promete
                  // trabalho e não entrega ferramenta: o operador ficava com o caso
                  // no nome e nenhum lugar para responder. A transição continua
                  // acontecendo — é ela que tira o caso da fila dos outros — e a
                  // navegação é a consequência natural dela.
                  if (proximo === "assumido") {
                    location.assign(`/handoffs/${h.conversation_id}`);
                  }
                }}
              >
                {ACAO[proximo]}
              </button>
            ))}
            {h.status === "assumido" ? (
              // Quem já assumiu volta ao atendimento sem ter de reabrir a fila.
              <a className="botao" href={`/handoffs/${h.conversation_id}`}>
                Abrir o atendimento
              </a>
            ) : null}
          </div>
        </article>
      ))}
    </section>
  );
}
