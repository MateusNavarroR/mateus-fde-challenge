import { useEffect, useRef, useState } from "react";
import type {
  ConversationDetail,
  EstadoConversa,
  Message,
  TipoMensagem,
} from "../api/tipos";
import { Bolha } from "./Bolha";
import { BlocoCotacao } from "./BlocoCotacao";
import { Digitando } from "./Digitando";
import { abrirSessao, historicoLocal, reiniciarSessao, retomarConversa } from "./sessao";
import { useConversa } from "./useConversa";

/** "14:03" para hoje, "05/09" para antes. O id curto ao lado desambigua. */
function quando(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "anterior";
  const hoje = new Date();
  const mesmoDia = d.toDateString() === hoje.toDateString();
  return mesmoDia
    ? d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
}

const ESTADO_LEGIVEL: Record<string, string> = {
  novo: "conversa aberta",
  qualificando: "coletando dados",
  cotando: "cotação em andamento",
  cotado: "cotação entregue",
  fechado: "conversa encerrada",
  encaminhado: "com a equipe",
};

/**
 * A tela é um **cliente burro** de um fluxo de eventos. Ela não decide nada
 * sobre a conversa: recebe `MessageEvent`, `TypingEvent` e `StateEvent`, mantém
 * um mapa `id → Message` e renderiza ordenado por `index`.
 *
 * Não existe cronômetro aqui. Os 6 s e os 20 s da política de degradação são do
 * backend — se a tela tivesse um `setTimeout(6000)`, existiriam duas cópias da
 * política e elas divergiriam na primeira mudança de limiar.
 */
