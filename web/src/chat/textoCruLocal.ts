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
  /*
   * MAPA VAZIO NÃO GRAVA, e esta linha é o conserto de um bug real.
   *
   * O `id` da conversa chega DEPOIS da montagem — a `PaginaChat` o resolve num
   * `await` — e, no render em que ele chega, o estado do reducer ainda é o vazio: o
   * efeito de troca de conversa só dispara o `dispatch`, e o reducer, que é quem lê
   * este armazenamento, roda depois de todos os efeitos daquele commit. O efeito de
   * persistência então gravava `{}` por cima do que estava guardado, e o reducer lia
   * o mapa recém-apagado. Na tela: depois de um F5, o lead voltava a ver `[CEP]` na
   * própria bolha — exatamente o que este módulo existe para evitar.
   *
   * Gravar vazio nunca é necessário: cada conversa tem a sua chave, e "Nova conversa"
   * troca o `id`. Não existe estado vazio que precise ser lembrado — só
   * `esquecerCru` apaga, e ele é explícito.
   */
  if (Object.keys(mapa).length === 0) return;
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
