import { useEffect, useRef, useState } from "react";
import { api } from "../api/cliente";
import type { StatusHandoff } from "../api/tipos";
import type { ConversationDetail, Message } from "../api/tipos";
import { Bolha } from "../chat/Bolha";
import { Erro } from "../ui/Erro";
import { useRecurso } from "../ui/useRecurso";

/**
 * A conversa **do ponto de vista de quem atende** — com a caneta, não só a leitura.
 *
 * **O que faltava.** A fila de handoff listava casos e não deixava atender nenhum: o
 * agente encerrava a participação, o caso entrava na fila, e ali parava. "Assumir"
 * mudava um status e não abria porta nenhuma. Esta tela é a outra ponta — o operador
 * lê a conversa como ela chegou ao lead e responde na mesma conversa.
 *
 * **A perspectiva está invertida em relação à vista do lead, e é isso que a torna
 * a tela do agente:** aqui *nós* ficamos à direita e o lead à esquerda. É a mesma
 * inversão que qualquer mensageiro faz quando você troca de aparelho, e ela responde
 * sozinha à pergunta "quem falou isto?" sem precisar de rótulo em cada bolha.
 *
 * **Isto NÃO contraria a recusa de `admin → chat`.** Aquela decisão impedia o operador
 * de assumir o lugar do LEAD — escrever como se fosse ele numa conversa que já tem
 * handoff. Aqui ele escreve como a empresa, que é o papel que de fato lhe cabe, e as
 * mensagens são gravadas com autor `operador`: distinguíveis, no admin, tanto do
 * template determinístico (`sistema`) quanto do modelo (`agente`). Ver não é escrever;
 * escrever *pelo seu próprio lado* é outra coisa, e é o trabalho.
 */
