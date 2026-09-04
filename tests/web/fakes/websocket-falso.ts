/**
 * Um WebSocket controlado pelo teste.
 *
 * A janela do turno degradado é de 37 s. Exercitá-la com um servidor de verdade
 * significaria uma suíte que dorme 37 s — e uma suíte que dorme 37 s ninguém
 * roda. Aqui o teste decide quando cada frame chega.
 */
export class WebSocketFalso {
  static ultima: WebSocketFalso | null = null;
  static criadas = 0;
  static todas: WebSocketFalso[] = [];

  static reiniciar(): void {
    WebSocketFalso.ultima = null;
    WebSocketFalso.criadas = 0;
    WebSocketFalso.todas = [];
  }

  readonly url: string;
  readyState = 0;
  enviados: string[] = [];
  fechada = false;

  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: unknown }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
    WebSocketFalso.criadas += 1;
    WebSocketFalso.ultima = this;
    WebSocketFalso.todas.push(this);
  }

  send(dado: string): void {
    this.enviados.push(dado);
  }

  /** Fechamento pedido pelo cliente: não dispara `onclose`, e não reconecta. */
  close(): void {
    this.fechada = true;
    this.readyState = 3;
  }

  // --- controles do teste --------------------------------------------------

  abrir(): void {
    this.readyState = 1;
    this.onopen?.();
  }

  receber(quadro: unknown): void {
    this.onmessage?.({ data: JSON.stringify(quadro) });
  }

  /** Queda do lado do servidor: dispara a reconexão do cliente. */
  cair(): void {
    this.readyState = 3;
    this.fechada = true;
    this.onclose?.();
  }
}
