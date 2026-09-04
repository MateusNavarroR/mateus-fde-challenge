import type { Outcome, Quote } from "../api/tipos";
import { duracao } from "../ui/formatar";

const CLASSE_OUTCOME: Record<Outcome, string> = {
  ok: "selo selo--ok",
  transient: "selo selo--falha",
  timeout: "selo selo--falha",
  refused: "selo selo--recusa",
  bad_request: "selo selo--espera",
};

/**
 * Enum **fechado** (`openapi.yaml`). Um `default` genérico esconderia um motivo
 * novo, e é justamente um motivo novo que precisaria ser visto.
 */
const MOTIVO_RECUSA: Record<string, string> = {
  idade_acima_do_limite: "Idade acima do limite de aceitação",
  idade_abaixo_do_minimo: "Idade abaixo do mínimo",
  veiculo_acima_de_20_anos: "Veículo acima de 20 anos",
};

/**
 * A linha do tempo é a parte que prova que a instabilidade foi **tratada**, e
 * não apenas sobrevivida: três tentativas com `outcome` diferente contam a
 * política inteira sem uma linha de README.
 */
export function LinhaDoTempoCotacao({ quote }: { quote: Quote }) {
  const maior = Math.max(1, ...quote.attempts.map((a) => a.latency_ms));

  return (
    <article className="cartao" data-testid={`quote-${quote.id}`} style={{ marginBottom: "0.7rem" }}>
      <header className="handoff__topo">
        <span className="rotulo">cotação {quote.id}</span>
        <span
          className={
            quote.status === "ok"
              ? "selo selo--ok"
              : quote.status === "refused"
                ? "selo selo--recusa"
                : quote.status === "failed"
                  ? "selo selo--falha"
                  : "selo selo--espera"
          }
        >
          {quote.status}
        </span>
        {quote.total_latency_ms !== null && quote.total_latency_ms !== undefined ? (
          <span className="rotulo">total {duracao(quote.total_latency_ms)}</span>
        ) : null}
      </header>

      {quote.status === "refused" && quote.motivo_recusa ? (
        <p className="erro__texto" style={{ marginTop: "0.6rem" }}>
          Recusa de negócio: <strong>{MOTIVO_RECUSA[quote.motivo_recusa] ?? quote.motivo_recusa}</strong>.
          Recusa não gera handoff — é desfecho, não indisponibilidade.
        </p>
      ) : null}

      {/*
        O breaker impediu a chamada: o job é `failed` SEM nenhuma tentativa. Sem
        esta distinção a tela sugere que a API foi chamada e não foi — e com o
        breaker aberto não sabemos nada sobre este lead.
      */}
      {quote.circuito_aberto ? (
        <p
          className="selo selo--falha"
          data-testid="selo-circuito-aberto"
          style={{ marginTop: "0.6rem" }}
        >
          circuito aberto — não chamamos a /quote
        </p>
      ) : quote.attempts.length === 0 ? (
        <p className="rotulo" style={{ marginTop: "0.6rem" }}>
          sem tentativas registradas
        </p>
      ) : (
        <div style={{ marginTop: "0.6rem" }}>
          {quote.attempts.map((a) => (
            <div className="tentativa" data-testid={`tentativa-${a.id}`} key={a.id}>
              <span>#{a.attempt}</span>
              {/* http_status nulo é "—", nunca "0": não houve resposta. */}
              <span>{a.http_status === null || a.http_status === undefined ? "—" : a.http_status}</span>
              <span>{duracao(a.latency_ms)}</span>
              <span className="trilho">
                <span
                  className={
                    a.outcome === "ok" ? "trilho__barra trilho__barra--ok" : "trilho__barra"
                  }
                  style={{ width: `${Math.max(4, (a.latency_ms / maior) * 100)}%` }}
                />
                <span className={CLASSE_OUTCOME[a.outcome]}>{a.outcome}</span>
              </span>
            </div>
          ))}
        </div>
      )}
    </article>
  );
}
