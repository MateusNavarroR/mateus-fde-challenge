import { useState } from "react";
import { api } from "../api/cliente";
import type { ConversationDetail, ListaDeTraces, Message } from "../api/tipos";
import { Erro } from "../ui/Erro";
import { Vazio } from "../ui/Vazio";
import { cepMascarado, hora } from "../ui/formatar";
import { useRecurso } from "../ui/useRecurso";
import { LinhaDoTempoCotacao } from "./LinhaDoTempoCotacao";
import { Bolha } from "../chat/Bolha";

const DINHEIRO = /(R\$\s*[\d.,]+)|([\d.,]+\s*reais\b)/i;

function suspeita(m: Message): boolean {
  if (m.autor === "lead") return false;
  const temQuote = m.quote_id !== null && m.quote_id !== undefined && m.quote_id !== "";
  return DINHEIRO.test(m.conteudo) && !temQuote;
}

/**
 * As três formas de ler a MESMA lista de mensagens, e cada uma responde a uma
 * pergunta diferente:
 *
 * - **transcrição** — "o que aconteceu com esse lead", com id e status por bolha;
 * - **como o lead viu** — a moldura da conversa, em leitura. É a forma que faltava:
 *   pelo handoff, o operador precisa ver a conversa como ela chegou ao lead antes de
 *   assumi-la, e uma tabela com metadados não mostra isso. Aqui não há compositor, e
 *   isso é a decisão, não uma pendência: a navegação `admin → chat` foi recusada
 *   porque por ela o operador assumiria o lugar do LEAD numa conversa que já tem
 *   handoff. **Ver não é escrever** — esta forma dá a vista e não dá a caneta;
 * - **razão** — a lista crua com `index`, para quando a pergunta é sobre a ordem;
 * - **trace** — o que cada resposta EXECUTOU: as tools, com argumentos, duração e
 *   erro, mais os tokens do turno. É a única forma que responde "por que ele
 *   respondeu isso", e vem de `ai.agno_runs` — granularidade de chamada, que a
 *   tabela de custo (granularidade de turno) não tem.
 */
type Forma = "transcricao" | "lead" | "razao" | "trace";

const ROTULO_CAMPO: Record<string, string> = {
  idade: "idade",
  veiculo_ano: "ano do veículo",
  cep: "CEP",
  data_inicio: "data de início",
  plano_id: "plano",
};

/**
 * A resposta ao critério C4 numa tela só: cada mensagem com id e status, cada
 * cotação com todas as suas tentativas.
 *
 * Aqui `sistema` **é** distinguível de `agente` — no admin isso é informação.
 * Na `/chat` os dois são idênticos, de propósito. A assimetria é deliberada e as
 * duas pontas têm teste, senão alguém "uniformiza" e a auditoria se perde.
 */
