import { useId, useState } from "react";
import { ErroApi, gravarToken } from "../api/cliente";
import { useAutenticacao } from "./useAutenticacao";

/**
 * Erro é estado de produto: uma tela em branco é a pior resposta possível a um
 * backend parado, porque não distingue "não há nada" de "não consegui perguntar".
 *
 * Cada tipo diz **o que fazer**, não só que algo deu errado. O 401 em particular
 * pede o `ADMIN_TOKEN` em vez de repetir a palavra "erro": o token é opcional e
 * exigido quando definido (CLAUDE.md 14c), então quem tropeça nele já sabe que
 * existe — falta só onde digitar.
 */
export function Erro({ erro, aoTentarDeNovo }: { erro: unknown; aoTentarDeNovo: () => void }) {
  const idCampo = useId();
  const [token, setToken] = useState("");
  const auth = useAutenticacao();
  const api = erro instanceof ErroApi ? erro : null;
  const tipo = api?.tipo ?? "erro";

  /*
   * UM 401 TEM DUAS CAUSAS DIFERENTES, e a tela dizia sempre a mesma coisa.
   *
   * Quando o login está configurado (`ADMIN_USER`/`ADMIN_PASSWORD`), um 401 significa
   * que a SESSÃO acabou — e ela acaba também quando o serviço reinicia, porque o salt
   * do `scrypt` é sorteado a cada boot e a chave que assina o cookie deriva dele
   * (`app/auth.py`). Nesse caso a tela oferecia um campo de `ADMIN_TOKEN` e afirmava
   * "o ADMIN_TOKEN está definido no backend" — uma frase falsa sobre uma variável
   * vazia, mandando o operador procurar um segredo que não existe para resolver um
   * problema cuja resposta é entrar de novo.
   *
   * O campo de token continua, e continua certo, para a outra causa: instalação sem
   * login, com `ADMIN_TOKEN` definido. Aí não há sessão nenhuma para renovar.
   */
  if (tipo === "nao_autorizado" && auth.situacao === "conhecido" && auth.exigido) {
    return (
      <div className="erro" role="alert">
        <p className="erro__titulo">Sua sessão de operação expirou</p>
        <p className="erro__texto">
          Entre de novo para continuar. A sessão também termina quando o serviço
          reinicia: a chave que assina o cookie é derivada de um salt sorteado a cada
          boot, então um <code>docker compose up</code> encerra as sessões abertas —
          é por isso que isso acontece sem você ter feito nada.
        </p>
        <a className="botao" href="/entrar">
          Entrar de novo
        </a>
      </div>
    );
  }

  if (tipo === "nao_autorizado") {
    return (
      <div className="erro" role="alert">
        <p className="erro__titulo">Esta instalação exige um token de administração</p>
        <p className="erro__texto">
          O <code>ADMIN_TOKEN</code> está definido no backend. Ele fica guardado{" "}
          <strong>nesta aba</strong> e vai como cabeçalho em cada chamada; fechar a aba
          o descarta. Para uso diário no navegador, prefira{" "}
          <code>ADMIN_USER</code>/<code>ADMIN_PASSWORD</code>, que usam cookie{" "}
          <code>httpOnly</code> e não ficam legíveis para o JavaScript da página.
        </p>
        <form
          className="filtros"
          onSubmit={(e) => {
            e.preventDefault();
            gravarToken(token.trim());
            aoTentarDeNovo();
          }}
        >
          <span className="campo">
            <label className="rotulo" htmlFor={idCampo}>
              ADMIN_TOKEN
            </label>
            <input
              id={idCampo}
              type="password"
              value={token}
              autoComplete="off"
              onChange={(e) => setToken(e.target.value)}
            />
          </span>
          <button type="submit" className="botao">
            Tentar de novo
          </button>
        </form>
      </div>
    );
  }

  if (tipo === "nao_encontrado") {
    return (
      <div className="erro" role="alert">
        <p className="erro__titulo">Não encontrado</p>
        <p className="erro__texto">
          {api?.message ?? "Esse registro não existe mais."} Se o banco foi recriado
          (<code>docker compose down -v</code>), os ids anteriores não voltam.
        </p>
        <button type="button" className="botao botao--discreto" onClick={aoTentarDeNovo}>
          Tentar de novo
        </button>
      </div>
    );
  }

  return (
    <div className="erro" role="alert">
      <p className="erro__titulo">Backend indisponível</p>
      <p className="erro__texto">
        {tipo === "conflito" && api?.message ? (
          api.message
        ) : (
          <>
            Não consegui falar com a API. Confira se o serviço está no ar com{" "}
            <code>docker compose ps</code> e tente de novo.
          </>
        )}
      </p>
      <button type="button" className="botao" onClick={aoTentarDeNovo}>
        Tentar de novo
      </button>
    </div>
  );
}
