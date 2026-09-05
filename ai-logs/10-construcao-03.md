# Sessão de construção 03

> Exportado por `scripts/exportar_ai_logs.py`, com redação de segredo,
> caminho absoluto e PII **na escrita**. 9 turnos; o `jsonl` de
> origem tinha 47 KB, majoritariamente saída de
> ferramenta, truncada em 1200 caracteres por bloco.

### Mateus

Review this change for security vulnerabilities.

Changed files (you may Read these and any other file in the repo):
  - tests/nucleo/test_repo_publico.py

Unified diff (only + lines are new):

=== DIFF: tests/nucleo/test_repo_publico.py ===
@@ -0,0 +1,99 @@
+"""Varredura de PII sobre tudo que é versionado e não é código.
+
+**Por que este teste existe agora e não na fatia 10.** O mascaramento de
+`app/privacy/mascarar.py` cobre mensagem persistida, log, trace, resposta de API e
+tela. Ele **não** cobre o que chega ao repositório por outro caminho:
+
+- `ai-logs/sessions/*.jsonl` — megabytes de texto cru das sessões de construção;
+- artefatos derivados do dataset (camada silver);
+- capturas do Playwright em `docs/evidencia-ui/`;
+- transcripts em `artifacts/`.
+
+Essa é a superfície de maior volume e a única sem teste. O scrub dela estava no
+checklist da fatia 10 como **procedimento manual** — e procedimento manual às onze da
+noite do dia da entrega é exatamente onde vaza.
+
+Reusa os mesmos regexes do mascaramento, apontados para outro diretório. Não há
+segunda definição de "o que é PII" para divergir, e **não há lista de exceções** — a
+mesma porta que se recusa a abrir no guardrail e nas fixtures.
+"""
+
+from __future__ import annotations
+
+import subprocess
+from pathlib import Path
+
+import pytest
+
+from app.privacy.mascarar import _REGRAS
+
+RAIZ = Path(__file__).resolve().parents[2]
+
+#: Extensões de código. Código é revisado linha a linha e tem os seus próprios testes
+#: (as fixtures usam gerador semeado — CLAUDE.md 13b); o risco aqui é conteúdo que
+#: chega em massa sem revisão.
+CODIGO = {".py", ".ts", ".tsx", ".js", ".jsx", ".sql", ".toml", ".lock", ".cfg", ".ini"}
+
+
+def _versionados() -> list[Path]:
+    saida = subprocess.run(
+        ["git", "ls-files", "-z"], cwd=RAIZ, capture_output=True, text=True, check=True
+    ).stdout
+    return [RAIZ / p for p in saida.split("\0") if p]
+
+
+def _alvos() -> list[Path]:
+    return [
+        p
+        for p in _versionados()
+        if p.suffix.lower() not in CODIGO and p.is_file() and p.stat().st_size > 0
+    ]
+
+
+def _achados(caminho: Path) -> list[tuple[str, str]]:
+    # errors="ignore" para que binários (parquet, png) também sejam varridos: uma
+    # string de PII dentro de um parquet aparece em texto do mesmo jeito.
+    try:
+        texto = caminho.read_bytes().decode("utf-8", errors="ignore")
+    except OSError:  # pragma: no cover
+        return []
+    return [
+        (nome, m.group(0))
+        for nome, padrao, _ in _REGRAS
+        for m in padrao.finditer(texto)
+    ]
+
+
+def test_ha_o_que_varrer():
+    """Se a listagem vier vazia, o teste abaixo passaria sem olhar nada."""
+    assert len(_alvos()) > 5
+
+
+def test_nenhum_arquivo_versionado_sem_ser_codigo_contem_pii():
+    problemas: list[str] = []
+    for alvo in _alvos():
+        for classe, trecho in _achados(alvo):
+            rel = alvo.relative_to(RAIZ)
+            problemas.append(f"{rel}: {classe} → {trecho!r}")
+    assert not problemas, (
+        "PII em arquivo versionado que não é código:\n  " + "\n  ".join(problemas)
+    )
+
+
+@pytest.mark.parametrize(
+    "diretorio",
+    ["ai-logs", "artifacts", "docs/evidencia-ui", "data"],
+)
+def test_diretorios_de_alto_volume_varridos_quando_existirem(diretorio):
+    """As quatro superfícies que nascem em massa. O teste não exige que existam —
+    `artifacts/` só aparece na fatia 3 —, mas varre assim que aparecerem."""
+    d = RAIZ / diretorio
+    if not d.exists():
+        pytest.skip(f"{diretorio}/ ainda não existe")
+    problemas = [
+        f"{p.relative_to(RAIZ)}: {classe} → {trecho!r}"
+        for p in _alvos()
+        if d in p.parents
+        for classe, trecho in _achados(p)
+    ]
+    assert not problemas, "\n  ".join(problemas)


