/**
 * Formatação de exibição. **Nenhum valor monetário de cotação passa por aqui** —
 * o bloco da cotação chega pronto do renderer, e formatar preço no front abriria
 * uma segunda origem.
 */

/**
 * O `??` proibido escrito em código.
 *
 * `cache_read` nulo é **"n/a", nunca "0 %"** (CLAUDE.md 26, migração 0002). Um
 * zero ali diria "o cache não acertou" onde a verdade é "não existe cache neste
 * caminho" — o Ollama não popula o campo. `formatarOuNa(v, f)` é a única porta:
 * devolve "n/a" para `null | undefined` e formata o resto.
 */
export const NA = "n/a";

export function formatarOuNa<T>(
  valor: T | null | undefined,
  formatador: (v: T) => string,
): string {
  if (valor === null || valor === undefined) return NA;
  return formatador(valor);
}

export const inteiro = (n: number): string => n.toLocaleString("pt-BR");

export const percentual = (v: number): string =>
  `${(v * 100).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} %`;

/** Custo em dólar da nossa própria base, já calculado pelo backend. */
export const dolar = (v: number): string =>
  `US$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 4, maximumFractionDigits: 4 })}`;

/** Milissegundos legíveis: abaixo de 1 s em ms, acima em segundos. */
export const duracao = (ms: number): string =>
  ms < 1000
    ? `${ms.toLocaleString("pt-BR")} ms`
    : `${(ms / 1000).toLocaleString("pt-BR", {
        minimumFractionDigits: 1,
        maximumFractionDigits: 1,
      })} s`;

export function instante(iso: string | null | undefined): string {
  if (!iso) return NA;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "medium" });
}

export function hora(iso: string | null | undefined): string {
  if (!iso) return NA;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString("pt-BR", { hour12: false });
}

/**
 * O CEP aparece no admin **mascarado**: o perfil serve para mostrar progresso da
 * qualificação, e o prefixo é o que importa ali.
 */
export function cepMascarado(cep: string | null | undefined): string {
  if (!cep) return NA;
  const digitos = cep.replace(/\D/g, "");
  if (digitos.length < 5) return "•••••-•••";
  return `${digitos.slice(0, 2)}•••-•••`;
}
