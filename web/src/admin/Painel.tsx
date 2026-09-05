import { api } from "../api/cliente";
import type { Resumo } from "../api/tipos";
import { Erro } from "../ui/Erro";
import { useRecurso } from "../ui/useRecurso";

/**
 * O painel: o quadro geral em números, e é a primeira tela depois de entrar.
 *
 * **Nenhum número aqui é um total sozinho.** Um cartão que diz "12 cotações" não
 * informa nada sobre um produto cujo desfecho interessante é justamente a divisão:
 * recusa é decisão de negócio, falha é indisponibilidade, e somá-las esconderia
 * exatamente a distinção que o sistema inteiro existe para tratar. Cada cartão traz o
 * recorte embaixo do número, e é o recorte que carrega a informação.
 *
 * **Contado no banco, não aqui.** `/api/resumo` faz uma consulta por métrica; contar
 * do lado da tela exigiria paginar a lista inteira, e um painel que mente por
 * paginação é pior que painel nenhum — ele parece informação.
 *
 * A entrada é escalonada (`--i` no `style`), e é o único momento animado da tela: os
 * cartões chegam da esquerda em sequência, como folhas sendo postas sobre a mesa.
 * Depois disso o painel fica quieto, que é o que um painel deve fazer.
 */
export function Painel() {
  const { dado, erro, carregando, recarregar } = useRecurso<Resumo>(
    () => api.resumo(), [],
  );

  if (erro) return <Erro erro={erro} aoTentarDeNovo={recarregar} />;

  const r = dado;
  const vazio = r !== null && r.conversas === 0;

  const cartoes = [
    {
      chave: "conversas",
      valor: r?.conversas,
      titulo: "conversas atendidas",
      recorte: r ? `${r.conversas_encaminhadas} terminaram com uma pessoa` : "",
      destaque: false,
    },
    {
      chave: "mensagens",
      valor: r?.mensagens_enviadas,
      titulo: "mensagens enviadas",
      recorte: r ? `${r.mensagens_recebidas} recebidas do lead` : "",
      destaque: false,
    },
    {
      chave: "cotacoes",
      valor: r?.cotacoes_ok,
      titulo: "cotações entregues",
      recorte: r
        ? `${r.cotacoes_recusadas} recusadas pela regra · ${r.cotacoes_falhas} sem resposta da API`
        : "",
      destaque: false,
    },
    {
      chave: "handoffs",
      valor: r?.handoffs_pendentes,
      titulo: "handoffs na fila",
      recorte: r ? `${r.handoffs_total} no total, desde o começo` : "",
      // O único cartão que muda de cor, e só quando há fila: um painel que grita
      // sempre é um painel que ninguém olha.
      destaque: (r?.handoffs_pendentes ?? 0) > 0,
    },
  ];

  // Os dois números que provam mecanismo, e não volume. Ficam numa faixa própria
  // porque respondem a outra pergunta: os cartões dizem "o que aconteceu", esta
  // faixa diz "e funciona".
  const cache = r?.cache;
  const fracao = cache?.fracao_do_cache;
  const evals = r?.evals;

  return (
    <div className="folha">
      <header className="folha__cabeca">
        <h1 className="folha__titulo">Painel</h1>
        <p className="folha__linha">
          O que o agente conduziu até agora, contado no banco. Cada número traz o
          recorte embaixo — é ele que diz o que aconteceu.
        </p>
      </header>

      <div className="cartoes" data-testid="cartoes-do-painel">
        {cartoes.map((c, i) => (
          <article
            key={c.chave}
            className={`cartao${c.destaque ? " cartao--atencao" : ""}`}
            data-testid={`cartao-${c.chave}`}
            style={{ "--i": i } as React.CSSProperties}
          >
            <span className="cartao__valor">
              {carregando || c.valor === undefined ? "—" : c.valor.toLocaleString("pt-BR")}
            </span>
            <span className="cartao__titulo">{c.titulo}</span>
            <span className="cartao__recorte">{c.recorte}</span>
          </article>
        ))}
      </div>

      <div className="provas" data-testid="provas">
        <div className="prova" data-testid="prova-cache">
          <span className="prova__valor">
            {fracao === null || fracao === undefined
              ? "n/a"
              : `${(fracao * 100).toFixed(1).replace(".", ",")} %`}
          </span>
          <span className="prova__titulo">do contexto veio do cache</span>
          <span className="prova__recorte">
            {cache && cache.turnos_medidos > 0 ? (
              <>
                {cache.tokens_do_cache.toLocaleString("pt-BR")} lidos contra{" "}
                {cache.tokens_enviados.toLocaleString("pt-BR")} enviados ·{" "}
                <strong>{cache.turnos_sem_cache}</strong> de {cache.turnos_medidos}{" "}
                turnos leram zero
              </>
            ) : (
              "nenhum turno medido ainda — o provider precisa reportar cache"
            )}
          </span>
        </div>

        <div className="prova" data-testid="prova-evals">
          <span className="prova__valor">
            {evals && evals.total > 0 ? `${evals.passaram}/${evals.total}` : "—"}
          </span>
          <span className="prova__titulo">avaliações que passaram</span>
          <span className="prova__recorte">
            {evals && evals.total > 0
              ? "ReliabilityEval e AgentAsJudgeEval, gravados em ai.eval_runs pelo Agno"
              : "nenhuma avaliação registrada ainda"}
          </span>
        </div>
      </div>

      {vazio ? (
        <p className="folha__nota" data-testid="painel-vazio">
          Ainda não há nada contado porque ninguém conversou com o agente. Abra o{" "}
          <a href="/simulador">Simulador</a>, mande uma mensagem, e os números aparecem
          aqui — junto com a conversa no Histórico.
        </p>
      ) : (
        <p className="folha__nota">
          O <a href="/historico">Histórico</a> tem cada mensagem com id e status; o{" "}
          <a href="/status">Status</a> tem a saúde da integração e o custo por conversa.
        </p>
      )}
    </div>
  );
}
