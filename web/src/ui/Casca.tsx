import type { ReactNode } from "react";

/**
 * A casca comum às duas áreas.
 *
 * O PROBLEMA que ela resolve não é estético: a aplicação tem **dois públicos** —
 * o lead, em `/chat`, e o operador, em `/admin` — e a interface tratava isso como
 * um app só com abas. Quem entrava numa área não sabia que a outra existia, e o
 * cabeçalho do admin empilhava cinco coisas de naturezas diferentes numa fileira.
 *
 * A METÁFORA vem do próprio vernáculo do domínio, e não de uma convenção de
 * dashboard: um documento de seguro tem **vias**. A 1ª via é do cliente, a 2ª
 * fica no arquivo. É exatamente a distinção de dois públicos olhando o mesmo
 * papel — e por ser nativa do assunto, ela se explica sozinha.
 *
 * QUATRO NATUREZAS, QUATRO TRATAMENTOS. Era essa a confusão:
 *
 *   1. `timbre`      identidade do sistema — canto, discreto, voz de documento
 *   2. `vias`        navegação entre ÁREAS — o elemento mais forte da casca;
 *                    a via inativa fica lavada, como cópia carbono
 *   3. `separadores` navegação entre SEÇÕES — abas de pasta, só no admin, em
 *                    linha própria, e a ativa **se conecta à folha** (sem filete
 *                    inferior), que é o que a torna óbvia ao olho e não só ao
 *                    `aria-current`
 *   4. `estado`      operação — badge e conexão, à direita, em Courier
 *
 * As duas navegações usam linguagens visuais **diferentes de propósito**: se
 * "ir para o admin" e "ir para status" parecerem a mesma coisa, o leitor não tem
 * como saber que uma troca de contexto e a outra não.
 */

export type Via = "chat" | "admin";

const VIAS = [
  { id: "chat" as const, href: "/chat", ordinal: "1ª", nome: "Atendimento", quem: "o cliente" },
  { id: "admin" as const, href: "/admin/conversas", ordinal: "2ª", nome: "Registro", quem: "a operação" },
];

export function Casca({
  via,
  separadores,
  estado,
  children,
}: {
  via: Via;
  /** Abas de seção. Só o admin tem; o chat passa `undefined` e a linha some. */
  separadores?: ReactNode;
  /** Badge de pendentes e pílula de conexão. Zona própria, nunca junto das abas. */
  estado?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="casca" data-via={via}>
      <header className="casca__cabecalho">
        <div className="casca__timbre">
          <span className="casca__marca">AutoSeguro</span>
          <span className="casca__formulario">seguro auto · proposta</span>
        </div>

        <nav className="casca__vias" aria-label="Áreas">
          {VIAS.map((v) => {
            const atual = v.id === via;
            return (
              <a
                key={v.id}
                className="via"
                href={v.href}
                aria-current={atual ? "true" : undefined}
                data-atual={atual ? "sim" : "nao"}
              >
                <span className="via__ordinal">{v.ordinal} via</span>
                <span className="via__nome">{v.nome}</span>
                <span className="so-leitor"> — para {v.quem}</span>
              </a>
            );
          })}
        </nav>

        {estado !== undefined ? <div className="casca__estado">{estado}</div> : null}
      </header>

      {separadores !== undefined ? (
        <div className="casca__separadores">{separadores}</div>
      ) : null}

      <div className="casca__folha">{children}</div>
    </div>
  );
}
