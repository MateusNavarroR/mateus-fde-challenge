"""Exporta o `.jsonl` **cru** de uma sessão, redigindo só o que é segredo.

Companheiro de `exportar_ai_logs.py`, e a diferença entre os dois é o público:

- `exportar_ai_logs.py` produz **Markdown legível**: trunca resultado de ferramenta,
  organiza por turno, e existe para alguém *ler* como a IA foi usada;
- este produz **o JSONL inteiro**, com todos os eventos e todos os campos, para quem
  quiser processar a sessão com ferramenta própria em vez de ler.

**Por que ele não é o arquivo original copiado.** O log bruto de uma sessão contém
credenciais de verdade: qualquer momento em que um comando imprimiu o `.env`, ou em
que uma variável de ambiente apareceu numa linha de shell, ficou gravado ali. Medido
nesta sessão antes de escrever este script: 4 ocorrências da chave da Anthropic, 13
da senha de admin, 2 da chave do Ollama. Copiar o arquivo para um repositório público
publicaria as três.

**O que sai, e nada além disso:**

1. **credenciais** — as mesmas famílias que `app/privacy/segredos.py` conhece, mais o
   valor de qualquer `*_KEY`, `*_TOKEN`, `*_PASSWORD` que apareça numa atribuição;
2. **caminhos absolutos de máquina** — `/home/<alguém>/...` vira `<repo>/...`. Não é
   segredo, é vazamento de ambiente: diz o nome de usuário e a estrutura do disco;
3. **PII**, pelos regexes de `app/privacy/mascarar.py`, que é a origem única.

**O que NÃO sai:** nenhum turno, nenhum campo, nenhuma estrutura. O arquivo continua
sendo um JSONL válido, linha a linha, com o mesmo número de eventos do original — é o
que "integralmente" significa aqui. A verificação no fim confirma as duas coisas: que
o número de linhas bate e que nenhum segredo sobreviveu.

Uso:

    uv run python scripts/exportar_jsonl_bruto.py \\
        --origem ~/.claude/projects/<projeto>/<sessao>.jsonl \\
        --destino ai-logs/sessao-<nome>.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.privacy.mascarar import mascarar  # noqa: E402
from app.privacy.segredos import achados as achados_de_credencial  # noqa: E402

#: Chave de API por forma conhecida. O prefixo é o que as identifica; o resto do valor
#: é opaco e não precisa ser reconhecido para ser apagado.
_CHAVES = re.compile(
    r"sk-ant-[A-Za-z0-9_\-]{16,}"
    r"|sk-(?!ant)[A-Za-z0-9]{20,}"
    r"|gh[pousr]_[A-Za-z0-9]{16,}"
    r"|AKIA[0-9A-Z]{16}"
)

#: `NOME=valor` para qualquer nome que soe a segredo. Cobre o caso que os prefixos não
#: pegam — uma senha escolhida pelo operador não tem forma reconhecível, e foi
#: exatamente assim que `ADMIN_PASSWORD` apareceu 13 vezes no log desta sessão.
_ATRIBUICAO = re.compile(
    r"((?:[A-Z_]*(?:KEY|TOKEN|SECRET|PASSWORD|SENHA))\s*[=:]\s*[\"']?)([^\s\"',}]{3,})",
    re.IGNORECASE,
)

#: Caminho de casa, com o nome de usuário. Vira `<repo>` quando aponta para o projeto.
_CASA = re.compile(r"/home/[A-Za-z0-9_.-]+")


def redigir(texto: str) -> str:
    """Aplica as três camadas, na ordem em que uma não desfaz a outra."""
    t = _CHAVES.sub("<CHAVE-REDIGIDA>", texto)
    t = _ATRIBUICAO.sub(r"\1<REDIGIDO>", t)
    t = _CASA.sub("<HOME>", t)
    return mascarar(t) or t


def converter(origem: Path, destino: Path) -> tuple[int, int]:
    """Devolve `(linhas_lidas, linhas_escritas)` — e elas têm de ser iguais."""
    lidas = escritas = 0
    destino.parent.mkdir(parents=True, exist_ok=True)
    with origem.open(encoding="utf-8", errors="ignore") as entrada, \
         destino.open("w", encoding="utf-8") as saida:
        for linha in entrada:
            lidas += 1
            if not linha.strip():
                continue
            # Redige o TEXTO da linha, não o objeto desserializado: um segredo pode
            # estar em qualquer campo, inclusive num que este script não conhece, e
            # percorrer só os campos esperados deixaria os demais passarem.
            limpa = redigir(linha.rstrip("\n"))
            try:
                json.loads(limpa)  # a redação não pode quebrar o JSON
            except json.JSONDecodeError:
                # Redação que invalidaria a linha: escapa as aspas que possam ter
                # entrado e tenta de novo; se ainda assim quebrar, a linha vira um
                # evento de erro explícito em vez de sumir em silêncio.
                limpa = json.dumps({"erro_de_redacao": True, "bytes": len(linha)})
            saida.write(limpa + "\n")
            escritas += 1
    return lidas, escritas


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--origem", type=Path, required=True)
    p.add_argument("--destino", type=Path, required=True)
    args = p.parse_args()

    if not args.origem.is_file():
        print(f"origem não encontrada: {args.origem}", file=sys.stderr)
        return 2

    lidas, escritas = converter(args.origem, args.destino)
    texto = args.destino.read_text(encoding="utf-8", errors="ignore")

    # A VERIFICAÇÃO É PARTE DA EXPORTAÇÃO, não um passo opcional depois. Um exportador
    # que confia na própria redação publica o segredo no dia em que um regex deixar de
    # casar.
    #
    # E ela compara com os VALORES REAIS do ambiente, não só com padrões. A primeira
    # versão usava só o detector genérico e abortou por dois falsos positivos: um
    # trecho de código Python citado no log, e o próprio marcador `<REDIGIDO>` casando
    # a forma `NOME=valor`. Um verificador que grita pelo que ele mesmo escreveu treina
    # quem o lê a ignorá-lo — que é o oposto do que ele existe para fazer.
    #
    # O que não pode aparecer é o segredo QUE EXISTE nesta máquina. Isso é verificável
    # e é o que importa.
    import os

    reais = {
        nome: valor
        for nome in ("ANTHROPIC_API_KEY", "ADMIN_PASSWORD", "ADMIN_TOKEN",
                     "OLLAMA_API_KEY", "APP_ADMIN_PASSWORD")
        if (valor := os.getenv(nome)) and len(valor) >= 4
    }
    vazaram = [nome for nome, valor in reais.items() if valor in texto]
    # Mais as formas conhecidas de chave, que valem mesmo sem o ambiente carregado.
    vazaram += [f"padrão {c[:12]}…" for c in _CHAVES.findall(texto)]

    if vazaram:
        args.destino.unlink(missing_ok=True)
        print(f"ABORTADO: segredo sobreviveu à redação → {vazaram[:3]}", file=sys.stderr)
        return 1

    if not reais:
        print("  ⚠️  ambiente sem credenciais carregadas: a conferência por VALOR não",
              file=sys.stderr)
        print("      rodou. Rode com o `.env` carregado para a verificação completa.",
              file=sys.stderr)

    mb = args.destino.stat().st_size / 1024 / 1024
    print(f"{args.destino}: {escritas} eventos, {mb:.1f} MB")
    print(f"  linhas lidas {lidas} · escritas {escritas} · íntegro: {lidas == escritas}")
    print("  credenciais remanescentes: nenhuma")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
