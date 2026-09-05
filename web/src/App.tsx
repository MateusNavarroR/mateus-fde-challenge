import { useEffect, useState } from "react";
import { DetalheConversa } from "./admin/DetalheConversa";
import { PaginaConversas } from "./admin/PaginaConversas";
import { PaginaHandoffs } from "./admin/PaginaHandoffs";
import { PaginaStatus } from "./admin/PaginaStatus";
import { Painel } from "./admin/Painel";
import { Simulador } from "./chat/Simulador";
import { Console, SECOES } from "./ui/Console";
import { Login } from "./ui/Login";
import { useAutenticacao } from "./ui/useAutenticacao";

/**
 * Roteador mínimo, de propósito.
 *
 * São cinco rotas e nenhuma delas precisa de nested layouts, loaders ou data
 * routers. Uma dependência de roteamento aqui pagaria em superfície de API e em
 * um `<Router>` obrigatório em volta de todo teste de componente — que é o tipo
 * de acoplamento que faz um teste de unidade deixar de ser de unidade.
 */
function useRota(): string {
  const [rota, setRota] = useState(
    () => globalThis.location?.pathname ?? "/",
  );

  useEffect(() => {
    const aoVoltar = () => setRota(globalThis.location.pathname);
    window.addEventListener("popstate", aoVoltar);

    // Navegação interna sem recarregar: o admin mantém um socket por sessão, e
    // um reload a cada clique o derrubaria — que é justamente o que a evidência
    // de push em tempo real precisa não acontecer.
    const aoClicar = (e: MouseEvent) => {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey) return;
      const alvo = (e.target as HTMLElement | null)?.closest("a");
      if (!alvo) return;
      const href = alvo.getAttribute("href");
      if (!href || !href.startsWith("/") || alvo.target === "_blank") return;
      e.preventDefault();
      history.pushState(null, "", href);
      setRota(globalThis.location.pathname);
    };
    document.addEventListener("click", aoClicar);

    return () => {
      window.removeEventListener("popstate", aoVoltar);
      document.removeEventListener("click", aoClicar);
    };
  }, []);

  return rota;
}

export function App() {
  const rota = useRota();
  const auth = useAutenticacao();

  /*
   * A GUARDA DA OPERAÇÃO, e a ordem das três condições é o conteúdo dela.
   *
   * 1. Enquanto o estado é `desconhecido`, ninguém decide. Renderizar o login "por
   *    precaução" faria a instalação ABERTA — o caminho padrão, o do avaliador —
   *    piscar um formulário de senha antes de mostrar o painel. Um flash desses
   *    ensina que existe uma senha que não existe.
   * 2. O login só aparece quando o backend disse `exigido` e `não autenticado`.
   * 3. **Esta guarda é conveniência, nunca segurança.** Quem manda é o
   *    `exigir_admin` do backend: sem sessão, cada chamada de `/api/*` volta 401 e
   *    a tela não tem o que mostrar. Um bypass no cliente não daria acesso a dado
   *    nenhum — por isso ela pode ser otimista quando a API não responde.
   */
  const barrado = auth.situacao === "conhecido" && auth.exigido && !auth.autenticado;

  // As rotas antigas continuam funcionando. Elas estão em transcripts commitados, no
  // README e em links que alguém já pode ter guardado — quebrar um link para renomear
  // uma rota é custo sem benefício.
  const destino = LEGADO[rota] ?? rota;
  if (destino !== rota) {
    history.replaceState(null, "", destino);
  }

  if (destino === "/entrar") {
    // Já entrou (ou a instalação é aberta): o balcão não tem por que existir.
    return barrado ? <Login /> : <Operacao rota="/painel" />;
  }

  if (SECOES.some((s) => destino === s.href || destino.startsWith(`${s.href}/`))) {
    if (auth.situacao === "desconhecido") return <Aguardando />;
    return barrado ? <Login destino={destino} /> : <Operacao rota={destino} />;
  }

  // A RAIZ é o login quando há credencial, e o painel quando não há.
  //
  // Não existe mais uma "capa" escolhendo entre duas vias: com a barra lateral, todas
  // as seções ficam visíveis de qualquer tela, e uma folha de rosto no meio do caminho
  // vira um clique a mais para chegar onde já dava para ver.
  if (auth.situacao === "desconhecido") return <Aguardando />;
  return barrado ? <Login /> : <Operacao rota="/painel" />;
}

/** As rotas antigas, apontando para as novas. Link guardado continua abrindo. */
const LEGADO: Record<string, string> = {
  "/": "/",
  "/chat": "/simulador",
  "/admin": "/painel",
  "/admin/conversas": "/historico",
  "/admin/status": "/status",
  "/admin/handoffs": "/handoffs",
};

/**
 * A casca com a guia lateral, e o que ela mostra em cada seção.
 *
 * O `Console` não conhece as páginas e as páginas não conhecem o `Console`: ele
 * recebe a rota e as renderiza como filhos. É o que permite testar uma página sem
 * montar a barra inteira, e trocar a barra sem tocar em nenhuma página.
 */
function Operacao({ rota }: { rota: string }) {
  return (
    <Console rota={rota}>
      {rota.startsWith("/historico/") ? (
        <DetalheConversa id={rota.slice("/historico/".length)} />
      ) : rota === "/historico" ? (
        <PaginaConversas />
      ) : rota === "/simulador" ? (
        <Simulador />
      ) : rota === "/handoffs" ? (
        <PaginaHandoffs />
      ) : rota === "/status" ? (
        <PaginaStatus />
      ) : (
        <Painel />
      )}
    </Console>
  );
}

/**
 * O intervalo entre "a página montou" e "o backend disse se pede senha".
 *
 * Deliberadamente mudo: sem spinner, sem esqueleto, sem "carregando". A resposta
 * chega em uma volta de rede local, e qualquer coisa animada nesse intervalo pisca —
 * o que é mais barulhento que a espera. O texto existe só para o leitor de tela.
 */
function Aguardando() {
  return (
    <div className="capa">
      <p className="so-leitor" role="status">
        Conferindo se esta instalação exige credencial.
      </p>
    </div>
  );
}
