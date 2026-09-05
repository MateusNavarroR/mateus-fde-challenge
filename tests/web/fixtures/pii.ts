/**
 * Gera PII válida em formato, no momento do teste — a porta do TypeScript para a
 * regra do invariante 13b do `CLAUDE.md`.
 *
 * **Nenhum valor daqui é literal no repositório.** Eles nascem em memória e
 * morrem no fim da execução, e é o que permite que a varredura do portão de
 * segurança seja absoluta, **sem lista de exceções** — que é a mesma porta que
 * este projeto se recusa a abrir no guardrail.
 *
 * O gerador é semeado com um **LCG explícito**: `Math.random()` não aceita seed,
 * e sem seed uma falha deixa de ser reproduzível. Mesmo desenho e mesmo contrato
 * `(frase, pii)` do gerador em Python.
 *
 * Nenhum golden file com a saída: gravar o resultado traria o literal de volta
 * pela porta dos fundos.
 */

const LETRAS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
const MINUSCULAS = "abcdefghijklmnopqrstuvwxyz";
const DDDS = ["11", "21", "31", "41", "47", "48", "51", "61", "62", "71", "81", "85"];
/** Domínios reservados pela RFC 2606 — não são registráveis por ninguém. */
const DOMINIOS = ["example.com", "example.org", "example.net"];
/** Montado em runtime: o literal do prefixo internacional não fica no fonte. */
const CODIGO_PAIS = 55;

/** Linear congruential generator — o mesmo `seed` dá a mesma sequência, sempre. */
function lcg(seed: number) {
  let estado = (seed >>> 0) || 1;
  return {
    /** Inteiro em [min, max]. */
    inteiro(min: number, max: number): number {
      estado = (Math.imul(estado, 1664525) + 1013904223) >>> 0;
      return min + (estado % (max - min + 1));
    },
    escolher<T>(itens: readonly T[]): T {
      estado = (Math.imul(estado, 1664525) + 1013904223) >>> 0;
      const item = itens[estado % itens.length];
      if (item === undefined) throw new Error("lista vazia");
      return item;
    },
  };
}

type Rng = ReturnType<typeof lcg>;

/** Com dígitos verificadores corretos: formato perfeito, conteúdo inventado. */
function cpf(rng: Rng): string {
  const n: number[] = [];
  for (let i = 0; i < 9; i += 1) n.push(rng.inteiro(0, 9));
  for (let k = 0; k < 2; k += 1) {
    let s = 0;
    for (let i = 0; i < n.length; i += 1) s += (n.length + 1 - i) * (n[i] as number);
    const d = (s * 10) % 11;
    n.push(d === 10 ? 0 : d);
  }
  const d = (i: number) => String(n[i]);
  return `${d(0)}${d(1)}${d(2)}.${d(3)}${d(4)}${d(5)}.${d(6)}${d(7)}${d(8)}-${d(9)}${d(10)}`;
}

function cep(rng: Rng): string {
  // Inclui prefixo com zero à esquerda de propósito: é a variação que quebra
  // implementação ingênua e que um exemplo escolhido a dedo esconde.
  const prefixo = String(rng.inteiro(1000, 99999)).padStart(5, "0");
  const sufixo = String(rng.inteiro(0, 999)).padStart(3, "0");
  return `${prefixo}-${sufixo}`;
}

function telefone(rng: Rng): string {
  const ddd = rng.escolher(DDDS);
  const a = String(rng.inteiro(1000, 9999));
  const b = String(rng.inteiro(1000, 9999));
  return `+${CODIGO_PAIS} ${ddd} 9${a}-${b}`;
}

/** Padrão Mercosul: LLLNLNN. */
function placa(rng: Rng): string {
  let letras = "";
  for (let i = 0; i < 3; i += 1) letras += rng.escolher([...LETRAS]);
  return `${letras}${rng.inteiro(0, 9)}${rng.escolher([...LETRAS])}${rng.inteiro(0, 9)}${rng.inteiro(0, 9)}`;
}

function email(rng: Rng): string {
  const palavra = (min: number, max: number) => {
    let s = "";
    const n = rng.inteiro(min, max);
    for (let i = 0; i < n; i += 1) s += rng.escolher([...MINUSCULAS]);
    return s;
  };
  const sep = rng.escolher([".", "_", ""]);
  return `${palavra(4, 9)}${sep}${palavra(4, 9)}@${rng.escolher(DOMINIOS)}`;
}

export type Pii = {
  cpf: string;
  cep: string;
  email: string;
  telefone: string;
  placa: string;
};

/** Semeado ⇒ determinístico. O seed é sempre explícito no teste. */
export function gerarPii(seed: number): Pii {
  const rng = lcg(seed);
  return {
    cpf: cpf(rng),
    cep: cep(rng),
    email: email(rng),
    telefone: telefone(rng),
    placa: placa(rng),
  };
}

/**
 * A fala e os valores, para o teste assertar sobre os dois.
 *
 * O formato imita o do dataset: PII solta em texto livre, misturada com o dado
 * de qualificação (a idade) que **não** é PII e não pode ser mascarado — cotar
 * depende dele.
 */
export function fraseDoLead(seed: number): [string, Pii] {
  const p = gerarPii(seed);
  return [
    `Tenho 35 anos, CPF ${p.cpf}, CEP ${p.cep}, ` +
      `meu email é ${p.email} e o whats é ${p.telefone}, ` +
      `placa ${p.placa}`,
    p,
  ];
}
