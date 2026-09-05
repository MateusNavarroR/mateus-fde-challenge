"""Detecção de **credencial embarcada**, em origem única.

Irmão de `mascarar.py`: lá é PII, aqui é segredo. Os dois existem porque a varredura
precisa de uma definição só — quando o exportador de `ai-logs` e o teste do portão
usavam regexes diferentes, o exportador achava que tinha limpado e o teste achava que
não, e quem estava certo era o teste.

Usado por:

- `tests/nucleo/test_auth.py`, que reprova a suíte se algo versionado casar;
- `scripts/exportar_ai_logs.py`, que **aborta a escrita** em vez de gravar o arquivo.

Ter as duas coisas lendo daqui é o que garante que "o export passou" e "o portão passa"
signifiquem a mesma coisa.
"""

from __future__ import annotations

import math
import re
from collections import Counter

#: Nomes que denunciam um segredo. São os que o passe `insecure-defaults@trailofbits`
#: procura, e cada um já vazou de verdade em algum repositório público.
_NOMES = r"(?:admin_password|password|passwd|senha|secret_key|client_secret|secret|admin_token|access_token|api_key|apikey)"

#: A mesma lista para a forma B, **em caixa alta e sem `(?i)`**. Nome de variável de
#: ambiente é maiúsculo por convenção universal, e deixar a forma B insensível a caixa
#: fazia `senha_ok = hmac.compare_digest(...)` — um identificador Python comum — virar
#: achado. Um teste de segurança que acusa código legítimo é desligado, não corrigido.
_NOMES_ENV = _NOMES.upper()

#: **Duas formas de embarcar uma credencial, e a varredura persegue as duas.**
#:
#: A. *Literal citado em código* — `SENHA = "..."`, `{"api_key": "..."}`. É a forma
#:    que nasce de "só para testar" e fica. Não há porta de escape por entropia aqui:
#:    valor entre aspas atribuído a um nome de segredo é achado, ponto.
#: B. *Linha de arquivo de ambiente* — `ADMIN_PASSWORD=...`, com ou sem `export`.
#:    Esta forma aparece em prosa o tempo todo (documentação citando o nome da
#:    variável), então exige que o valor **pareça** um segredo — ver `_parece_segredo`.
#: C. *Prefixo de provider* — `sk-`, `ghp_`. Não precisa de nome nem de contexto: a
#:    própria string já é a credencial.
CREDENCIAIS = [
    ("literal citado", re.compile(r'(?i)\b' + _NOMES + r'["\']?\s*[:=]\s*(["\'])([^"\'\n]{6,})\1'), 2, False),
    ("linha de ambiente", re.compile(r"\b[A-Z_]*" + _NOMES_ENV + r"[A-Z_]*[ \t]*=[ \t]*([^\s\"'#\n\\]{6,})"), 1, True),
    ("chave de provider", re.compile(r"\b(sk-[A-Za-z0-9_\-]{16,}|ghp_[A-Za-z0-9]{20,})"), 1, False),
]

#: Um valor que é **placeholder ou referência** não é credencial. Isto não é uma lista
#: de arquivos isentos — não há nenhuma; é a definição do que conta como valor.
#:
#: `^[A-Z][A-Z0-9_]*$` cobre o caso que mais gera ruído: o valor é o **nome de outra
#: variável**, como no espelhamento `{"ADMIN_TOKEN": "APP_ADMIN_TOKEN"}` de
#: `app/bootstrap.py`. Segredo de verdade em CAIXA ALTA com underscores não existe.
PLACEHOLDERS = re.compile(
    r"^(?:"
    # O `(?i:...)` é escopado de propósito: se a insensibilidade a caixa vazasse para
    # o ramo `[A-Z][A-Z0-9_]*` abaixo, TODO token alfanumérico viraria "referência" e
    # a varredura pararia de acusar qualquer coisa — verde e cega.
    r"(?i:none|null|true|false|\.\.\.|x+|\*+|str\s*\|\s*none|senha|password|token|str|bool|int)"
    r"|<[^>]*>|\$\{[^}]*\}|%[sd]|\{[^}]*\}"
    # As marcas que a própria redação escreve. Sem isto o portão acusa o resultado da
    # limpeza — e o exportador entrava em laço: redigia, era acusado, e abortava.
    r"|\[(?:REDIGIDO|ANTHROPIC_API_KEY|API_KEY|GITHUB_TOKEN|AWS_KEY|PRIVATE_KEY"
    r"|CPF|CEP|EMAIL|TELEFONE|PLACA)\]"
    r"|[A-Z][A-Z0-9_]*"
    r")$"
)

#: Limiar de entropia de Shannon, em bits por caractere, para a forma B.
#:
#: É a mesma heurística do `gitleaks` e do `detect-secrets`, e o número tem medição:
#: `secrets.token_urlsafe(12)` fica entre 3,7 e 4,0; uma senha de gerenciador com
#: maiúscula, minúscula e dígito fica acima de 3,3; palavras de dicionário coladas
#: por hífen ficam abaixo de 2,9.
#:
#: 3,2 separa os dois grupos com folga dos dois lados. Um limiar mais baixo faria a
#: varredura acusar cada `POSTGRES_PASSWORD: postgres` do compose e cada nome de
#: variável citado em documentação — e varredura que grita à toa é varredura que
#: alguém desliga.
ENTROPIA_MINIMA = 3.2



def _entropia(valor: str) -> float:
    n = len(valor)
    if n == 0:
        return 0.0
    return -sum((c / n) * math.log2(c / n) for c in Counter(valor).values())


def parece_segredo(valor: str) -> bool:
    return len(valor) >= 8 and _entropia(valor) >= ENTROPIA_MINIMA


def achados(texto: str) -> list[str]:
    """`["classe → trecho", ...]`, vazio quando não há credencial aparente."""
    saida = []
    for classe, padrao, grupo, exige_entropia in CREDENCIAIS:
        for m in padrao.finditer(texto):
            valor = m.group(grupo)
            if PLACEHOLDERS.match(valor):
                continue
            if exige_entropia and not parece_segredo(valor):
                continue
            saida.append(f"{classe} → {m.group(0)!r}")
    return saida
