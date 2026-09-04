import { useId, useState } from "react";
import { ErroApi, gravarToken } from "../api/cliente";

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
  const api = erro instanceof ErroApi ? erro : null;
  const tipo = api?.tipo ?? "erro";

  if (tipo === "nao_autorizado") {
    return (
      <div className="erro" role="alert">
        <p className="erro__titulo">Esta instalação exige um token de administração</p>
        <p className="erro__texto">
          O <code>ADMIN_TOKEN</code> está definido no backend. Ele fica guardado só neste
          navegador e vai como cabeçalho em cada chamada.
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
