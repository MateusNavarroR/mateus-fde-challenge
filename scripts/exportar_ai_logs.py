"""Exporta as sessões de IA para `ai-logs/`, **redigindo antes de escrever**.

Entregável nº 5 do enunciado. É o maior volume de texto do repositório e o que menos
passou por revisão humana — e o que mais tem chance de carregar algo que não devia.

**A redação acontece na escrita, não depois.** O arquivo nunca chega ao disco com o
segredo dentro: escrever primeiro e limpar depois deixaria a versão crua no `git add`
de alguém apressado, e o histórico não desfaz.

O que sai:

- **chave de API** — a `ANTHROPIC_API_KEY` aparece no log bruto porque um resultado de
  ferramenta imprimiu o `.env` durante a sessão. É o achado que motivou este script;
- **caminho absoluto de máquina** — `/home/<alguém>/...` vira `<repo>/...`. Não é
  segredo, é vazamento de ambiente: diz o nome de usuário e a estrutura do disco;
- **PII**, pelos mesmos regexes de `app/privacy/mascarar.py`, que é a origem única.

O que **não** sai, de propósito: as falas. O valor deste artefato para o critério "como
a IA foi usada" está justamente no que foi pedido, no que deu errado e em como foi
corrigido — resumir isso seria entregar a versão editada de mim mesmo.

**Resultados de ferramenta são truncados**, e é o que torna o volume razoável: 15 MB de
`jsonl` são majoritariamente saída de comando, que é ruído para quem lê. O corte é
declarado no arquivo, com o tamanho original.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.privacy.mascarar import mascarar  # noqa: E402
from app.privacy.segredos import achados as achados_de_credencial  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent

#: Segredos por FORMA, não por valor: uma lista de valores conhecidos falharia no
#: primeiro segredo novo, e é justamente o novo que ninguém revisou.
SEGREDOS = (
    # Qualquer comprimento: o corte de resultado de ferramenta pode partir a chave ao
    # meio, e o que sobra (`sk-ant-api03-`) é só o prefixo público — mas repositório
    # público não carrega nem fragmento com cara de chave.
    (re.compile(r"sk-ant[A-Za-z0-9_\-]*"), "[ANTHROPIC_API_KEY]"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"), "[API_KEY]"),
    (re.compile(r"sk-[A-Za-z0-9]{32,}"), "[API_KEY]"),
    (re.compile(r"ghp_[A-Za-z0-9]{36}"), "[GITHUB_TOKEN]"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[AWS_KEY]"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
                re.S), "[PRIVATE_KEY]"),
    # Bearer/Authorization soltos, que aparecem em exemplo de curl.
    (re.compile(r"(?i)(authorization:\s*bearer\s+)[A-Za-z0-9._\-]{16,}"),
     r"\1[REDIGIDO]"),
    # Nome de segredo com valor citado, em qualquer forma: `senha="..."`,
    # `{"api_key": "..."}`. É a forma que nasce de "só para testar" e fica.
    (re.compile(r'(?i)\b(admin_password|password|passwd|senha|secret_key|'
                r'client_secret|secret|admin_token|access_token|api_key|apikey)'
                r'(["\']?\s*[:=]\s*)(["\'])[^"\'\n]{6,}\3'),
     r"\1\2\3[REDIGIDO]\3"),
    # Linha de ambiente com valor: `ADMIN_PASSWORD=...`.
    (re.compile(r"\b([A-Z_]*(?:PASSWORD|PASSWD|SENHA|SECRET|TOKEN|API_KEY|APIKEY)"
                r"[A-Z_]*[ \t]*=[ \t]*)[^\s\"'#\n\\]{6,}"),
     r"\1[REDIGIDO]"),
)

#: `/home/alguem/...` e `/Users/alguem/...` → `<repo>/...`. Diz o nome de usuário do
#: dono da máquina e a estrutura do disco: não é segredo, é vazamento de ambiente.
CAMINHOS = (
    (re.compile(re.escape(str(RAIZ))), "<repo>"),
    (re.compile(r"/home/[A-Za-z0-9_.-]+"), "/home/<usuario>"),
    (re.compile(r"/Users/[A-Za-z0-9_.-]+"), "/Users/<usuario>"),
)

#: Acima disto, um resultado de ferramenta vira ruído para quem lê.
CORTE_FERRAMENTA = 1200


def redigir(texto: str) -> str:
    """Segredo → caminho → PII, nesta ordem.

    A ordem importa: mascarar PII primeiro poderia partir uma chave ao meio e fazer o
    regex de segredo deixar de casar com o que sobrou.
    """
    for padrao, marca in SEGREDOS:
        texto = padrao.sub(marca, texto)
    for padrao, marca in CAMINHOS:
        texto = padrao.sub(marca, texto)
    return mascarar(texto)


def _texto_do_conteudo(conteudo) -> list[str]:
    """Um evento do `jsonl` tem `content` em três formas. As três viram texto."""
    if isinstance(conteudo, str):
        return [conteudo]
    if not isinstance(conteudo, list):
        return []
    saida = []
    for bloco in conteudo:
        if not isinstance(bloco, dict):
            continue
        tipo = bloco.get("type")
        if tipo == "text":
            saida.append(bloco.get("text", ""))
        elif tipo == "thinking":
            continue  # raciocínio interno não é parte do registro entregue
        elif tipo == "tool_use":
            nome = bloco.get("name", "?")
            entrada = json.dumps(bloco.get("input", {}), ensure_ascii=False)
            saida.append(f"→ **{nome}**  `{_cortar(entrada, 300)}`")
        elif tipo == "tool_result":
            bruto = bloco.get("content")
            if isinstance(bruto, list):
                bruto = " ".join(
                    b.get("text", "") for b in bruto if isinstance(b, dict)
                )
            saida.append(f"```\n{_cortar(str(bruto), CORTE_FERRAMENTA)}\n```")
    return [s for s in saida if s.strip()]


def _cortar(texto: str, n: int) -> str:
    if len(texto) <= n:
        return texto
    return f"{texto[:n]}\n… [+{len(texto) - n} caracteres]"


def converter(caminho: Path) -> tuple[str, int, int]:
    """Devolve `(markdown, turnos, bytes_originais)`."""
    linhas: list[str] = []
    turnos = 0
    for bruta in caminho.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            ev = json.loads(bruta)
        except json.JSONDecodeError:
            continue
        papel = ev.get("type")
        if papel not in ("user", "assistant"):
            continue
        msg = ev.get("message") or {}
        partes = _texto_do_conteudo(msg.get("content"))
        if not partes:
            continue
        turnos += 1
        rotulo = "Mateus" if papel == "user" else "Claude"
        linhas.append(f"\n### {rotulo}\n")
        linhas.extend(partes)
    return "\n".join(linhas), turnos, caminho.stat().st_size


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--origem", type=Path, required=True,
                   help="diretório com os .jsonl das sessões")
    p.add_argument("--destino", type=Path, default=RAIZ / "ai-logs")
    p.add_argument("--prefixo", default="10-construcao",
                   help="prefixo dos arquivos gerados")
    args = p.parse_args()

    sessoes = sorted(args.origem.glob("*.jsonl"), key=lambda x: x.stat().st_mtime)
    if not sessoes:
        print(f"nenhuma sessão em {args.origem}", file=sys.stderr)
        return 2

    args.destino.mkdir(parents=True, exist_ok=True)
    escritos = 0
    for n, sessao in enumerate(sessoes, 1):
        corpo, turnos, tamanho = converter(sessao)
        if turnos < 4:
            continue  # sessão vazia ou abortada: não é registro de nada

        limpo = redigir(corpo)

        # ⚠️ O portão, e ele usa **o mesmo detector do teste** que barra o commit
        # (`app/privacy/segredos.py`). Quando cada um tinha o seu regex, o exportador
        # achava que tinha limpado e o portão achava que não — e quem estava certo era
        # o portão. Falhar alto é a única resposta aceitável: um export silenciosamente
        # incompleto é pior que nenhum export.
        restou = achados_de_credencial(limpo)
        if restou:
            print(f"ABORTADO: credencial sobreviveu à redação em {sessao.name}",
                  file=sys.stderr)
            for a in restou[:5]:
                print(f"  {a}", file=sys.stderr)
            return 1

        alvo = args.destino / f"{args.prefixo}-{n:02d}.md"
        alvo.write_text(
            f"# Sessão de construção {n:02d}\n\n"
            f"> Exportado por `scripts/exportar_ai_logs.py`, com redação de segredo,\n"
            f"> caminho absoluto e PII **na escrita**. {turnos} turnos; o `jsonl` de\n"
            f"> origem tinha {tamanho / 1024:.0f} KB, majoritariamente saída de\n"
            f"> ferramenta, truncada em {CORTE_FERRAMENTA} caracteres por bloco.\n"
            + limpo + "\n",
            encoding="utf-8",
        )
        escritos += 1
        print(f"{alvo.name}: {turnos} turnos", file=sys.stderr)

    print(f"→ {escritos} sessões em {args.destino}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
