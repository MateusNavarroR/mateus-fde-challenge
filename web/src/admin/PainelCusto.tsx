import type { Usage, UsageAgregado } from "../api/tipos";
import { Vazio } from "../ui/Vazio";
import { dolar, duracao, formatarOuNa, inteiro, percentual } from "../ui/formatar";

/**
 * O painel de custo é uma **seção** de `/admin/status`, com título próprio e
 * âncora — não um rodapé, não uma quinta tela (`DECISOES-FECHADAS.md` §8). São
 * seis números, e o leitor já vai a `/admin/status` porque é lá que o circuit
 * breaker aparece.
 *
 * Duas regras de exibição, e as duas são invariantes:
 *
 * 1. **A tela não abre arquivo de preço e não multiplica token por valor.** O
 *    custo chega calculado do backend, com a vigência da tabela usada. Duas
 *    origens de preço é como um custo histórico deixa de ser auditável no dia em
 *    que a tabela muda.
 * 2. **Nulo é "n/a", nunca "0 %".** O Ollama não reporta cache; um zero ali
 *    diria "o cache não acertou" onde a verdade é "não existe cache neste
 *    caminho". Todo número anulável passa por `formatarOuNa` — o `??` proibido
 *    escrito em código.
 */
export function PainelCusto({ usage }: { usage: Usage | null }) {
  const total: UsageAgregado | null = usage?.total ?? null;
  const vazio =
    total === null ||
    (total.tokens_in === 0 &&
      total.tokens_out === 0 &&
      (usage?.por_conversa.length ?? 0) === 0);

  return (
    <section className="secao" id="custo" aria-labelledby="titulo-custo">
      <h2 className="secao__titulo" id="titulo-custo">
        Custo e uso de tokens
      </h2>
      <p className="pagina__subtitulo">
        Lido da nossa própria base, a cada turno. Prova o prompt caching com número e diz
        quanto custou cada conversa.
      </p>

      {vazio ? (
        <div style={{ marginTop: "1rem" }}>
          <Vazio titulo="Nenhum turno gravado ainda">
            Assim que o agente responder a primeira mensagem, os tokens, o custo e a taxa
            de acerto de cache aparecem aqui — com a vigência da tabela de preço usada.
          </Vazio>
        </div>
      ) : (
        <>
          <div className="grade" style={{ marginTop: "1rem" }}>
            <div className="metrica">
              <span className="metrica__valor num">{inteiro(total.tokens_in)}</span>
              <span className="metrica__nome">tokens enviados ao modelo</span>
            </div>
            <div className="metrica">
              <span className="metrica__valor num">{inteiro(total.tokens_out)}</span>
              <span className="metrica__nome">tokens gerados pelo modelo</span>
            </div>
            <div className="metrica">
              <span
                className={
                  total.taxa_acerto_cache === null || total.taxa_acerto_cache === undefined
                    ? "metrica__valor num metrica__valor--na"
                    : "metrica__valor num"
                }
                data-testid="taxa-cache"
              >
                {formatarOuNa(total.taxa_acerto_cache, percentual)}
              </span>
              <span className="metrica__nome">do contexto veio do cache</span>
              <span className="metrica__nota">
                {total.cache_read === null || total.cache_read === undefined
                  ? "este provider não reporta cache"
                  : `${inteiro(total.cache_read)} lidos do cache`}
              </span>
            </div>
            <div className="metrica">
              <span
                className={
                  total.custo_usd === null || total.custo_usd === undefined
                    ? "metrica__valor num metrica__valor--na"
                    : "metrica__valor num"
                }
                data-testid="custo-total"
              >
                {formatarOuNa(total.custo_usd, dolar)}
              </span>
              <span className="metrica__nome">gasto acumulado nas conversas</span>
              <span className="metrica__nota">
                {/* Sem procedência, um custo é um número solto. */}
                tabela vigente em{" "}
                <span data-testid="vigencia">
                  {formatarOuNa(total.pricing_vigencia, (v) => v)}
                </span>
              </span>
            </div>
            <div className="metrica">
              <span className="metrica__valor num">
                {formatarOuNa(total.latency_p50_ms, duracao)}
              </span>
              <span className="metrica__nome">metade dos turnos responde em até</span>
            </div>
          </div>

          <h3 className="secao__titulo" style={{ marginTop: "1.4rem", fontSize: "1.05rem" }}>
            Por provider
          </h3>
          <table className="tabela" role="table">
            <thead>
              <tr>
                <th scope="col">Provider</th>
                <th scope="col">Entrada</th>
                <th scope="col">Saída</th>
                <th scope="col">Acerto de cache</th>
                <th scope="col">Custo</th>
                <th scope="col">p50</th>
              </tr>
            </thead>
            <tbody>
              {(usage?.por_provider ?? []).map((p) => (
                <tr key={p.provider}>
                  <td data-rotulo="Provider">{p.provider}</td>
                  <td data-rotulo="Entrada" className="num">
                    {inteiro(p.tokens_in)}
                  </td>
                  <td data-rotulo="Saída" className="num">
                    {inteiro(p.tokens_out)}
                  </td>
                  <td data-rotulo="Acerto de cache" className="num">
                    {formatarOuNa(p.taxa_acerto_cache, percentual)}
                  </td>
                  <td data-rotulo="Custo" className="num">
                    {formatarOuNa(p.custo_usd, dolar)}
                  </td>
                  <td data-rotulo="p50" className="num">
                    {formatarOuNa(p.latency_p50_ms, duracao)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {(usage?.por_conversa ?? []).length > 0 ? (
            <>
              <h3 className="secao__titulo" style={{ marginTop: "1.4rem", fontSize: "1.05rem" }}>
                Por conversa
              </h3>
              <table className="tabela" role="table">
                <thead>
                  <tr>
                    <th scope="col">Conversa</th>
                    <th scope="col">Turnos</th>
                    <th scope="col">Entrada</th>
                    <th scope="col">Saída</th>
                    <th scope="col">Acerto de cache</th>
                    <th scope="col">Custo</th>
                  </tr>
                </thead>
                <tbody>
                  {(usage?.por_conversa ?? []).map((c) => (
                    <tr key={c.conversation_id}>
                      <td data-rotulo="Conversa">
                        <a href={`/admin/conversas/${c.conversation_id}`}>
                          {c.conversation_id}
                        </a>
                      </td>
                      <td data-rotulo="Turnos" className="num">
                        {c.turnos ?? "—"}
                      </td>
                      <td data-rotulo="Entrada" className="num">
                        {inteiro(c.tokens_in)}
                      </td>
                      <td data-rotulo="Saída" className="num">
                        {inteiro(c.tokens_out)}
                      </td>
                      <td data-rotulo="Acerto de cache" className="num">
                        {formatarOuNa(c.taxa_acerto_cache, percentual)}
                      </td>
                      <td data-rotulo="Custo" className="num">
                        {formatarOuNa(c.custo_usd, dolar)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          ) : null}
        </>
      )}
    </section>
  );
}
