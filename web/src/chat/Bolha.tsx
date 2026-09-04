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
 *
 * Uma mensagem de mídia mostra o NOME DO ARQUIVO com um rótulo de anexo. Sem o
 * rótulo, "foto-do-carro.jpg" aparece exatamente como se o lead tivesse digitado
 * essa string — e é o que o operador leria no transcript também. O arquivo em si
 * não é guardado: o produto registra que chegou mídia, não a mídia.
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

  const anexo = mensagem.tipo !== "text";
  // A frase inteira, e não só o substantivo com um sufixo colado: "imagem" é
  // feminino e "áudio" é masculino, e `${rotulo} anexado` produziria "imagem
  // anexado" na tela do lead.
  const ROTULO: Record<string, string> = {
    image: "imagem anexada",
    audio: "áudio anexado",
    document: "documento anexado",
  };

  return (
    <div className={classe} data-testid={`bolha-${mensagem.id}`}>
      {anexo ? (
        <span className="bolha__anexo" data-testid="marca-anexo">
          {ROTULO[mensagem.tipo] ?? "arquivo anexado"}
        </span>
      ) : null}
      <Markdown texto={mensagem.conteudo} />
      {mensagem.suspeitaDeBug ? (
        <span className="marca-bug" data-testid="marca-bug">
          valor sem cotação vinculada
        </span>
      ) : null}
    </div>
  );
}
