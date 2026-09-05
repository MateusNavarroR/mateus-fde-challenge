import { useCallback, useEffect, useState, type ReactNode } from "react";
import { api } from "../api/cliente";
import { useEventos } from "../admin/useEventos";
import { useRecurso } from "./useRecurso";
import { useAutenticacao, useSair } from "./useAutenticacao";
import type { FilaHandoffs } from "../api/tipos";

/**
 * A casca da operação: guia lateral colapsável, e o conteúdo à direita.
 *
 * **A metáfora é a guia de arquivo**, e ela não é enfeite — é o que resolve o
 * problema que as abas horizontais tinham. Cinco abas numa linha empilhavam coisas
 * de naturezas diferentes (identidade, navegação, estado) no mesmo lugar, e a seção
 * ativa só se anunciava por `aria-current`. Numa coluna, cada seção ganha ordinal,
 * nome e uma linha dizendo o que é — e a ativa é evidente porque a guia avança sobre
 * o conteúdo, como uma aba de pasta puxada para fora.
 *
 * **Colapsada, sobram os ordinais.** Não ícones: ícone de "histórico" e ícone de
 * "chat" são a mesma nuvenzinha para quem nunca viu este produto, e um ordinal
 * romano carimbado é inequívoco depois de visto uma vez. A largura vai de 15rem para
 * 3.5rem, o que devolve a tela inteira para a tabela de conversas — que é onde a
 * densidade importa.
 *
 * O estado do colapso vive no `localStorage`: quem trabalha com a barra fechada não
 * quer reabri-la a cada F5. É preferência de operador, não estado de produto — e é
 * exatamente o caso em que `localStorage` é a ferramenta certa.
 */

type Secao = {
  href: string;
  ordinal: string;
  nome: string;
  linha: string;
};

/** A ordem é a do trabalho: primeiro o quadro, depois o que aconteceu, depois o teste. */
export const SECOES: readonly Secao[] = [
  { href: "/painel", ordinal: "I", nome: "Painel",
    linha: "o quadro geral em números" },
  { href: "/historico", ordinal: "II", nome: "Histórico",
    linha: "as conversas, mensagem a mensagem" },
  { href: "/simulador", ordinal: "III", nome: "Simulador",
    linha: "converse com o agente" },
  { href: "/handoffs", ordinal: "IV", nome: "Handoffs",
    linha: "a fila que espera uma pessoa" },
  { href: "/status", ordinal: "V", nome: "Status",
    linha: "saúde da integração e custo" },
] as const;

const CHAVE_COLAPSO = "autoseguro.barra_colapsada";

function lerColapso(): boolean {
  try {
    return globalThis.localStorage?.getItem(CHAVE_COLAPSO) === "1";
  } catch {
    // Armazenamento bloqueado não pode derrubar a casca inteira.
    return false;
  }
}

