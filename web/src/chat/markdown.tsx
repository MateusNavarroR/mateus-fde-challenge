import type { ReactNode } from "react";

/**
 * Um subconjunto seguro de Markdown, renderizado como elementos React.
 *
 * O agente escreve `**Essencial**`, listas com `-` e listas numeradas — é assim que
 * ele explica os planos, e sem renderizar isso o lead lê asteriscos.
 *
 * **Por que um renderizador próprio e não uma biblioteca.** Duas razões, e a segunda
 * é a que decide:
 *
 * 1. O que o agente produz é um subconjunto pequeno e conhecido: negrito, itálico,
 *    código, listas e parágrafos. Uma biblioteca completa traria tabelas, HTML
 *    embutido, links e imagens — superfície que ninguém pediu.
 * 2. **Nada aqui passa por `dangerouslySetInnerHTML`.** O texto renderizado vem em
 *    parte do modelo e em parte do próprio lead, e os dois são conteúdo não
 *    confiável. Construir nós React em vez de HTML significa que uma tentativa de
 *    injeção sai como texto — que é exatamente o que se quer, e é o mesmo princípio
 *    que trata a mensagem do lead como dado e nunca como instrução.
 *
 * O que NÃO é suportado, de propósito: links, imagens, HTML embutido, tabelas e
 * títulos. Se o agente algum dia produzir isso, o lead vê o texto cru — que é feio,
 * e é infinitamente melhor que uma superfície de injeção numa tela pública.
 */

type Trecho = { tipo: "texto" | "negrito" | "italico" | "codigo"; valor: string };

/** `**negrito**`, `*itálico*` e `` `código` `` — o que o agente de fato usa. */
function fatiar(linha: string): Trecho[] {
  const trechos: Trecho[] = [];
  const padrao = /(\*\*[^*]+\*\*|\*[^*\n]+\*|`[^`\n]+`)/g;
  let ultimo = 0;
  for (const m of linha.matchAll(padrao)) {
    const i = m.index;
    if (i > ultimo) trechos.push({ tipo: "texto", valor: linha.slice(ultimo, i) });
    const bruto = m[0];
    if (bruto.startsWith("**")) {
      trechos.push({ tipo: "negrito", valor: bruto.slice(2, -2) });
    } else if (bruto.startsWith("`")) {
      trechos.push({ tipo: "codigo", valor: bruto.slice(1, -1) });
    } else {
      trechos.push({ tipo: "italico", valor: bruto.slice(1, -1) });
    }
    ultimo = i + bruto.length;
  }
  if (ultimo < linha.length) trechos.push({ tipo: "texto", valor: linha.slice(ultimo) });
  return trechos;
}

/**
 * Exportado para o `BlocoCotacao`: o bloco de cotação vem do template em
 * `quote/renderer.py`, que usa ênfase estilo WhatsApp (`*assim*`) porque o canal
 * imita o WhatsApp. Sem passar por aqui, o lead lia `*Completo — R$ 392,25/mês*`
 * com os asteriscos — na linha mais importante do produto.
 *
 * Reusar isto **não** viola o "este componente não formata número nenhum": `Inline`
 * converte marcador de ênfase em elemento e não toca em dígito, separador nem
 * símbolo de moeda.
 */
export function Inline({ linha }: { linha: string }): ReactNode {
  return fatiar(linha).map((t, i) => {
    if (t.tipo === "negrito") return <strong key={i}>{t.valor}</strong>;
    if (t.tipo === "italico") return <em key={i}>{t.valor}</em>;
    if (t.tipo === "codigo") return <code key={i}>{t.valor}</code>;
    return <span key={i}>{t.valor}</span>;
  });
}

const ITEM_SOLTO = /^\s*[-*•]\s+(.*)$/;
const ITEM_NUMERADO = /^\s*(\d+)[.)]\s+(.*)$/;

/**
 * Renderiza o texto da mensagem.
 *
 * Quebra em blocos: listas viram `<ul>`/`<ol>`, o resto vira parágrafos. Linhas em
 * branco separam parágrafos; quebras simples dentro de um parágrafo viram `<br>`,
 * porque o agente usa quebra simples para separar frases curtas — e colapsá-las
 * grudaria o texto de um jeito que ele não escreveu.
 */
export function Markdown({ texto }: { texto: string }): ReactNode {
  const linhas = texto.replace(/\r\n/g, "\n").split("\n");
  const blocos: ReactNode[] = [];

  let paragrafo: string[] = [];
  let lista: { ordenada: boolean; itens: string[] } | null = null;

  const fecharParagrafo = () => {
    if (paragrafo.length === 0) return;
    blocos.push(
      <p key={`p${blocos.length}`}>
        {paragrafo.map((l, i) => (
          <span key={i}>
            {i > 0 ? <br /> : null}
            <Inline linha={l} />
          </span>
        ))}
      </p>,
    );
    paragrafo = [];
  };

  const fecharLista = () => {
    if (lista === null) return;
    const itens = lista.itens.map((it, i) => (
      <li key={i}>
        <Inline linha={it} />
      </li>
    ));
    blocos.push(
      lista.ordenada ? (
        <ol key={`l${blocos.length}`}>{itens}</ol>
      ) : (
        <ul key={`l${blocos.length}`}>{itens}</ul>
      ),
    );
    lista = null;
  };

  for (const linha of linhas) {
    const solto = ITEM_SOLTO.exec(linha);
    const numerado = ITEM_NUMERADO.exec(linha);

    if (solto !== null || numerado !== null) {
      fecharParagrafo();
      const ordenada = numerado !== null;
      const item = ordenada ? numerado[2] : solto![1];
      if (lista === null || lista.ordenada !== ordenada) {
        fecharLista();
        lista = { ordenada, itens: [] };
      }
      lista.itens.push(item ?? "");
      continue;
    }

    fecharLista();
    if (linha.trim() === "") fecharParagrafo();
    else paragrafo.push(linha);
  }

  fecharLista();
  fecharParagrafo();

  return <div className="md">{blocos}</div>;
}