Investigate per the method in your instructions, then return the findings list.

### Claude

Looking at the diff, this is a single new test file (`tests/nucleo/test_repo_publico.py`) that scans repo files for PII patterns. Per my instructions, I should generally not report on test/mock files unless they introduce a concrete security impact.

Let me verify the file contents match the diff and check for any actual security issue in this test.

### Claude

→ **Read**  `{"file_path": "/home/<usuario>/repo/tests/nucleo/test_repo_publico.py"}`

### Mateus

```
File does not exist. Note: your current working directory is <repo>.
```

### Claude

→ **Read**  `{"file_path": "<repo>/tests/nucleo/test_repo_publico.py"}`

### Mateus

```
1	"""Varredura de PII sobre tudo que é versionado e não é código.
2	
3	**Por que este teste existe agora e não na fatia 10.** O mascaramento de
4	`app/privacy/mascarar.py` cobre mensagem persistida, log, trace, resposta de API e
5	tela. Ele **não** cobre o que chega ao repositório por outro caminho:
6	
7	- `ai-logs/sessions/*.jsonl` — megabytes de texto cru das sessões de construção;
8	- artefatos derivados do dataset (camada silver);
9	- capturas do Playwright em `docs/evidencia-ui/`;
10	- transcripts em `artifacts/`.
11	
12	Essa é a superfície de maior volume e a única sem teste. O scrub dela estava no
13	checklist da fatia 10 como **procedimento manual** — e procedimento manual às onze da
14	noite do dia da entrega é exatamente onde vaza.
15	
16	Reusa os mesmos regexes do mascaramento, apontados para outro diretório. Não há
17	segunda definição de "o que é PII" para divergir, e **não há lista de exceções** — a
18	mesma porta que se recusa a abrir no guardrail e nas fixtures.
19	"""
20	
21	from __future__ import annotations
22	
23	import subprocess
24	from pathlib import Path
25	
26	import pytest
27	
28	from app.privacy.mascarar import _REGRAS
29	
30	RAIZ = Path(__file__).resolve
… [+2568 caracteres]
```

### Claude

Analysis of `tests/nucleo/test_repo_publico.py`:

**Entry points:** None — this is a pytest-only file that runs in CI/dev.

**Sinks touched:**
- `subprocess.run(["git", "ls-files", "-z"], cwd=RAIZ, ...)` — hardcoded argv, `shell=False` (default), fixed cwd. No injection surface.
- File reads via `read_bytes()` on paths returned by `git ls-files` — bounded to the repo tree; no traversal risk from external input.
- Regex `finditer` from imported `_REGRAS` — no dynamic construction here.

**Data flow:**
- No attacker-controllable input reaches any sink. The only "input" is the working-tree file list, which is developer-controlled at commit time.
- Assertion messages include matched PII snippets — but this only fires when the test *detects* PII in a versioned file, which is the intended failure mode (surfacing the leak to the developer). Not a new exposure introduced by this test.

**Phase 2c checks:**
- No new sink args, no allowlists, no auth gates, no IaC, no CI trigger changes, no observability additions in production code paths, no security-registry writes. The test is purely additive and read-only.
- No production code paths are modified.

**Reportability gate:** Per instructions, do not report test/mock files absent concrete impact. There is no concrete impact here — the test itself does not run in production, does not touch secrets/creds, and its subprocess call is safely constructed.

### Claude

→ **StructuredOutput**  `{"findings": []}`

### Mateus

```
Structured output provided successfully
```