export function DetalheConversa({ id }: { id: string }) {
  const [forma, setForma] = useState<Forma>("transcricao");
  const { dado, erro, recarregar } = useRecurso<ConversationDetail>(
    () => api.conversa(id),
    [id],
  );

  if (erro) return <Erro erro={erro} aoTentarDeNovo={recarregar} />;
  if (!dado) return <p className="rotulo">carregando…</p>;

  // Ordem por `index`, nunca por timestamp: 99,8 % do dataset está fora de ordem.
  const mensagens = [...(dado.messages ?? [])].sort((a, b) => a.index - b.index);
  const perfil = dado.perfil ?? {};
  const faltantes = perfil.campos_faltantes ?? [];

  return (
    <section>
      <div className="pagina__topo">
        <div>
          <h1 className="pagina__titulo">Conversa {dado.id}</h1>
          <p className="pagina__subtitulo">
            Está em <strong>{dado.state}</strong>, aberta pelo canal {dado.channel}.
          </p>
        </div>

        {/*
          CONTINUAR A CONVERSA, e o destino depende de QUEM você é nela.

          Esta é a ponte que faltava: do Histórico dava para ler uma conversa e não
          dava para retomá-la. A decisão fechada §8 recusava `admin → chat` porque
          "o operador assumiria o lugar do LEAD numa conversa que já tem handoff" — e
          essa razão continua de pé, mas ela nomeia um caso, não a ponte inteira.

          Conversa ENCAMINHADA vai para a tela do atendente, onde ele escreve pelo
          lado da empresa. Qualquer outra abre no simulador, como CLIENTE, que é o
          uso legítimo: seguir a conversa a partir dali para ver o que o agente faz.
          O caso que a decisão proibia é justamente o que este `if` impede.
        */}
        {dado.state === "encaminhado" ? (
          <a className="botao" href={`/handoffs/${dado.id}`} data-testid="ir-para-atendimento">
            Assumir como atendente
          </a>
        ) : (
          <a
            className="botao botao--discreto"
            href={`/simulador?conversa=${dado.id}`}
            data-testid="continuar-como-cliente"
          >
            Continuar como cliente
          </a>
        )}
      </div>

      <div className="grade">
        <div className="metrica">
          <span className="metrica__valor num">{perfil.idade ?? "—"}</span>
          <span className="metrica__nome">idade do condutor</span>
        </div>
        <div className="metrica">
          <span className="metrica__valor num">{perfil.veiculo_ano ?? "—"}</span>
          <span className="metrica__nome">ano do veículo</span>
        </div>
        <div className="metrica">
          {/* Mascarado: não existe endpoint que devolva a versão crua. */}
          <span className="metrica__valor num">{cepMascarado(perfil.cep)}</span>
          <span className="metrica__nome">CEP</span>
        </div>
        <div className="metrica">
          <span className="metrica__valor">{perfil.plano_id ?? "—"}</span>
          <span className="metrica__nome">plano escolhido</span>
        </div>
      </div>

      {faltantes.length > 0 ? (
        <p className="chat__travado" data-testid="campos-faltantes">
          Qualificação em andamento — faltam:{" "}
          {faltantes.map((c) => ROTULO_CAMPO[c] ?? c).join(", ")}.
        </p>
      ) : null}

      <h2 className="secao__titulo" style={{ marginTop: "1.6rem" }}>
        Mensagens
      </h2>

      {/*
        DUAS leituras da mesma coisa, e as duas são necessárias.

        A **transcrição** é a conversa como o lead a viu — é para isso que o
        Histórico existe, e é o que faltava: o livro-razão respondia "que mensagens
        houve" e não "como foi a conversa". Ler um atendimento em linhas de tabela é
        possível e é ruim.

        O **razão** é a evidência do critério nº 4: id, índice, autor e status de
        cada mensagem, alinhados em coluna. Nenhum dado sai de um para o outro — é a
        mesma lista, com duas formas.

        A transcrição é o padrão porque a pergunta mais comum aqui é "o que
        aconteceu com esse lead", não "qual o id da terceira mensagem".
      */}
      <div className="alternador" role="group" aria-label="Forma de leitura">
        {([
          ["transcricao", "Transcrição"],
          ["lead", "Como o lead viu"],
          ["razao", "Razão"],
          ["trace", "Trace"],
        ] as const).map(
          ([chave, rotulo]) => (
            <button
              key={chave}
              type="button"
              className="alternador__opcao"
              aria-pressed={forma === chave}
              onClick={() => setForma(chave)}
            >
              {rotulo}
            </button>
          ),
        )}
      </div>
      {mensagens.length === 0 ? (
        <Vazio titulo="Nenhuma mensagem">
          A conversa existe mas ninguém falou ainda.
        </Vazio>
      ) : forma === "trace" ? (
        <TraceDaConversa id={id} />
      ) : forma === "lead" ? (
        /* A moldura de leitura. `.chat__thread` é a MESMA classe da conversa do
           lead — traz o papel, o espaçamento e o alinhamento das bolhas (que é
           `align-self`, e portanto depende do contêiner flex certo). O que ela não
           traz é o `chat__rodape`, o compositor, e isso é a decisão. */
        <div className="simulador vista-lead">
          <div className="vista-lead__moldura">
            <p className="vista-lead__aviso rotulo">
              somente leitura — a conversa como o lead a viu
            </p>
            <div className="chat__thread" data-testid="vista-lead">
              {mensagens.map((m) => (
                <Bolha
                  key={m.id}
                  mensagem={{ ...m, pendente: false, suspeitaDeBug: suspeita(m) }}
                />
              ))}
            </div>
          </div>
        </div>
      ) : forma === "transcricao" ? (
        <div className="transcricao" data-testid="transcricao">
          {mensagens.map((m) => (
            <div
              key={m.id}
              // O AUTOR na classe, e não "lead ou não-lead". Distinguir `sistema`
              // de `agente` é o ponto do admin: na conversa do lead os dois são
              // idênticos de propósito, e aqui a diferença é auditoria. Achatar os
              // dois em "nós" perdia isso — um teste pegou.
              className={`transcricao__linha transcricao__linha--${m.autor}`}
              data-testid={`bolha-${m.id}`}
            >
              <div className="transcricao__balao">
                {m.tipo !== "text" ? (
                  <span className="transcricao__anexo">
                    {m.tipo === "image"
                      ? "imagem anexada"
                      : m.tipo === "audio"
                        ? "áudio anexado"
                        : "documento anexado"}
                  </span>
                ) : null}
                <span className="transcricao__texto">{m.conteudo}</span>
                {suspeita(m) ? (
                  <span className="marca-bug" data-testid="marca-bug">
                    valor sem cotação vinculada
                  </span>
                ) : null}
                {/* O id e o status acompanham a bolha: sem eles a transcrição
                    deixaria de responder pelo critério nº 4, e a alternância viraria
                    "uma view bonita e uma view útil". */}
                <span className="transcricao__meta rotulo">
                  <span>{m.autor}</span>
                  <span className="num">{m.id}</span>
                  <span>{m.status}</span>
                  <span>{hora(m.criado_em)}</span>
                </span>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="razao">
          {mensagens.map((m) => (
            <div
              key={m.id}
              className={`msg msg--${m.autor}`}
              data-testid={`msg-${m.id}`}
              data-index={m.index}
            >
              <span className="num">{m.index}</span>
              <span className="rotulo">{m.autor}</span>
              <span className="msg__conteudo">
                {m.conteudo}
                {suspeita(m) ? (
                  <span className="marca-bug" data-testid="marca-bug">
                    valor sem cotação vinculada
                  </span>
                ) : null}
              </span>
              <span className="rotulo msg__meta">
                <span className="num">{m.id}</span>
                <span>{m.status}</span>
                <span>{hora(m.criado_em)}</span>
              </span>
            </div>
          ))}
        </div>
      )}

      <h2 className="secao__titulo" style={{ marginTop: "1.6rem" }}>
        Cotações
      </h2>
      {(dado.quotes ?? []).length === 0 ? (
        <Vazio titulo="Nenhuma cotação">
          Esta conversa não chegou a chamar a <code>/quote</code>.
        </Vazio>
      ) : (
        (dado.quotes ?? []).map((q) => <LinhaDoTempoCotacao key={q.id} quote={q} />)
      )}

      {(dado.handoffs ?? []).length > 0 ? (
        <>
          <h2 className="secao__titulo" style={{ marginTop: "1.6rem" }}>
            Handoffs
          </h2>
          {dado.handoffs.map((h) => (
            <div className={`handoff handoff--${h.status}`} data-testid={`handoff-${h.id}`} key={h.id}>
              <div className="handoff__topo">
                <span className="selo selo--falha">{h.trigger}</span>
                <span className="rotulo">disparado por {h.disparado_por}</span>
                <span className="selo selo--neutro">{h.status}</span>
              </div>
              <p className="vazio__texto">{h.reason}</p>
            </div>
          ))}
        </>
      ) : null}
    </section>
  );
}


/**
 * O trace de cada resposta: as tools que ela executou, em ordem, com os tokens do turno.
 *
 * **Carregado sob demanda, e não junto com o detalhe.** A pergunta "o que aconteceu com
 * esse lead" é a comum; "quais tools rodaram no turno 3" é a rara, e é cara — são todos
 * os `run_data` da conversa. Pendurá-la no detalhe faria toda abertura de conversa
 * pagar por uma resposta que quase ninguém pediu.
 *
 * **Os argumentos chegam MASCARADOS do backend**, e isso não é decoração: o Agno grava
 * `tool_args` como o modelo os escreveu, com o CEP cru — é o que a `/quote` precisa
 * receber. Toda a aplicação mascara PII na escrita; esta tabela é a exceção, porque
 * quem escreve nela é uma dependência. O mascaramento acontece em
 * `consultas.traces_da_conversa`, e não aqui, porque uma tela que recebe o dado cru já
 * o vazou — para o `curl` de quem chamar o endpoint direto, e para o devtools.
 */
function TraceDaConversa({ id }: { id: string }) {
  const { dado, erro, carregando, recarregar } = useRecurso<ListaDeTraces>(
    () => api.traces(id), [id],
  );

  if (erro) return <Erro erro={erro} aoTentarDeNovo={recarregar} />;
  if (carregando || !dado) return <p className="rotulo">carregando o trace…</p>;
  if (dado.items.length === 0) {
    return (
      <Vazio titulo="Sem trace">
        Esta conversa não tem execução registrada pelo agente. Acontece com conversas do
        dataset reproduzidas fora do caminho de produção.
      </Vazio>
    );
  }

  return (
    <div className="trace" data-testid="trace">
      {dado.items.map((t) => (
        <article key={t.run_id} className="trace__turno">
          <header className="trace__cabeca">
            <span className="num">#{t.index}</span>
            <span className="rotulo">{t.status}</span>
            <span className="rotulo">
              {t.tokens_in.toLocaleString("pt-BR")} in ·{" "}
              {t.tokens_out.toLocaleString("pt-BR")} out ·{" "}
              {/* "n/a" e nunca "0": o Ollama não reporta cache, e um zero ali seria
                  uma medição inventada. */}
              {t.cache_read === null ? "cache n/a" : `${t.cache_read.toLocaleString("pt-BR")} do cache`}
            </span>
            <span className="rotulo">{Math.round(t.duracao_ms)} ms</span>
          </header>

          {t.tools.length === 0 ? (
            <p className="trace__sem-tool rotulo">nenhuma tool — só texto</p>
          ) : (
            <ol className="trace__tools">
              {t.tools.map((tool, i) => (
                <li
                  key={`${t.run_id}-${i}`}
                  className={`trace__tool${tool.erro ? " trace__tool--erro" : ""}`}
                >
                  <span className="trace__nome num">{tool.nome}</span>
                  <span className="trace__dur rotulo">{tool.duracao_ms} ms</span>
                  <pre className="trace__args">{JSON.stringify(tool.argumentos)}</pre>
                  <p className="trace__resultado">{tool.resultado}</p>
                </li>
              ))}
            </ol>
          )}
        </article>
      ))}
    </div>
  );
}
