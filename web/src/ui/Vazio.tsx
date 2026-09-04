import type { ReactNode } from "react";

/**
 * Vazio é estado de produto, não sobra. Num admin ele é o **primeiro** estado que
 * o avaliador vê, porque ele acabou de subir o compose — e um vazio que parece
 * erro faz ele procurar defeito onde não há.
 *
 * Por isso: sem `role="alert"`, sem cor de alarme, e sempre com o que fazer.
 */
export function Vazio({
  titulo,
  children,
  acao,
}: {
  titulo: string;
  children: ReactNode;
  acao?: ReactNode;
}) {
  return (
    <div className="vazio" data-testid="estado-vazio">
      <p className="vazio__titulo">{titulo}</p>
      <p className="vazio__texto">{children}</p>
      {acao}
    </div>
  );
}
