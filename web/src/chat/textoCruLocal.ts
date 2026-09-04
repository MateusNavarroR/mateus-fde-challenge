/**
 * O texto que o lead digitou, guardado **só na sessão do navegador dele**.
 *
 * O PROBLEMA. O mascaramento acontece na gravação, então não existe versão crua em
 * lugar nenhum do servidor — nem no banco, nem no log, nem para o operador. Isso é
 * deliberado e é a garantia mais forte do projeto: não é uma regra que alguém precisa
 * lembrar de aplicar, é uma ausência.
 *
 * O efeito colateral era feio: o lead digitava o CPF e via `[CPF]` na própria bolha.
 * Ele sabe o que escreveu, e a mensagem alterada parece defeito.
 *
 * A SAÍDA que não enfraquece nada: o navegador dele lembra o que ele digitou, e só
 * ele. Três propriedades, e as três importam:
 *
 * 1. **`sessionStorage`, não `localStorage`.** Morre quando a aba fecha. Um CPF que
 *    sobrevive a um reboot num computador compartilhado é um problema novo criado
 *    para resolver um problema de aparência.
 * 2. **Nunca sai do navegador.** Nada aqui é enviado, sincronizado ou lido pelo
 *    servidor. O invariante do backend fica intacto: ele continua sem nunca ter a
 *    versão crua persistida.
 * 3. **Só a fala do lead.** O texto do agente e do sistema vem do servidor, já
 *    mascarado, e não tem versão local — se tivesse, seria uma segunda fonte da
 *    verdade para o que a empresa disse.
 *
 * Quando o `sessionStorage` não está disponível (aba anônima com storage bloqueado,
 * navegador travado), tudo degrada para o comportamento anterior: o lead vê a versão
 * mascarada. Feio, e correto.
 */

const PREFIXO = "autoseguro:cru:";

function chave(conversationId: string): string {
  return `${PREFIXO}${conversationId}`;
}

export function lerCru(conversationId: string): Record<string, string> {
  try {
    const bruto = sessionStorage.getItem(chave(conversationId));
    if (bruto === null) return {};
    const lido: unknown = JSON.parse(bruto);
    return typeof lido === "object" && lido !== null ? (lido as Record<string, string>) : {};
  } catch {
    return {};
  }
}

export function gravarCru(conversationId: string, mapa: Record<string, string>): void {
  try {
    sessionStorage.setItem(chave(conversationId), JSON.stringify(mapa));
  } catch {
    /* storage bloqueado: degrada para a versão mascarada */
  }
}

export function esquecerCru(conversationId: string): void {
  try {
    sessionStorage.removeItem(chave(conversationId));
  } catch {
    /* idem */
  }
}
