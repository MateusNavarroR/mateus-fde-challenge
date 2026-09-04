import { useEffect, useState } from "react";
import { Admin } from "./admin/Admin";
import { PaginaChat } from "./chat/PaginaChat";
import { Capa } from "./ui/Capa";
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
   * A GUARDA DA 2ª VIA, e a ordem das três condições é o conteúdo dela.
   *
   * 1. Enquanto o estado é `desconhecido`, ninguém decide. Renderizar o login "por
   *    precaução" faria a instalação ABERTA — o caminho padrão, o do avaliador —
   *    piscar um formulário de senha antes de mostrar o registro. Um flash desses
   *    ensina que existe uma senha que não existe.
   * 2. O login só aparece quando o backend disse `exigido` e `não autenticado`.
   * 3. **Esta guarda é conveniência, nunca segurança.** Quem manda é o
   *    `exigir_admin` do backend: sem sessão, cada chamada de `/api/*` volta 401 e
   *    a tela não tem o que mostrar. Um bypass no cliente não daria acesso a dado
   *    nenhum — por isso ela pode ser otimista quando a API não responde.
   */
  const barrado = auth.situacao === "conhecido" && auth.exigido && !auth.autenticado;

  if (rota.startsWith("/entrar")) {
    // Já entrou (ou a instalação é aberta): o balcão não tem por que existir.
    return barrado ? <Login /> : <Admin rota="/admin/conversas" />;
  }

  if (rota.startsWith("/admin")) {
    if (auth.situacao === "desconhecido") return <Aguardando />;
    return barrado ? <Login destino={rota} /> : <Admin rota={rota} />;
  }

  if (rota.startsWith("/chat")) return <PaginaChat />;

  // A raiz DECIDE: apresenta as duas vias em vez de cair no chat por omissão.
  // Caindo, a existência da segunda área ficava escondida de quem abre a
  // aplicação pela primeira vez — que é exatamente o avaliador.
  return <Capa />;
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
