import { useAutenticacao } from "./useAutenticacao";

/**
 * A rota `/`.
 *
 * Antes ela caía no chat por omissão, e o efeito era que a existência da segunda
 * área ficava escondida: quem abria a aplicação via uma conversa e não tinha
 * motivo para supor que houvesse um admin.
 *
 * A capa **decide alguma coisa**: apresenta as duas vias, diz quem lê cada uma, e
 * deixa a escolha explícita. É a folha de rosto de uma proposta — a peça que
 * existe justamente para dizer o que vem depois.
 *
 * Ela não é uma landing page: sem herói, sem argumento de venda. Três linhas e
 * duas escolhas, porque o leitor aqui é um avaliador com pouco tempo.
 *
 * **A única coisa que a autenticação mudou aqui.** Quando a instalação define
 * `ADMIN_USER`/`ADMIN_PASSWORD`, a 2ª via passa a levar ao balcão de credencial em
 * vez de ao registro. O link é reescrito **antes** do clique, e não depois: deixar
 * a capa apontar para `/admin` e o admin devolver 401 seco seria oferecer uma porta
 * e bater com ela na cara de quem aceitou. O selo "exige credencial" avisa em uma
 * linha, e some por completo na instalação aberta — que é o caminho padrão, e onde
 * um aviso sobre senha só criaria a suspeita de que falta um passo.
 */
export function Capa() {
  const auth = useAutenticacao();
  const pedeCredencial = auth.situacao === "conhecido" && auth.exigido && !auth.autenticado;

  return (
    <div className="capa">
      <div className="capa__folha">
        <p className="capa__formulario">seguro auto · proposta</p>
        <h1 className="capa__marca">AutoSeguro</h1>
        <p className="capa__linha">
          Um agente atende o lead por mensagem, qualifica, cota na API de cotação e
          decide sozinho quando passar para um humano.
        </p>

        <div className="capa__vias">
          <a className="capa__via" href="/chat">
            <span className="capa__ordinal">1ª via</span>
            <span className="capa__nome">Atendimento</span>
            <span className="capa__quem">
              A conversa, como o lead vê. Fale com o agente e peça uma cotação.
            </span>
          </a>

          <a className="capa__via" href={pedeCredencial ? "/entrar" : "/admin/conversas"}>
            <span className="capa__ordinal">2ª via</span>
            <span className="capa__nome">Registro</span>
            <span className="capa__quem">
              O mesmo atendimento pelo lado da operação: cada mensagem com id e
              status, as tentativas de cotação, a saúde da integração e a fila de
              handoff.
            </span>
            {pedeCredencial ? (
              <span className="capa__selo">exige credencial de operação</span>
            ) : null}
          </a>
        </div>

        <p className="capa__rodape">
          A mesma conversa aparece nas duas vias. É por isso que elas existem.
        </p>
      </div>
    </div>
  );
}
