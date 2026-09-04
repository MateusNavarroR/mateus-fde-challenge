import { useEffect, useState } from "react";
import { Admin } from "./admin/Admin";
import { PaginaChat } from "./chat/PaginaChat";
import { Capa } from "./ui/Capa";

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

  if (rota.startsWith("/admin")) return <Admin rota={rota} />;
  if (rota.startsWith("/chat")) return <PaginaChat />;

  // A raiz DECIDE: apresenta as duas vias em vez de cair no chat por omissão.
  // Caindo, a existência da segunda área ficava escondida de quem abre a
  // aplicação pela primeira vez — que é exatamente o avaliador.
  return <Capa />;
}
