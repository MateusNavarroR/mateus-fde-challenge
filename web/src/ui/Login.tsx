import { useId, useState } from "react";
import { ErroApi, api } from "../api/cliente";
import { reconsultarAutenticacao } from "./useAutenticacao";
import { SECOES } from "./Console";

/**
 * A porta da 2ª via.
 *
 * **A ideia, e ela vem do domínio, não de um padrão de dashboard.** O sistema já
 * chama suas duas áreas de *vias* de um mesmo documento: a 1ª é do cliente, a 2ª
 * fica no arquivo. Pedir credencial para a 2ª via não é "fazer login num app" — é
 * **requisitar acesso ao arquivo**, e o balcão pergunta quem está requisitando. Toda
 * a tela é escrita nessa voz, e por isso ela se explica sem instrução de uso.
 *
 * **A folha é a mesma da capa**, deliberadamente: quem clicou na 2ª via não trocou
 * de aplicação, encontrou um balcão. O que muda é uma coisa só, e ela é o elemento
 * mais forte da tela — a **linha picotada** acima do formulário, onde a 1ª via foi
 * destacada. É a única marca que diz, sem texto, "você está na segunda folha".
 *
 * **O que a tela NÃO faz, e cada omissão é uma decisão:**
 *
 * - *não tem carimbo girado.* O sistema visual reserva escala e rotação a um único
 *   elemento na aplicação inteira, o disjuntor em `/admin/status`. Um segundo carimbo
 *   aqui roubaria dele exatamente o que o torna achável em dois segundos;
 * - *não tem "lembrar de mim".* A sessão já dura um turno e vive num cookie
 *   `httpOnly`; a caixinha só serviria para dar a impressão de controle sobre algo
 *   que o servidor decide;
 * - *não tem "esqueci a senha".* Não há cadastro, e-mail nem recuperação: a
 *   credencial é uma variável de ambiente de quem operou o `docker compose`. Um link
 *   que não leva a lugar nenhum é pior que a ausência dele — a nota do rodapé diz a
 *   verdade em uma linha;
 * - *não diz se o usuário existe.* O backend devolve a mesma recusa para nome errado
 *   e senha errada, e a tela repete essa recusa sem enfeitar.
 *
 * **Nada de senha sai daqui.** O campo é `type="password"`, `autoComplete` é
 * `current-password` (o gerenciador do navegador é a resposta certa para "onde
 * guardo isso"), o formulário é `POST` por `fetch` — nunca `GET`, que poria a senha
 * na barra de endereços e no log do servidor — e o estado local é descartado no
 * sucesso. A sessão volta num cookie que este código não consegue ler.
 */
export function Login({ destino = "/admin/conversas" }: { destino?: string }) {
  const idUsuario = useId();
  const idSenha = useId();

  const [usuario, setUsuario] = useState("");
  const [senha, setSenha] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [recusa, setRecusa] = useState<string | null>(null);

  async function enviar(e: React.FormEvent) {
    e.preventDefault();
    if (enviando) return;
    setEnviando(true);
    setRecusa(null);
    try {
      await api.entrar(usuario, senha);
      // A senha some da memória do componente no instante em que deixa de ser
      // necessária. Não impede um dump de heap, mas encurta a janela — e a linha
      // custa nada.
      setSenha("");
      await reconsultarAutenticacao();
      history.pushState(null, "", destino);
      // O `App` escuta `popstate` para navegação de volta; um `pushState` não o
      // dispara sozinho, então o evento é emitido aqui.
      window.dispatchEvent(new PopStateEvent("popstate"));
    } catch (erro: unknown) {
      setSenha("");
      setRecusa(
        erro instanceof ErroApi && erro.status !== null
          ? erro.message
          : "Não consegui falar com o backend. Confira se o serviço está no ar.",
      );
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="capa">
      <div className="capa__folha login">
        <p className="capa__formulario">seguro auto · proposta</p>
        <h1 className="capa__marca">AutoSeguro</h1>

        {/* A linha por onde a 1ª via foi destacada. Decorativa para o leitor de
            tela — o que ela comunica já está dito em texto logo abaixo. */}
        <div className="login__picote" aria-hidden="true" />

        <p className="capa__ordinal login__ordinal">controle de acesso · operação</p>
        <h2 className="login__titulo">Requisição de acesso ao arquivo</h2>
        <p className="capa__linha">
          Esta instalação pede credencial para a área de operação. Ela é a{" "}
          <code>ADMIN_USER</code> e a <code>ADMIN_PASSWORD</code> definidas no ambiente
          de quem subiu o serviço.
        </p>

        {/* O que existe atrás da porta, nomeado antes de ela abrir. Uma tela de login
            que só diz "entre" obriga quem chega a adivinhar se vale a pena procurar a
            credencial — e aqui quem chega é um avaliador com pressa. Os ordinais são
            os mesmos da guia lateral, lidos da MESMA constante: a lista ensina a
            navegação que ele encontra do outro lado, e não pode divergir dela. */}
        <ol className="login__secoes">
          {SECOES.map((secao) => (
            <li key={secao.href} className="login__secao">
              <span className="login__romano" aria-hidden="true">{secao.ordinal}</span>
              <span>
                <strong>{secao.nome}</strong> — {secao.linha}
              </span>
            </li>
          ))}
        </ol>

        <form className="login__form" onSubmit={enviar} noValidate>
          <span className="campo">
            <label className="rotulo" htmlFor={idUsuario}>
              Usuário
            </label>
            <input
              id={idUsuario}
              name="usuario"
              value={usuario}
              autoComplete="username"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              autoFocus
              required
              onChange={(e) => setUsuario(e.target.value)}
            />
          </span>

          <span className="campo">
            <label className="rotulo" htmlFor={idSenha}>
              Senha
            </label>
            <input
              id={idSenha}
              name="senha"
              type="password"
              value={senha}
              autoComplete="current-password"
              required
              onChange={(e) => setSenha(e.target.value)}
            />
          </span>

          <button type="submit" className="botao login__entrar" disabled={enviando}>
            {enviando ? "Conferindo…" : "Entrar"}
          </button>
        </form>

        {/* `role="alert"` e não um texto qualquer: quem usa leitor de tela precisa
            saber que a tentativa falhou sem ter de sair procurando. */}
        {recusa !== null ? (
          <p className="erro login__recusa" role="alert">
            {recusa}
          </p>
        ) : null}

        <p className="capa__rodape">
          Não há cadastro nem recuperação de senha: a credencial vive no ambiente do
          serviço. Sem <code>ADMIN_USER</code> e <code>ADMIN_PASSWORD</code> definidas,
          esta tela não existe e a operação abre direto.{" "}
          <a href="/simulador">O chat simulado é público</a> e não pede credencial: é a
          conversa do lead, e um lead não faz login para pedir cotação.
        </p>
      </div>
    </div>
  );
}