export function PaginaChat({ conversationId }: { conversationId?: string }) {
  const [id, setId] = useState<string | null>(conversationId ?? null);
  const [historico, setHistorico] = useState<Message[] | null>(null);
  const [estadoInicial, setEstadoInicial] = useState<EstadoConversa | null>(null);
  const [falhaAoAbrir, setFalhaAoAbrir] = useState(false);
  const [rascunho, setRascunho] = useState("");
  const thread = useRef<HTMLElement | null>(null);

  // Retomada ao carregar. Um F5 no meio de uma janela de 37 s não pode destruir
  // a conversa — sempre-nova é o comportamento do botão, não do carregamento.
  useEffect(() => {
    if (conversationId !== undefined) return;
    let vivo = true;
    void abrirSessao()
      .then(({ id: aberta, detalhe }: { id: string; detalhe: ConversationDetail | null }) => {
        if (!vivo) return;
        setHistorico(detalhe?.messages ?? null);
        setEstadoInicial(detalhe?.state ?? null);
        setId(aberta);
      })
      .catch(() => {
        if (vivo) setFalhaAoAbrir(true);
      });
    return () => {
      vivo = false;
    };
  }, [conversationId]);

  // Recalculado a cada troca de conversa: `lembrarConversa` acabou de reordenar a
  // lista, e um `useState` aqui mostraria a ordem anterior.
  const anteriores = historicoLocal();

  const anexo = useRef<HTMLInputElement>(null);
  const { estado, enviar } = useConversa(id, historico, estadoInicial);

  // Rola a ESTEIRA, e não o elemento pela API do navegador.
  //
  // `scrollIntoView` rola **todos** os ancestrais roláveis até o elemento aparecer —
  // inclusive a página. Com a moldura ancorada e conteúdo acima dela, cada mensagem
  // enviada arrastava a janela inteira para o topo: o usuário perdia de vista o que
  // estava lendo a cada envio. Mexer no `scrollTop` do contêiner move só ele, que é
  // o que se queria desde o começo.
  useEffect(() => {
    const esteira = thread.current;
    if (esteira === null) return;
    esteira.scrollTop = esteira.scrollHeight;
  }, [estado.mensagens.length, estado.digitando]);

  const submeter = () => {
    const texto = rascunho.trim();
    if (texto.length === 0) return;
    enviar(texto);
    setRascunho("");
  };

  /**
   * Anexo: registra que **chegou mídia**, sem subir o arquivo.
   *
   * O canal aqui é uma moldura de conversa, não um WhatsApp: guardar os bytes
   * criaria uma superfície de dado sensível (uma foto de CNH, um áudio com o CPF
   * falado) que este projeto declara não ter. O que a conversa precisa saber é que
   * o lead mandou mídia em vez de texto — e é isso, e só isso, que trafega.
   *
   * É o que torna `MIDIA_SEM_TEXTO` alcançável de verdade: a primeira mídia faz o
   * agente pedir texto, a segunda encaminha.
   */
  const anexar = (arquivo: File) => {
    const tipo: TipoMensagem = arquivo.type.startsWith("image/")
      ? "image"
      : arquivo.type.startsWith("audio/")
        ? "audio"
        : "document";
    enviar(arquivo.name, tipo);
  };

  const trocarDeConversa = () => {
    void reiniciarSessao()
      .then((nova) => {
        setHistorico(null);
        setEstadoInicial(null);
        setId(nova);
      })
      .catch(() => setFalhaAoAbrir(true));
  };

  const estadoDaConversa = (
    <span className="pilula" data-testid="estado-conversa">
      {ESTADO_LEGIVEL[estado.state] ?? estado.state}
    </span>
  );

  return (
    // Sem casca própria: quem dá a moldura é o `Console`, e o chat vive dentro do
    // `Simulador`. A `Casca` aqui renderizava marca e navegação DENTRO da barra
    // lateral — duas cascas empilhadas, com dois conjuntos de links para as mesmas
    // seções.
    <div className="chat">
      <div className="chat__acoes">
        {/* O estado da conversa vinha na casca antiga. Ele é informação de PRODUTO —
            "com a equipe" muda o que o lead pode fazer —, então acompanha as ações
            em vez de sumir junto com a moldura. */}
        <span className="chat__estado" data-testid="estado-da-conversa">
          {estadoDaConversa}
        </span>
        <button type="button" className="botao-fantasma" onClick={trocarDeConversa}>
          Nova conversa
        </button>
        {/*
          ESCOLHER QUAL CONVERSA CONTINUAR.
          
          Antes só existia a última: quem clicava em "Nova conversa" perdia a anterior
          de vista, sem forma de voltar. Para exercitar o agente é o contrário do que
          se quer — comparar dois caminhos exige ter os dois à mão.

          A lista vem do NAVEGADOR, não da API. `GET /api/conversations` devolveria as
          conversas de todo mundo, e um seletor no chat público mostrando a conversa de
          outro lead é vazamento, não conveniência. Cada navegador lista o que ele
          mesmo abriu — ids que ele já tinha.

          Some quando há só uma: um seletor de um item é ruído.
        */}
        {anteriores.length > 1 ? (
          <label className="chat__retomar">
            <span className="so-leitor">Continuar uma conversa</span>
            <select
              data-testid="seletor-de-conversa"
              value={id ?? ""}
              onChange={(e) => {
                const escolhida = e.target.value;
                if (escolhida && escolhida !== id) {
                  setHistorico(null);
                  setEstadoInicial(null);
                  setId(retomarConversa(escolhida));
                }
              }}
            >
              {anteriores.map((c, i) => (
                <option key={c.id} value={c.id}>
                  {i === 0 ? "mais recente" : quando(c.aberta_em)} · {c.id.slice(-6)}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        {/*
          A navegação é assimétrica de propósito: `chat → admin` existe e é a
          demonstração inteira da rastreabilidade. O inverso não existe.
        */}
        {id !== null ? (
          <a className="elo-admin" href={`/admin/conversas/${id}`}>
            Ver esta conversa no admin
          </a>
        ) : null}
      </div>

      <main className="chat__thread" ref={thread}>
        {estado.conexao === "reconectando" ? (
          <p role="status" className="pilula pilula--atencao">
            Reconectando… nada se perde: ao voltar, tudo que chegou aparece aqui.
          </p>
        ) : null}

        {falhaAoAbrir ? (
          <div role="alert" className="erro">
            <p className="erro__titulo">Não consegui abrir a conversa</p>
            <p className="erro__texto">
              O backend não respondeu. Confira se ele está no ar com{" "}
              <code>docker compose ps</code> e tente de novo.
            </p>
            <button
              type="button"
              className="botao"
              onClick={() => {
                setFalhaAoAbrir(false);
                trocarDeConversa();
              }}
            >
              Tentar de novo
            </button>
          </div>
        ) : null}

        {/*
          Vazio é convite. Uma janela em branco de 37 s já é longa o bastante sem
          que a primeira tela também não diga nada.
        */}
        {!falhaAoAbrir && estado.mensagens.length === 0 && !estado.digitando ? (
          <p className="vazio__texto" data-testid="conversa-vazia">
            Conte o que você precisa: idade, ano do carro, CEP e quando quer começar. Com
            isso eu já consigo buscar o valor.
          </p>
        ) : null}

        {estado.mensagens.map((m) =>
          m.quote_id !== null && m.quote_id !== undefined && m.quote_id !== "" ? (
            <BlocoCotacao key={m.id} mensagem={m} />
          ) : (
            <Bolha key={m.id} mensagem={m} />
          ),
        )}

        {estado.digitando ? <Digitando /> : null}
      </main>

      <footer className="chat__rodape">
        {/*
          A saída fica AQUI, junto do campo travado, e não só no botão do topo.

          Achado na vistoria: entrando pela capa — que promete "fale com o agente e
          peça uma cotação" — dá para cair numa conversa `encaminhado` de uma sessão
          anterior, com o campo morto. A tela explicava o porquê e a saída existia,
          mas a três centímetros dali e sem relação visual com o problema.

          Não é caso de apagar o histórico ao carregar: a retomada é deliberada, e um
          F5 no meio de uma janela de 37 s não pode destruir a conversa. O que faltava
          era a ação estar onde a pessoa está olhando quando descobre que não pode
          escrever.
        */}
        {/*
          AVISA, E NÃO TRAVA — e a diferença apareceu quando o atendimento humano
          passou a existir de verdade.

          `encaminhado` significa que o AGENTE encerrou a participação, não que a
          conversa acabou. Enquanto ninguém podia assumir a fila, travar o campo era
          defensável: o lead não ficava falando sozinho. Agora que um operador
          responde pela mesma conversa, travar transforma o handoff num beco — a
          pessoa escreve "oi, aqui é a Ana" e o lead não tem como responder.

          O que ele digita daqui em diante fica registrado e **não vai ao modelo**:
          a guarda no topo de `responder` ignora conversa encaminhada. É mensagem
          para a pessoa que assumiu, e é ela quem lê.
        */}
        {estado.entradaBloqueada ? (
          <p className="chat__travado">
            Sua conversa está com um atendente da equipe. Pode escrever normalmente —
            quem responde daqui em diante é uma pessoa.{" "}
            <button
              type="button"
              className="chat__travado-acao"
              onClick={trocarDeConversa}
            >
              Começar uma conversa nova
            </button>
          </p>
        ) : null}
        <form
          className="compositor"
          onSubmit={(e) => {
            e.preventDefault();
            submeter();
          }}
        >
          <label className="so-leitor" htmlFor="campo-mensagem">
            Sua mensagem
          </label>
          <input
            ref={anexo}
            type="file"
            // `hidden`, e não a classe de leitor de tela: `so-leitor` esconde aos
            // olhos e MANTÉM na árvore de acessibilidade, então quem navega por
            // leitor encontrava dois controles ("Choose File" e "Anexar mídia")
            // para a mesma ação. O botão visível é o único controle; este input é
            // só o mecanismo, e `.click()` funciona em input escondido.
            hidden
            id="campo-anexo"
            onChange={(e) => {
              const arquivo = e.target.files?.[0];
              if (arquivo) anexar(arquivo);
              // Zera para que anexar o MESMO arquivo duas vezes seguidas continue
              // disparando `change` — é justamente a insistência que o gatilho lê.
              e.target.value = "";
            }}
          />
          <button
            type="button"
            className="compositor__anexo"
            onClick={() => anexo.current?.click()}
            aria-label="Anexar mídia"
            title="Anexar mídia"
          >
            +
          </button>
          <textarea
            id="campo-mensagem"
            className="compositor__campo"
            placeholder="Escreva aqui…"
            rows={1}
            value={rascunho}
            onChange={(e) => setRascunho(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submeter();
              }
            }}
          />
          <button
            type="submit"
            className="compositor__enviar"
            disabled={rascunho.trim().length === 0}
          >
            Enviar
          </button>
        </form>
      </footer>
    </div>
  );
}
