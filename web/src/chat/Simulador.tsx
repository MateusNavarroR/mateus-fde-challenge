import { PaginaChat } from "./PaginaChat";

/**
 * O Chat Simulado, e o rótulo aqui é **produto, não decoração**.
 *
 * Esta tela imita a moldura de uma conversa de WhatsApp porque é assim que o lead
 * conversaria de verdade — mas não há WhatsApp nenhum atrás dela: não há Cloud API,
 * webhook, número nem QR. É um banco de provas para exercitar as respostas do agente.
 *
 * **Por que isso precisa estar escrito na tela, e não só no README.** Um avaliador que
 * abre uma interface parecida com WhatsApp e não é avisado tem duas leituras
 * possíveis, e as duas são ruins: ou acha que existe uma integração real — e o
 * repositório declara que não existe, então a interface estaria mentindo — ou
 * desconfia que existe e ninguém disse, o que é pior. O aviso remove a ambiguidade
 * antes que ela nasça.
 *
 * O carimbo é o mesmo gesto do resto da aplicação: papel de formulário, tinta óxido,
 * rotação de despachante com pressa. Ele é `aria-hidden` porque o texto que importa
 * está no aviso ao lado, legível por leitor de tela e sem depender de ver a rotação.
 */
export function Simulador() {
  return (
    <div className="simulador">
      <header className="simulador__cabeca">
        <div className="simulador__dizeres">
          <h1 className="folha__titulo">Chat simulado</h1>
          <p className="folha__linha">
            <strong>Ambiente de teste.</strong> Esta tela imita a moldura de uma
            conversa de WhatsApp para você exercitar as respostas do agente — mas{" "}
            <strong>não há WhatsApp atrás dela</strong>: sem Cloud API, sem webhook, sem
            número e sem QR. É uma decisão de escopo declarada no README, não uma
            integração pendente.
          </p>
          <p className="folha__linha">
            Tudo o que você escrever aqui percorre o caminho de produção inteiro e
            aparece no <a href="/historico">Histórico</a>, com id e status por mensagem.
          </p>
        </div>
        <span className="carimbo" aria-hidden="true">
          <span className="carimbo__linha1">simulação</span>
          <span className="carimbo__linha2">ambiente de teste</span>
        </span>
      </header>

      <PaginaChat />
    </div>
  );
}
