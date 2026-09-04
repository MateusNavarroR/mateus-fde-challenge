import { Markdown } from "./markdown";
import type { Mensagem } from "./useConversa";

/**
 * `sistema` e `agente` são **visualmente idênticos** para o lead — mesma classe,
 * sem rótulo que denuncie a origem. A distinção é auditoria, não produto: para
 * quem está do outro lado, é a mesma empresa falando. Ela existe e é visível no
 * admin, onde é informação.
 *
 * O conteúdo passa pelo renderizador de Markdown: o agente escreve `**negrito**` e
 * listas, e sem isso o lead lê asteriscos. É um subconjunto próprio e sem
 * `dangerouslySetInnerHTML` — o texto vem em parte do modelo e em parte do lead, e
 * os dois são conteúdo não confiável.
 */
export function Bolha({ mensagem }: { mensagem: Mensagem }) {
  const doLead = mensagem.autor === "lead";
  const classe = [
    "bolha",
    doLead ? "bolha--lead" : "bolha--empresa",
    mensagem.pendente ? "bolha--pendente" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={classe} data-testid={`bolha-${mensagem.id}`}>
      <Markdown texto={mensagem.conteudo} />
      {mensagem.suspeitaDeBug ? (
        <span className="marca-bug" data-testid="marca-bug">
          valor sem cotação vinculada
        </span>
      ) : null}
    </div>
  );
}
