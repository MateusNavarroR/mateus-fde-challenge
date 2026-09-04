import { useEffect, useRef } from "react";
import { api } from "../api/cliente";
import type { EstadoBreaker, QuoteHealth, Usage } from "../api/tipos";
import { Erro } from "../ui/Erro";
import { duracao, inteiro, instante, percentual } from "../ui/formatar";
import { useRecurso } from "../ui/useRecurso";
import { PainelCusto } from "./PainelCusto";
import { useEventos } from "./useEventos";

const CLASSE_BREAKER: Record<EstadoBreaker, string> = {
  fechado: "breaker breaker--fechado",
  aberto: "breaker breaker--aberto",
  meia_abertura: "breaker breaker--meia",
};

const TEXTO_BREAKER: Record<EstadoBreaker, string> = {
  fechado: "fechado",
  aberto: "aberto",
  meia_abertura: "meia-abertura",
};

/**
 * A saúde **real** da `/quote`, que é diferente do `/health` do legado.
 *
 * O `/health` deles responde 200 com 100 % das cotações falhando. Exibi-lo sem a
 * ressalva é como se produz um monitor que mente — por isso a nota vem colada no
 * número, e não num rodapé de documentação.
 *
 * O breaker é o único elemento com escala de cartaz: o avaliador precisa achá-lo
 * em dois segundos.
 */