export function Console({ rota, children }: { rota: string; children?: ReactNode }) {
  const [colapsada, setColapsada] = useState(lerColapso);
  // `limit: 1` porque a casca quer só a CONTAGEM, e o backend a calcula do lado
  // dele — a lista não vem junto. Em `/handoffs` isso são duas requisições ao mesmo
  // endpoint, e é deliberado: a alternativa seria a casca receber a fila da página,
  // acoplando a moldura ao conteúdo para economizar uma consulta de uma linha. As
  // duas recarregam no mesmo push, então não divergem.
  const fila = useRecurso<FilaHandoffs>(() => api.handoffs({ limit: 1 }), []);
  const auth = useAutenticacao();
  const sair = useSair();

  // O socket de EVENTOS é da operação, e só abre quando há acesso a ela.
  //
  // No simulador anônimo — que é público, porque um lead não faz login para pedir
  // cotação — ele batia num 401 e reconectava em laço com backoff, para sempre, contra
  // uma rota que nunca ia abrir. Barulho no console do avaliador e trabalho inútil no
  // servidor, para receber eventos que a tela não tem permissão de mostrar.
  const podeOuvirOperacao =
    auth.situacao === "conhecido" && (!auth.exigido || auth.autenticado);
  const conexao = useEventos(
    (tipo) => {
      if (tipo === "handoff.created" || tipo === "handoff.updated") fila.recarregar();
    },
    { ativo: podeOuvirOperacao },
  );

  const alternar = useCallback(() => {
    setColapsada((c) => {
      const proximo = !c;
      try {
        globalThis.localStorage?.setItem(CHAVE_COLAPSO, proximo ? "1" : "0");
      } catch {
        /* idem */
      }
      return proximo;
    });
  }, []);

  // `[` alterna a barra. É o atalho que editores usam para painéis laterais, então
  // quem o conhece acerta de primeira; quem não conhece nunca esbarra nele.
  useEffect(() => {
    const aoTeclar = (e: KeyboardEvent) => {
      const alvo = e.target as HTMLElement | null;
      const digitando = alvo?.tagName === "INPUT" || alvo?.tagName === "TEXTAREA";
      if (e.key === "[" && !digitando && !e.metaKey && !e.ctrlKey) alternar();
    };
    document.addEventListener("keydown", aoTeclar);
    return () => document.removeEventListener("keydown", aoTeclar);
  }, [alternar]);

  const pendentes = fila.dado?.pendentes ?? 0;
  const comSessao = auth.situacao === "conhecido" && auth.exigido && auth.autenticado;

  return (
    <div className={`console${colapsada ? " console--colapsada" : ""}`}>
      <aside className="guia">
        <div className="guia__marca">
          <span className="guia__sigla" aria-hidden="true">AS</span>
          <span className="guia__nome">
            <strong>AutoSeguro</strong>
            <span className="guia__formulario">operação</span>
          </span>
        </div>

        {/* O rótulo fica no `nav`, e não no `aside`: quem navega por marcos
            procura a navegação, e um `complementary` chamado "Seções" é
            um marco com o nome de outro. */}
        <nav className="guia__secoes" aria-label="Seções">
          {SECOES.map((s) => {
            const atual = rota === s.href || rota.startsWith(`${s.href}/`);
            return (
              <a
                key={s.href}
                className={`guia__secao${atual ? " guia__secao--atual" : ""}`}
                href={s.href}
                aria-current={atual ? "page" : undefined}
                title={colapsada ? `${s.nome} — ${s.linha}` : undefined}
                // O nome ACESSÍVEL é declarado, e não montado a partir dos filhos.
                // Sem isto, colapsada, a badge de pendentes engolia o rótulo e o link
                // de Handoffs passava a se chamar "5 handoffs pendentes" — quem
                // navega por leitor perdia o nome da seção justamente na que tem
                // trabalho esperando.
                aria-label={
                  s.href === "/handoffs" && pendentes > 0
                    ? `${s.nome}, ${pendentes} pendentes`
                    : s.nome
                }
              >
                <span className="guia__ordinal" aria-hidden="true">{s.ordinal}</span>
                <span className="guia__rotulo">
                  <span className="guia__titulo">{s.nome}</span>
                  <span className="guia__linha">{s.linha}</span>
                </span>
                {s.href === "/handoffs" && pendentes > 0 ? (
                  <span
                    className="guia__contagem"
                    data-testid="contagem-pendentes"
                    aria-hidden="true"
                  >
                    {pendentes}
                  </span>
                ) : null}
              </a>
            );
          })}
        </nav>

        <div className="guia__rodape">
          <span
            className={`pilula${conexao === "conectado" ? " pilula--viva" : " pilula--morta"}`}
            data-testid="pilula-conexao"
          >
            {conexao === "conectado" ? "recebendo em tempo real" : "sem conexão em tempo real"}
          </span>
          {comSessao ? (
            <button type="button" className="guia__sair" onClick={() => void sair()}>
              Encerrar sessão
            </button>
          ) : null}
          <button
            type="button"
            className="guia__alternar"
            onClick={alternar}
            aria-expanded={!colapsada}
            aria-label={colapsada ? "Expandir a barra lateral" : "Recolher a barra lateral"}
          >
            <span aria-hidden="true">{colapsada ? "»" : "«"}</span>
          </button>
        </div>
      </aside>

      <main className="console__conteudo">{children}</main>
    </div>
  );
}
