import type { Mensagem } from "./useConversa";

/**
 * **Este componente não formata número nenhum.**
 *
 * O bloco chega pronto do `quote/renderer.py`, que é a origem única do texto com
 * valor monetário. Formatar moeda aqui abriria uma segunda origem de preço — e o
 * invariante é que o preço nunca vem de outro lugar que não a `/quote`.
 *
 * A tela faz só duas coisas: preserva as quebras de linha e destaca a linha da
 * carência, que já vem marcada do template. A carência é a ressalva que gera
 * reclamação depois se passar batida, então ela tem tratamento próprio.
 */
export function BlocoCotacao({ mensagem }: { mensagem: Mensagem }) {
  const linhas = mensagem.conteudo.split("\n");

  return (
    <div
      className="cotacao"
      data-testid="bloco-cotacao"
      data-quote-id={mensagem.quote_id ?? ""}
    >
      {linhas.map((linha, i) => {
        const vazia = linha.trim() === "";
        const carencia = linha.includes("⚠️");
        const classe = vazia
          ? "cotacao__linha cotacao__linha--vazia"
          : carencia
            ? "cotacao__linha cotacao__linha--carencia"
            : "cotacao__linha";
        return (
          // A ordem das linhas é fixa e vem do template: o índice é a identidade.
          <p key={`${mensagem.id}-${i}`} className={classe}>
            {linha}
          </p>
        );
      })}
      <div className="cotacao__rodape">
        <span className="rotulo">cotação {mensagem.quote_id}</span>
      </div>
    </div>
  );
}
