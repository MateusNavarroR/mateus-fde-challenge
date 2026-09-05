import { Inline } from "./markdown";
import type { Mensagem } from "./useConversa";

/**
 * **Este componente não formata número nenhum.**
 *
 * O bloco chega pronto do `quote/renderer.py`, que é a origem única do texto com
 * valor monetário. Formatar moeda aqui abriria uma segunda origem de preço — e o
 * invariante é que o preço nunca vem de outro lugar que não a `/quote`.
 *
 * A tela faz três coisas: preserva as quebras de linha, destaca a linha da carência
 * — que já vem marcada do template, e é a ressalva que gera reclamação depois se
 * passar batida — e converte os marcadores de ênfase do template.
 *
 * A ênfase é estilo WhatsApp (`*assim*`), porque o canal imita o WhatsApp. Antes de
 * passar pelo `Inline`, o lead lia `*Completo — R$ 392,25/mês*` com os asteriscos, na
 * primeira linha do bloco. `Inline` converte marcador em elemento e não toca em
 * dígito nem em moeda, então a regra acima continua valendo.
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
            <Inline linha={linha} />
          </p>
        );
      })}
      <div className="cotacao__rodape">
        <span className="rotulo">cotação {mensagem.quote_id}</span>
      </div>
    </div>
  );
}
