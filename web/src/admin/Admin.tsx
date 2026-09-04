import { LayoutAdmin } from "./LayoutAdmin";
import { DetalheConversa } from "./DetalheConversa";
import { PaginaConversas } from "./PaginaConversas";
import { PaginaHandoffs } from "./PaginaHandoffs";
import { PaginaStatus } from "./PaginaStatus";

const DETALHE = /^\/admin\/conversas\/([^/?#]+)/;

/** As três telas sobre o layout comum, escolhidas pela rota. */
export function Admin({ rota }: { rota: string }) {
  const detalhe = DETALHE.exec(rota);

  return (
    <LayoutAdmin rota={rota}>
      {detalhe ? (
        <DetalheConversa id={decodeURIComponent(detalhe[1] ?? "")} />
      ) : rota.startsWith("/admin/status") ? (
        <PaginaStatus />
      ) : rota.startsWith("/admin/handoffs") ? (
        <PaginaHandoffs />
      ) : (
        <PaginaConversas />
      )}
    </LayoutAdmin>
  );
}