export function Atendimento({ id }: { id: string }) {
  const [rascunho, setRascunho] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [recusa, setRecusa] = useState<string | null>(null);
  const [locais, setLocais] = useState<readonly Message[]>([]);
  const [encerrando, setEncerrando] = useState(false);
  const esteira = useRef<HTMLDivElement | null>(null);

  const { dado, erro, recarregar } = useRecurso<ConversationDetail>(
    () => api.conversa(id), [id],
  );

  // Do banco mais o que acabou de sair daqui. O POST devolve a mensagem gravada, com
  // id e index reais, então não há bolha "otimista" a reconciliar: o que aparece na
  // tela é exatamente a linha que existe no banco.
  const mensagens = [...(dado?.messages ?? []), ...locais].sort(
    (a, b) => a.index - b.index,
  );

  // Rola a ESTEIRA, nunca a página — o mesmo defeito já corrigido no chat do lead:
  // `scrollIntoView` arrasta todos os ancestrais roláveis e joga a janela para o topo.
  useEffect(() => {
    const el = esteira.current;
    if (el !== null) el.scrollTop = el.scrollHeight;
  }, [mensagens.length]);

  if (erro) return <Erro erro={erro} aoTentarDeNovo={recarregar} />;
  if (!dado) return <p className="rotulo">carregando a conversa…</p>;

  const encerrada = dado.state === "encaminhado";

  /*
   * O HANDOFF ABERTO desta conversa, para poder fechá-lo daqui.
   *
   * A tela nasceu sem esta ação, e a falta era gritante em uso: o operador assume o
   * caso, atende, resolve o problema do lead — e não tem como dizer que terminou. Ele
   * teria de voltar à fila, achar o mesmo caso no meio dos outros e só então marcar.
   * A ação pertence a quem está fazendo o trabalho, no momento em que ele acaba.
   *
   * O `resolvido` é terminal: não volta para pendente, e por isso a tela não oferece
   * desfazer — o que ela oferece é a confirmação de que aconteceu.
   */
  const aberto = (dado.handoffs ?? []).find((h) => h.status !== "resolvido") ?? null;

  async function transicionar(status: StatusHandoff) {
    if (aberto === null || encerrando) return;
    setEncerrando(true);
    setRecusa(null);
    try {
      await api.transicionarHandoff(aberto.id, status);
      recarregar();
    } catch (err: unknown) {
      setRecusa(err instanceof Error ? err.message : "Não consegui aplicar a transição.");
    } finally {
      setEncerrando(false);
    }
  }

  async function enviar(e: React.FormEvent) {
    e.preventDefault();
    const texto = rascunho.trim();
    if (texto.length === 0 || enviando) return;
    setEnviando(true);
    setRecusa(null);
    try {
      const m = await api.responderComoOperador(id, texto);
      setLocais((antes) => [...antes, m]);
      setRascunho("");
    } catch (err: unknown) {
      setRecusa(
        err instanceof Error ? err.message : "Não consegui enviar. Tente de novo.",
      );
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="folha atendimento">
      <header className="folha__cabeca">
        <h1 className="folha__titulo">Atendimento</h1>
        <p className="folha__linha">
          Conversa <span className="num">{id}</span> — você responde como a equipe. O
          agente já encerrou a participação nesta conversa; o que você escrever aqui vai
          para o lead na hora, e fica no histórico com autor <code>operador</code>.
        </p>
        <p className="folha__linha">
          <a href={`/historico/${id}`}>Ver o histórico completo</a>, com a linha do tempo
          das cotações e o trace de cada resposta.
        </p>
      </header>

      {!encerrada ? (
        // O backend recusa com 409, e a tela diz o mesmo antes de deixar tentar: o
        // agente ainda conduz, e duas vozes no mesmo turno deixam o lead sem saber
        // com quem está falando.
        <p className="erro" role="alert" data-testid="ainda-do-agente">
          Esta conversa ainda está com o agente. Só se responde depois do handoff.
        </p>
      ) : null}

      <div className="simulador atendimento__moldura">
        <div className="vista-lead__moldura">
          <p className="vista-lead__aviso rotulo">
            você está do lado da <strong>equipe</strong> — o lead vê o espelho disto
          </p>
          <div className="chat__thread atendimento__esteira" ref={esteira}
               data-testid="esteira-do-atendimento">
            {mensagens.map((m) => (
              <Bolha
                key={m.id}
                // `autor` invertido de propósito na renderização: a classe
                // `bolha--lead` é "a minha bolha", e aqui quem escreve somos nós.
                mensagem={{
                  ...m,
                  autor: m.autor === "lead" ? "agente" : "lead",
                  pendente: false,
                  suspeitaDeBug: false,
                }}
              />
            ))}
          </div>

          <form className="compositor atendimento__compositor" onSubmit={enviar}>
            <label className="so-leitor" htmlFor="resposta-do-operador">
              Sua resposta
            </label>
            <input
              id="resposta-do-operador"
              value={rascunho}
              placeholder={encerrada ? "Responda ao lead…" : "Aguardando o handoff…"}
              disabled={!encerrada || enviando}
              onChange={(e) => setRascunho(e.target.value)}
            />
            <button
              type="submit"
              className="botao"
              disabled={!encerrada || enviando || rascunho.trim().length === 0}
            >
              {enviando ? "Enviando…" : "Enviar"}
            </button>
          </form>
        </div>
      </div>

      <div className="handoff__acoes atendimento__fecho">
        {aberto === null ? (
          <p className="rotulo" data-testid="sem-handoff-aberto">
            nenhum handoff aberto nesta conversa
          </p>
        ) : (
          <>
            <span className="rotulo" data-testid="status-do-handoff">
              handoff <strong>{aberto.status}</strong> · {aberto.trigger}
            </span>
            {aberto.status === "pendente" ? (
              <button
                type="button"
                className="botao"
                disabled={encerrando}
                onClick={() => void transicionar("assumido")}
              >
                Assumir
              </button>
            ) : null}
            <button
              type="button"
              className="botao botao--discreto"
              disabled={encerrando}
              onClick={() => void transicionar("resolvido")}
            >
              {encerrando ? "Encerrando…" : "Marcar como resolvido"}
            </button>
          </>
        )}
      </div>

      {recusa !== null ? (
        <p className="erro" role="alert">{recusa}</p>
      ) : null}
    </div>
  );
}
