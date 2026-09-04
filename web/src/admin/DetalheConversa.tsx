import { api } from "../api/cliente";
import type { ConversationDetail, Message } from "../api/tipos";
import { Erro } from "../ui/Erro";
import { Vazio } from "../ui/Vazio";
import { cepMascarado, hora } from "../ui/formatar";
import { useRecurso } from "../ui/useRecurso";
import { LinhaDoTempoCotacao } from "./LinhaDoTempoCotacao";

const DINHEIRO = /(R\$\s*[\d.,]+)|([\d.,]+\s*reais\b)/i;

function suspeita(m: Message): boolean {
  if (m.autor === "lead") return false;
  const temQuote = m.quote_id !== null && m.quote_id !== undefined && m.quote_id !== "";
  return DINHEIRO.test(m.conteudo) && !temQuote;
}

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
      {mensagens.length === 0 ? (
        <Vazio titulo="Nenhuma mensagem">
          A conversa existe mas ninguém falou ainda.
        </Vazio>
      ) : (
        <div>
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
