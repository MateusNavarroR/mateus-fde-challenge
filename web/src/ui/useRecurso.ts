import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Leitura de um endpoint com os três estados que importam: carregando, erro e
 * dado. Não existe um quarto — "vazio" é uma decisão de cada tela sobre o dado,
 * e confundir vazio com erro é o defeito que a fatia 8 mais persegue.
 */
export function useRecurso<T>(
  carregar: () => Promise<T>,
  deps: readonly unknown[] = [],
): {
  dado: T | null;
  erro: unknown;
  carregando: boolean;
  recarregar: () => void;
} {
  const [dado, setDado] = useState<T | null>(null);
  const [erro, setErro] = useState<unknown>(null);
  const [carregando, setCarregando] = useState(true);
  const [gatilho, setGatilho] = useState(0);
  const fn = useRef(carregar);
  fn.current = carregar;

  /*
   * A guarda contra `setState` depois do desmonte é o `cancelado` local desta
   * execução, e só ele. Sob StrictMode o React monta, desmonta e remonta, então
   * um segundo sinalizador em ref só acrescentaria um ciclo de vida para errar.
   */
  useEffect(() => {
    let cancelado = false;
    setCarregando(true);
    fn.current()
      .then((r) => {
        if (cancelado) return;
        setDado(r);
        setErro(null);
      })
      .catch((e: unknown) => {
        if (cancelado) return;
        setErro(e);
      })
      .finally(() => {
        if (cancelado) return;
        setCarregando(false);
      });
    return () => {
      cancelado = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gatilho, ...deps]);

  const recarregar = useCallback(() => setGatilho((g) => g + 1), []);
  return { dado, erro, carregando, recarregar };
}
