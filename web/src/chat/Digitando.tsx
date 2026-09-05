/**
 * O indicador é por **turno**, não por mensagem: acende no `TypingEvent`
 * `ativo: true` e só apaga no `ativo: false`. Entre os dois podem chegar três
 * mensagens em 37 s, e ele fica aceso do começo ao fim — é o que impede o lead
 * de ver o aviso de espera seguido de 31 s de silêncio morto.
 *
 * A forma é a régua do turno continuando: um traço vertical que ainda está sendo
 * escrito, na mesma margem que sustenta a transcrição. Três bolinhas seriam a
 * citação direta de outro produto; a régua diz a mesma coisa no vocabulário
 * desta tela — enquanto ela existe, o turno não acabou.
 *
 * Não mede nada: os 6 s e os 20 s são do backend. Um relógio aqui seria a
 * política de degradação em duas cópias.
 *
 * Não usa `role="status"`: essa função está reservada ao aviso de reconexão, e
 * dois live regions competindo dizem menos que um.
 */
export function Digitando() {
  // As três bolinhas só existem DENTRO do simulador, e por CSS: aqui a marcação é
  // a mesma nos dois contextos. No console a régua continua sendo a régua do turno;
  // no simulador, que imita o mensageiro de propósito, a citação direta é o certo —
  // é o vocabulário que a pessoa reconhece sem legenda.
  //
  // O texto fica em `so-leitor` no simulador: bolinha não é lida por leitor de tela.
  return (
    <p className="digitando" data-testid="digitando">
      <span className="digitando__risco" aria-hidden="true" />
      <span className="digitando__pontos" aria-hidden="true">
        <i /><i /><i />
      </span>
      <span className="digitando__texto">ainda escrevendo</span>
    </p>
  );
}