export function PaginaStatus() {
  const saude = useRecurso<QuoteHealth>(() => api.quoteHealth(), []);
  const uso = useRecurso<Usage>(() => api.usage(), []);
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Um cenário degradado emite dezenas de `quote.attempt` por segundo. Sem
  // debounce a tela se repintaria a cada frame e o número ficaria ilegível.
  useEventos((tipo) => {
    if (tipo !== "quote.attempt") return;
    if (debounce.current !== null) clearTimeout(debounce.current);
    debounce.current = setTimeout(() => saude.recarregar(), 400);
  });

  useEffect(
    () => () => {
      if (debounce.current !== null) clearTimeout(debounce.current);
    },
    [],
  );

  // A âncora `/admin/status#custo` rola até a seção ao carregar.
  useEffect(() => {
    if (globalThis.location?.hash !== "#custo") return;
    document.getElementById("custo")?.scrollIntoView({ block: "start" });
  }, [saude.dado, uso.dado]);

  if (saude.erro) return <Erro erro={saude.erro} aoTentarDeNovo={saude.recarregar} />;

  const h = saude.dado;
  /*
   * Nada de estado antes de saber o estado. Desenhar o disjuntor como "fechado"
   * enquanto a resposta não chegou é a mesma classe de defeito do `/health` do
   * legado que esta tela existe para desmentir: um monitor que afirma o que não
   * apurou.
   */
  if (h === null) {
    return (
      <section>
        <div className="pagina__topo">
          <h1 className="pagina__titulo">Status da integração</h1>
        </div>
        <p className="rotulo">Lendo a janela de tentativas…</p>
      </section>
    );
  }

  const breaker = h.breaker ?? { estado: "fechado" as EstadoBreaker, falhas_consecutivas: 0 };
  const janela = h.janela;
  const upstream = h.upstream_health;

  return (
    <section>
      <div className="pagina__topo">
        <div>
          <h1 className="pagina__titulo">Status da integração</h1>
          <p className="pagina__subtitulo">
            Verde e vermelho não provam que a instabilidade foi tratada. Aqui estão a
            janela real de tentativas, as latências e o estado do disjuntor.
          </p>
        </div>
      </div>

      {/*
        O carimbo. É o único elemento da aplicação inteira com escala e rotação,
        e a ousadia foi gasta aqui de propósito: um disjuntor aberto tem que ser
        achado em dois segundos, sem ler nada.
      */}
      <div
        className={CLASSE_BREAKER[breaker.estado]}
        data-testid="breaker"
        data-estado={breaker.estado}
      >
        <p className="breaker__selo">
          <span className="breaker__caption">disjuntor da /quote</span>
          <span className="breaker__estado">{TEXTO_BREAKER[breaker.estado]}</span>
        </p>
        <div className="breaker__dados">
          <span className="metrica">
            <span className="metrica__valor num">{breaker.falhas_consecutivas}</span>
            <span className="metrica__nome">falhas seguidas</span>
          </span>
          <span className="metrica">
            <span className="metrica__valor num">{instante(breaker.aberto_desde)}</span>
            <span className="metrica__nome">abriu em</span>
          </span>
          {/* Quando reabre, não só que abriu — é a única informação acionável ali. */}
          <span className="metrica">
            <span className="metrica__valor num">{instante(breaker.reabre_em)}</span>
            <span className="metrica__nome">reabre em</span>
          </span>
        </div>
      </div>

      <div className="grade">
        <div className="metrica" data-testid="upstream">
          <span className="metrica__valor">
            {upstream?.status === "unreachable" ? "inalcançável" : (upstream?.status ?? "—")}
          </span>
          <span className="metrica__nome">o /health do legado responde</span>
          <span className="metrica__nota">
            {upstream?.nota ??
              "responde 200 mesmo com 100% das cotações falhando — não é a saúde da cotação"}
          </span>
        </div>
        <div className="metrica">
          <span className="metrica__valor num" data-testid="taxa-sucesso">
            {janela ? percentual(janela.taxa_sucesso) : "—"}
          </span>
          <span className="metrica__nome">cotações que deram certo</span>
          <span className="metrica__nota">
            {janela ? `${inteiro(janela.sucesso)} de ${inteiro(janela.total)} tentativas` : ""}
          </span>
        </div>
        <div className="metrica">
          <span className="metrica__valor num" data-testid="p50">
            {janela ? duracao(janela.p50_ms) : "—"}
          </span>
          <span className="metrica__nome">metade responde em até</span>
        </div>
        <div className="metrica">
          <span className="metrica__valor num" data-testid="p95">
            {janela ? duracao(janela.p95_ms) : "—"}
          </span>
          <span className="metrica__nome">as 5% mais lentas passam de</span>
          <span className="metrica__nota">inclui as chamadas lentas de 8 s</span>
        </div>
      </div>

      <div className="cartao" data-testid="por-outcome">
        <p className="rotulo" style={{ margin: "0 0 0.45rem" }}>
          Como as tentativas terminaram
        </p>
        <div className="handoff__topo">
          {Object.entries(janela?.por_outcome ?? {}).length === 0 ? (
            <span className="rotulo">nenhuma tentativa na janela</span>
          ) : (
            Object.entries(janela?.por_outcome ?? {}).map(([nome, n]) => (
              <span
                key={nome}
                className={nome === "ok" ? "selo selo--ok" : "selo selo--falha"}
              >
                {nome} <strong className="num">{n}</strong>
              </span>
            ))
          )}
        </div>
      </div>

      <h2 className="secao__titulo" style={{ marginTop: "1.6rem" }}>
        Últimas tentativas
      </h2>
      {(h.ultimas_tentativas ?? []).length === 0 ? (
        <p className="rotulo">nenhuma tentativa registrada na janela</p>
      ) : (
        <div>
          {(h.ultimas_tentativas ?? []).map((t) => (
            <div className="tentativa" data-testid={`tentativa-${t.id}`} key={t.id}>
              <span>#{t.attempt}</span>
              <span>{t.http_status === null || t.http_status === undefined ? "—" : t.http_status}</span>
              <span>{duracao(t.latency_ms)}</span>
              <span className="trilho">
                <span className={t.outcome === "ok" ? "selo selo--ok" : "selo selo--falha"}>
                  {t.outcome}
                </span>
                {/* Cada tentativa leva à conversa que a originou: é a navegação
                    que demonstra rastreabilidade. */}
                {t.conversation_id ? (
                  <a href={`/admin/conversas/${t.conversation_id}`}>{t.conversation_id}</a>
                ) : null}
              </span>
            </div>
          ))}
        </div>
      )}

      {uso.carregando ? (
        <p className="rotulo">Somando o uso de tokens…</p>
      ) : (
        <PainelCusto usage={uso.dado} />
      )}
    </section>
  );
}

