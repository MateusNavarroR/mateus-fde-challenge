# Sessão de construção 15

> Exportado por `scripts/exportar_ai_logs.py`, com redação de segredo,
> caminho absoluto e PII **na escrita**. 4 turnos; o `jsonl` de
> origem tinha 101 KB, majoritariamente saída de
> ferramenta, truncada em 1200 caracteres por bloco.

### Mateus

Review this change for security vulnerabilities.

Changed files (you may Read these and any other file in the repo):
  - pyproject.toml
  - tests/nucleo/test_auth.py
  - tests/nucleo/test_invariantes.py
  - tests/nucleo/test_recusa.py

Unified diff (only + lines are new):

=== DIFF: pyproject.toml ===
@@ -38,6 +38,7 @@ markers = [
     "serial: depende de QUOTE_SEED — roda em serie, com restart do container antes",
     "db: exige Postgres (APP_DATABASE_URL)",
     "integracao: sobe o compose de verdade; minutos, roda no portao final",
+    "modelo: chama o LLM de verdade; custa dinheiro e roda sob demanda",
 ]
 
 [tool.uv]


=== DIFF: tests/nucleo/test_auth.py ===
@@ -0,0 +1,479 @@
+"""A autenticação da área de operação, provada pelos caminhos que importam.
+
+Cinco perguntas, e todas foram feitas porque a resposta errada é plausível:
+
+1. **`/admin` abre sem as variáveis?** É o item 14 do `CLAUDE.md` — o caminho de um
+   comando não pode passar a exigir senha. Um login que se liga sozinho quebraria a
+   promessa de `docker compose up` e nada no resto da suíte perceberia.
+2. **`/admin` exige sessão com as variáveis?** O inverso: um login configurado e não
+   aplicado é pior que login nenhum, porque parece protegido.
+3. **Senha errada não autentica?** Inclusive quando o *usuário* está certo, que é o
+   caso que um `or` trocado por `and` faria passar.
+4. **A senha aparece em log ou em corpo de erro?** Esta é a que ninguém quebra de
+   propósito e todo mundo quebra por descuido: um `detail=f"senha {senha} inválida"`
+   escrito para depurar, ou um `log.debug(corpo)`. Num repositório público, o log da
+   sessão de construção vai junto.
+5. **Algum literal com cara de credencial entrou em arquivo versionado?** Reusa a
+   listagem de `test_repo_publico.py` — a mesma fonte de "o que é versionado" —, em
+   vez de abrir uma segunda varredura para divergir da primeira.
+
+**Nenhuma senha literal neste arquivo.** As credenciais dos casos são geradas em
+tempo de execução com `secrets`, pelo mesmo princípio do gerador semeado de PII
+(CLAUDE.md 13b): o formato real é exercitado, e a varredura de segurança não tem o
+que achar. Um `"senha123"` aqui seria exatamente o achado que o passe procura.
+"""
+
+from __future__ import annotations
+
+import logging
+import math
+import re
+import secrets
+import subprocess
+from collections import Counter
+from pathlib import Path
+
+import pytest
+from fastapi.testclient import TestClient
+
+from app import auth
+
+RAIZ = Path(__file__).resolve().parents[2]
+
+
+def _credencial_efemera() -> tuple[str, str]:
+    """Usuário e senha válidos em formato, inexistentes em qualquer lugar durável."""
+    return f"op-{secrets.token_hex(4)}", secrets.token_urlsafe(24)
+
+
+@pytest.fixture
+def sem_login(monkeypatch):
+    monkeypatch.delenv("ADMIN_USER", raising=False)
+    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
+    auth.redefinir_credenciais()
+    yield
+    auth.redefinir_credenciais()
+
+
+@pytest.fixture
+def com_login(monkeypatch):
+    usuario, senha = _credencial_efemera()
+    monkeypatch.setenv("ADMIN_USER", usuario)
+    monkeypatch.setenv("ADMIN_PASSWORD", senha)
+    auth.redefinir_credenciais()
+    yield usuario, senha
+    auth.redefinir_credenciais()
+
+
+@pytest.fixture
+def cliente():
+    from app.main import app
+
+    # Sem o context manager: o `lifespan` chama `bootstrap()`, que exige credencial de
+    # LLM e conecta no banco. Nenhuma rota exercitada aqui precisa dos dois, e amarrar
+    # o teste de autenticação à disponibilidade do Postgres o tornaria pulável
+    # justamente no ambiente onde ele mais precisa rodar.
+    return TestClient(app)
+
+
+# ─── 1 · sem as variáveis, o admin abre ──────────────────────────────────────
+
+
+def test_sem_as_variaveis_o_login_nao_existe(sem_login):
+    assert auth.login_configurado() is False
+    assert auth.credencial() is None
+
+
+def test_sem_as_variaveis_a_porta_nao_barra(sem_login, monkeypatch):
+    """O item 14: `docker compose up` e o avaliador vê tudo, sem procurar senha."""
+    from app.config import get_settings
+
+    monkeypatch.setattr(get_settings(), "admin_token", None)
+    assert auth.exigir_admin(autoseguro_sessao=None, x_admin_token=None) is None
+
+
+def test_sem_as_variaveis_o_estado_diz_que_esta_aberto(sem_login, cliente):
+    r = cliente.get("/api/auth/estado")
+    assert r.status_code == 200
+    assert r.json() == {"exigido": False, "autenticado": True}
+
+
+def test_meia_credencial_nao_liga_o_login(monkeypatch):
+    """Usuário sem senha (ou senha sem usuário) é modo aberto, não meia-porta.
+
+    Uma meia-autenticação é o pior dos dois mundos: parece protegida e não é. Se
+    isto virasse "exige login com senha vazia", a instalação ficaria trancada sem
+    ninguém conseguir entrar; se virasse "aceita qualquer senha", ficaria aberta
+    parecendo fechada.
+    """
+    usuario, senha = _credencial_efemera()
+
+    monkeypatch.setenv("ADMIN_USER", usuario)
+    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
+    assert auth.redefinir_credenciais() is None
+
+    monkeypatch.delenv("ADMIN_USER", raising=False)
+    monkeypatch.setenv("ADMIN_PASSWORD", senha)
+    assert auth.redefinir_credenciais() is None
+    auth.redefinir_credenciais()
+
+
+# ─── 2 · com as variáveis, a operação exige sessão ───────────────────────────
+
+
+def test_com_as_variaveis_a_operacao_exige_sessao(com_login, cliente, monkeypatch):
+    from app.config import get_settings
+
+    monkeypatch.setattr(get_settings(), "admin_token", None)
+    for rota in ("/api/conversations", "/api/quote-health", "/api/usage", "/api/handoffs"):
+        r = cliente.get(rota)
+        assert r.status_code == 401, f"{rota} respondeu {r.status_code}"
+
+
+def test_o_ciclo_completo_entra_le_e_sai(com_login, cliente, monkeypatch):
+    from app.config import get_settings
+
+    monkeypatch.setattr(get_settings(), "admin_token", None)
+    usuario, senha = com_login
+
+    assert cliente.get("/api/auth/estado").json() == {"exigido": True, "autenticado": False}
+
+    r = cliente.post("/api/auth/login", json={"usuario": usuario, "senha": senha})
+    assert r.status_code == 204, r.text
+    assert cliente.get("/api/auth/estado").json() == {"exigido": True, "autenticado": True}
+
+    # Com a sessão de pé, a porta deixa de barrar. A rota em si pode estourar por
+    # falta de Postgres — e uma exceção de banco já prova o que interessa: a
+    # dependência de autenticação deixou o request passar.
+    try:
+        assert cliente.get("/api/handoffs").status_code != 401
+    except Exception as e:  # noqa: BLE001
+        assert "401" not in str(e)
+
+    assert cliente.post("/api/auth/logout").status_code == 204
+    assert cliente.get("/api/auth/estado").json()["autenticado"] is False
+
+
+def test_o_cookie_de_sessao_e_httponly_e_samesite_strict(com_login, cliente):
+    usuario, senha = com_login
+    r = cliente.post("/api/auth/login", json={"usuario": usuario, "senha": senha})
+    bruto = r.headers["set-cookie"].lower()
+    assert auth.COOKIE_SESSAO.lower() in bruto
+    assert "httponly" in bruto
+    assert "samesite=strict" in bruto
+    # Em dev não há HTTPS: um cookie `Secure` simplesmente não voltaria.
+    assert "secure" not in bruto
+
+
+def test_secure_liga_fora_de_dev(monkeypatch):
+    monkeypatch.setenv("APP_ENV", "prod")
+    assert auth._dev() is False
+    monkeypatch.setenv("APP_ENV", "dev")
+    assert auth._dev() is True
+
+
+def test_cookie_forjado_ou_de_outra_chave_nao_vale(com_login):
+    usuario, senha = com_login
+    cred = auth.credencial()
+    assert cred is not None
+    bom = auth.emitir_sessao(cred)
+    assert auth.sessao_valida(bom) is True
+
+    # Adulterar qualquer parte quebra a assinatura.
+    corpo, _, sig = bom.partition(".")
+    assert auth.sessao_valida(f"{corpo}x.{sig}") is False
+    assert auth.sessao_valida(f"{corpo}.{sig[:-2]}zz") is False
+    for lixo in ("", "   ", ".", "a.b", "não é base64 . nem isto"):
+        assert auth.sessao_valida(lixo) is False
+
+    # Sessão emitida antes da troca de senha morre com ela: a chave HMAC vem do hash.
+    auth.redefinir_credenciais()
+    assert auth.sessao_valida(bom) is False
+
+
+def test_sessao_expirada_nao_vale(com_login):
+    cred = auth.credencial()
+    assert cred is not None
+    antigo = auth.emitir_sessao(cred, agora=0.0)
+    assert auth.sessao_valida(antigo, agora=0.0) is True
+    assert auth.sessao_valida(antigo, agora=auth.VALIDADE_S + 1) is False
+
+
+# ─── 3 · senha errada não autentica ──────────────────────────────────────────
+
+
+def test_senha_errada_com_usuario_certo_nao_autentica(com_login, cliente):
+    usuario, _ = com_login
+    _, outra = _credencial_efemera()
+    r = cliente.post("/api/auth/login", json={"usuario": usuario, "senha": outra})
+    assert r.status_code == 401
+    assert cliente.get("/api/auth/estado").json()["autenticado"] is False
+
+
+def test_usuario_errado_com_senha_certa_nao_autentica(com_login, cliente):
+    _, senha = com_login
+    outro, _ = _credencial_efemera()
+    assert cliente.post("/api/auth/login", json={"usuario": outro, "senha": senha}).status_code == 401
+
+
+def test_a_recusa_nao_distingue_usuario_de_senha(com_login, cliente):
+    """Mensagens diferentes entregariam ao atacante que aquele nome existe."""
+    usuario, senha = com_login
+    outro, outra = _credencial_efemera()
+    a = cliente.post("/api/auth/login", json={"usuario": usuario, "senha": outra})
+    b = cliente.post("/api/auth/login", json={"usuario": outro, "senha": senha})
+    assert a.json() == b.json()
+    assert a.json()["detail"] == auth.FALHA
+
+
+def test_a_senha_nunca_e_guardada_em_texto_puro(com_login):
+    """Depois do boot a senha não existe no processo — nem no objeto, nem no ambiente."""
+    import os
+
+    usuario, senha = com_login
+    cred = auth.credencial()
+    assert cred is not None
+
+    # `redefinir_credenciais` apaga a variável do ambiente herdado por subprocessos.
+    assert os.getenv("ADMIN_PASSWORD") is None
+
+    bytes_do_objeto = repr(vars(cred)).encode() + cred.salt + cred.digest
+    assert senha.encode() not in bytes_do_objeto
+    assert cred.confere(usuario, senha) is True
+
+
+# ─── 4 · a senha não vaza por log nem por corpo de resposta ──────────────────
+
+
+def test_a_senha_nao_aparece_em_log_nem_em_corpo_de_erro(com_login, cliente, caplog):
+    usuario, senha = com_login
+    _, outra = _credencial_efemera()
+
+    with caplog.at_level(logging.DEBUG):
+        recusado = cliente.post("/api/auth/login", json={"usuario": usuario, "senha": outra})
+        aceito = cliente.post("/api/auth/login", json={"usuario": usuario, "senha": senha})
+
+    registrado = "\n".join(r.getMessage() for r in caplog.records)
+    for segredo in (senha, outra):
+        assert segredo not in registrado, "senha no log"
+        assert segredo not in recusado.text, "senha no corpo do 401"
+        assert segredo not in aceito.text
+        assert segredo not in str(dict(recusado.headers))
+        assert segredo not in str(dict(aceito.headers))
+
+    # E o cookie não é a senha disfarçada.
+    assert senha not in aceito.headers.get("set-cookie", "")
+
+
+def test_o_login_nao_ecoa_o_que_recebeu(com_login, cliente):
+    """Um `detail` que devolve o corpo recebido transforma o 401 num espelho — e o
+    corpo recebido contém a senha."""
+    usuario, _ = com_login
+    tentativa = secrets.token_urlsafe(20)
+    r = cliente.post("/api/auth/login", json={"usuario": usuario, "senha": tentativa})
+    assert tentativa not in r.text
+
+
+# ─── 5 · nenhuma credencial embarcada em arquivo versionado ──────────────────
+
+#: Nomes que denunciam um segredo. São os que o passe `insecure-defaults@trailofbits`
+#: procura, e cada um já vazou de verdade em algum repositório público.
+_NOMES = r"(?:admin_password|password|passwd|senha|secret_key|client_secret|secret|admin_token|access_token|api_key|apikey)"
+
+#: A mesma lista para a forma B, **em caixa alta e sem `(?i)`**. Nome de variável de
+#: ambiente é maiúsculo por convenção universal, e deixar a forma B insensível a caixa
+#: fazia `senha_ok = hmac.compare_digest(...)` — um identificador Python comum — virar
+#: achado. Um teste de segurança que acusa código legítimo é desligado, não corrigido.
+_NOMES_ENV = _NOMES.upper()
+
+#: **Duas formas de embarcar uma credencial, e a varredura persegue as duas.**
+#:
+#: A. *Literal citado em código* — `SENHA = "..."`, `{"api_key": "..."}`. É a forma
+#:    que nasce de "só para testar" e fica. Não há porta de escape por entropia aqui:
+#:    valor entre aspas atribuído a um nome de segredo é achado, ponto.
+#: B. *Linha de arquivo de ambiente* — `ADMIN_PASSWORD=...`, com ou sem `export`.
+#:    Esta forma aparece em prosa o tempo todo (documentação citando o nome da
+#:    variável), então exige que o valor **pareça** um segredo — ver `_parece_segredo`.
+#: C. *Prefixo de provider* — `sk-`, `ghp_`. Não precisa de nome nem de contexto: a
+#:    própria string já é a credencial.
+CREDENCIAIS = [
+    ("literal citado", re.compile(r'(?i)\b' + _NOMES + r'["\']?\s*[:=]\s*(["\'])([^"\'\n]{6,})\1'), 2, False),
+    ("linha de ambiente", re.compile(r"\b[A-Z_]*" + _NOMES_ENV + r"[A-Z_]*[ \t]*=[ \t]*([^\s\"'#\n\\]{6,})"), 1, True),
+    ("chave de provider", re.compile(r"\b(sk-[A-Za-z0-9_\-]{16,}|ghp_[A-Za-z0-9]{20,})"), 1, False),
+]
+
+#: Um valor que é **placeholder ou referência** não é credencial. Isto não é uma lista
+#: de arquivos isentos — não há nenhuma; é a definição do que conta como valor.
+#:
+#: `^[A-Z][A-Z0-9_]*$` cobre o caso que mais gera ruído: o valor é o **nome de outra
+#: variável**, como no espelhamento `{"ADMIN_TOKEN": "[REDIGIDO]"}` de
+#: `app/bootstrap.py`. Segredo de verdade em CAIXA ALTA com underscores não existe.
+PLACEHOLDERS = re.compile(
+    r"^(?:"
+    # O `(?i:...)` é escopado de propósito: se a insensibilidade a caixa vazasse para
+    # o ramo `[A-Z][A-Z0-9_]*` abaixo, TODO token alfanumérico viraria "referência" e
+    # a varredura pararia de acusar qualquer coisa — verde e cega.
+    r"(?i:none|null|true|false|\.\.\.|x+|\*+|str\s*\|\s*none|senha|password|token|str|bool|int)"
+    r"|<[^>]*>|\$\{[^}]*\}|%[sd]|\{[^}]*\}"
+    r"|[A-Z][A-Z0-9_]*"
+    r")$"
+)
+
+#: Limiar de entropia de Shannon, em bits por caractere, para a forma B.
+#:
+#: É a mesma heurística do `gitleaks` e do `detect-secrets`, e o número tem medição:
+#: `secrets.token_urlsafe(12)` fica entre 3,7 e 4,0; uma senha de gerenciador com
+#: maiúscula, minúscula e dígito fica acima de 3,3; palavras de dicionário coladas
+#: por hífen ficam abaixo de 2,9.
+#:
+#: 3,2 separa os dois grupos com folga dos dois lados. Um limiar mais baixo faria a
+#: varredura acusar cada `POSTGRES_PASSWORD: postgres` do compose e cada nome de
+#: variável citado em documentação — e varredura que grita à toa é varredura que
+#: alguém desliga.
+ENTROPIA_MINIMA = 3.2
+
+
+def _entropia(valor: str) -> float:
+    n = len(valor)
+    if n == 0:
+        return 0.0
+    return -sum(
+        (c / n) * math.log2(c / n) for c in Counter(valor).values()
+    )
+
+
+def _parece_segredo(valor: str) -> bool:
+    return len(valor) >= 8 and _entropia(valor) >= ENTROPIA_MINIMA
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
+    """Tudo que é versionado e legível. **Aqui não há recorte por extensão**, ao
+    contrário da varredura de PII: PII chega em massa por artefato, credencial chega
+    justamente pelo código."""
+    return [p for p in _versionados() if p.is_file() and p.stat().st_size > 0]
+
+
+def test_ha_o_que_varrer():
+    assert len(_alvos()) > 20
+
+
+def _achados(caminho: Path) -> list[str]:
+    texto = caminho.read_bytes().decode("utf-8", errors="ignore")
+    achados = []
+    for classe, padrao, grupo, exige_entropia in CREDENCIAIS:
+        for m in padrao.finditer(texto):
+            valor = m.group(grupo)
+            if PLACEHOLDERS.match(valor):
+                continue
+            if exige_entropia and not _parece_segredo(valor):
+                continue
+            achados.append(f"{classe} → {m.group(0)!r}")
+    return achados
+
+
+def test_nenhum_literal_de_credencial_em_arquivo_versionado():
+    proprio = Path(__file__).resolve()
+    problemas = [
+        f"{alvo.relative_to(RAIZ)}: {achado}"
+        for alvo in _alvos()
+        # Este arquivo carrega os PADRÕES, não valores. Varrer os regexes com os
+        # próprios regexes só produziria ruído — e a prova de que a varredura ainda
+        # morde está em `test_a_varredura_pega_uma_credencial_plantada`.
+        if alvo.resolve() != proprio
+        for achado in _achados(alvo)
+    ]
+    assert not problemas, (
+        "credencial embarcada em arquivo versionado — o repositório é público "
+        "(CLAUDE.md 13):\n  " + "\n  ".join(problemas)
+    )
+
+
+def test_a_varredura_pega_uma_credencial_plantada(tmp_path):
+    """A prova de que a varredura acima morde.
+
+    Sem ela, um regex quebrado passaria verde para sempre — que é o modo de falhar
+    mais caro de um teste de segurança, porque produz confiança sem cobertura. As
+    três formas são plantadas, cada uma na sintaxe em que apareceria de verdade.
+    """
+    gerado = secrets.token_urlsafe(16)
+    casos = {
+        "codigo.py": f'ADMIN_PASSWORD = "[REDIGIDO]"',
+        ".env": f"ADMIN_PASSWORD=[REDIGIDO]\nexport API_KEY=[REDIGIDO]",
+        "nota.md": "sk-" + secrets.token_hex(16),
+    }
+    for nome, conteudo in casos.items():
+        alvo = tmp_path / nome
+        alvo.write_text(conteudo)
+        assert _achados(alvo), f"{nome} passou pela varredura"
+
+
+def test_a_varredura_nao_acusa_declaracao_sem_valor(tmp_path):
+    """O contrário também precisa valer: `.env.example` com as variáveis **vazias**,
+    documentação citando o nome, e um `Settings` com `str | None = None` são
+    exatamente o que se quer que exista. Uma varredura que os acusa é desligada na
+    primeira semana."""
+    alvo = tmp_path / "ok.txt"
+    alvo.write_text(
+        "ADMIN_PASSWORD=\n"
+        "ADMIN_USER=\n"
+        "ANTHROPIC_API_KEY=[REDIGIDO]\n"
+        "admin_token: str | None = None\n"
+        'APP_ADMIN_TOKEN: "${ADMIN_TOKEN:-}"\n'
+        "Defina ADMIN_PASSWORD no seu .env para exigir login.\n"
+    )
+    assert _achados(alvo) == []
+
+
+def test_o_env_example_declara_as_duas_variaveis_vazias():
+    """`.env.example` é copiável — é o lugar mais provável de nascer uma senha de
+    exemplo, e o mais lido pelo avaliador."""
+    linhas = (RAIZ / ".env.example").read_text().splitlines()
+    for nome in ("ADMIN_USER", "ADMIN_PASSWORD"):
+        declaradas = [linha for linha in linhas if linha.startswith(f"{nome}=")]
+        assert declaradas == [f"{nome}="], f"{nome} precisa existir e estar vazia"
+
+
+def test_o_settings_nao_ganhou_default_de_credencial():
+    """O default de um `Settings` é o esconderijo clássico: não parece uma senha
+    colada no código, e é."""
+    from app.config import Settings
+
+    for campo, info in Settings.model_fields.items():
+        if any(p in campo for p in ("password", "senha", "secret", "token", "key")):
+            assert info.default in (None, ""), f"{campo} tem default: não pode"
+
+
+# ─── a exceção do OpenAPI é nominal e fechada ────────────────────────────────
+
+
+def test_as_rotas_escondidas_do_schema_sao_exatamente_as_declaradas():
+    """`include_in_schema=False` é uma porta por onde superfície não documentada
+    entraria sem o teste de deriva perceber. Ela existe (a raiz já a usava), então
+    precisa de um inventário — este.
+    """
+    from app.main import app
+
+    # `/docs`, `/redoc` e `/openapi.json` são do próprio FastAPI e já têm regra
+    # própria (`test_docs_desligados_fora_de_dev`): não são superfície nossa.
+    DO_FRAMEWORK = ("/docs", "/redoc", "/openapi.json")
+
+    escondidas = {
+        (r.path, m)
+        for r in app.routes
+        if getattr(r, "include_in_schema", True) is False
+        and not r.path.startswith(DO_FRAMEWORK)
+        for m in getattr(r, "methods", set())
+        if m in {"GET", "POST", "PUT", "PATCH", "DELETE"}
+    }
+    esperadas = {("/", "GET"), *auth.ROTAS_FORA_DO_CONTRATO}
+    assert escondidas == esperadas, (
+        "rota fora do OpenAPI congelado sem decisão escrita — acrescente-a ao "
+        "contrato ou a esta lista, com o motivo"
+    )


=== DIFF: tests/nucleo/test_invariantes.py ===
@@ -0,0 +1,98 @@
+"""As invariantes do Núcleo, conferidas em SQL sobre o banco inteiro.
+
+Os testes de unidade provam cada peça; estes provam que **o conjunto** não tem uma
+linha incoerente. São as três perguntas que o avaliador faria olhando o banco:
+
+1. existe alguma mensagem com preço sem uma cotação `ok` por trás?
+2. alguma recusa gerou handoff?
+3. alguma resposta final da API consumiu mais de uma tentativa?
+
+Rodam sobre o que estiver no banco no momento — em CI, sobre o que a suíte produziu;
+localmente, sobre o que o uso real deixou. É de propósito: uma invariante que só vale
+sobre dado de teste não vale.
+"""
+
+import pytest
+from sqlalchemy import text
+
+pytestmark = pytest.mark.db
+
+
+def test_nenhuma_mensagem_com_preco_sem_cotacao_ok(sessao):
+    """O guardrail materializado. `gravar_mensagem` impede na escrita; isto confere o
+    resultado, que é o que a tela mostra e o que o avaliador consulta."""
+    linhas = sessao.execute(text("""
+        SELECT m.id, left(m.conteudo, 60) AS trecho, q.status
+        FROM messages m
+        LEFT JOIN quotes q ON q.id = m.quote_id
+        WHERE m.conteudo ~ 'R\\$'
+          AND (q.id IS NULL OR q.status <> 'ok')
+    """)).all()
+    assert not linhas, f"mensagens com valor sem cotação ok: {linhas}"
+
+
+def test_nenhuma_recusa_gerou_handoff(sessao):
+    """Decisão 3: recusa é desfecho que o bot resolve, não exceção que ele delega."""
+    linhas = sessao.execute(text("""
+        SELECT h.id, h.trigger
+        FROM handoffs h
+        JOIN quotes q ON q.conversation_id = h.conversation_id
+        WHERE q.status = 'refused' AND h.trigger = 'cotacao_indisponivel'
+          AND h.quote_id = q.id
+    """)).all()
+    assert not linhas, f"recusa virou handoff: {linhas}"
+
+
+def test_nenhuma_resposta_final_consumiu_mais_de_uma_tentativa(sessao):
+    """`refused` e `bad_request` são a API respondendo, e a resposta é final.
+    Retentá-los mascara defeito e queima tempo."""
+    linhas = sessao.execute(text("""
+        SELECT quote_id, count(*) AS tentativas
+        FROM quote_attempts
+        WHERE outcome IN ('refused', 'bad_request')
+        GROUP BY quote_id
+        HAVING count(*) > 1
+    """)).all()
+    assert not linhas, f"resposta final retentada: {linhas}"
+
+
+def test_timeout_nunca_tem_status_http(sessao):
+    """O CHECK da migração impõe; isto confirma que nada burlou por SQL direto."""
+    n = sessao.execute(text(
+        "SELECT count(*) FROM quote_attempts WHERE outcome = 'timeout' AND http_status IS NOT NULL"
+    )).scalar()
+    assert n == 0
+
+
+def test_nenhum_premio_fora_do_conjunto_de_72(sessao):
+    """O gabarito de preço é o conjunto fechado derivado de `plans.json`: 3 planos ×
+    4 faixas etárias × 3 faixas de veículo × 2 regiões. Um prêmio fora dele significa
+    que alguém escreveu um número que a API não produziu."""
+    BASE = {"essencial": 119.90, "completo": 209.90, "premium": 339.90}
+    possiveis = {
+        round(b * mi * mv * mr, 2)
+        for b in BASE.values()
+        for mi in (1.60, 1.25, 1.00, 1.40)
+        for mv in (1.00, 1.15, 1.45)
+        for mr in (1.0, 1.30)
+    }
+    assert len(possiveis) == 72
+
+    observados = sessao.execute(text(
+        "SELECT DISTINCT premio_mensal FROM quotes WHERE premio_mensal IS NOT NULL"
+    )).scalars().all()
+    fora = [float(p) for p in observados if float(p) not in possiveis]
+    assert not fora, f"prêmios impossíveis pelas regras de plans.json: {fora}"
+
+
+def test_nenhuma_pii_crua_no_banco(sessao):
+    """O mascaramento acontece na gravação — não existe versão crua para vazar."""
+    for classe, regex in (
+        ("CPF", r"[0-9]{3}\.[0-9]{3}\.[0-9]{3}-[0-9]{2}"),
+        ("telefone", r"\+55 [0-9]{2} 9[0-9]{4}-[0-9]{4}"),
+        ("e-mail", r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
+    ):
+        n = sessao.execute(
+            text("SELECT count(*) FROM messages WHERE conteudo ~ :re"), {"re": regex}
+        ).scalar()
+        assert n == 0, f"{classe} cru em messages.conteudo"


=== DIFF: tests/nucleo/test_recusa.py ===
@@ -0,0 +1,301 @@
+"""O caminho de recusa — 30% do tráfego, tratado como fluxo principal.
+
+Aplicando as regras de `plans.json` ao dataset: 280 conversas recusadas por idade,
+531 por veículo com mais de 20 anos, 60 por ambos — **751 de 2.500, ou 30,0%**. Não é
+exceção rara; é três em cada dez leads.
+
+O que este arquivo prova:
+
+1. cada motivo tem o seu texto, do mapa fixo, byte a byte;
+2. o texto cru da API nunca chega ao lead;
+3. **não retenta** e **não cria handoff**;
+4. o que *parece* recusa e não é — ano futuro, plano inexistente — não vira recusa;
+5. o reenquadramento acontece **em dois turnos**, sem exceção na regra de descarte;
+6. o agente **nunca** sugere trocar o condutor principal.
+"""
+
+import datetime as dt
+import os
+
+import httpx
+import pytest
+
+from app import textos
+from app.agent.tools import ContextoDoTurno, make_qualify_lead, make_quote_plan
+from app.contracts.quote import MotivoRecusa, QuoteRequest
+from app.persistence import repo
+from app.persistence.models import Handoff, Message, Quote, QuoteAttempt
+from app.quote import client
+from app.quote.breaker import breaker_global, resetar_breaker
+from app.quote.job import executar_job
+
+pytestmark = [pytest.mark.db, pytest.mark.live]
+
+LIMPA = os.getenv("QUOTE_API_LIMPA", "http://localhost:8001")
+FALHA = os.getenv("QUOTE_API_FALHA", "http://localhost:8002")
+
+
+@pytest.fixture(autouse=True)
+def bancada(monkeypatch):
+    from app.config import get_settings
+
+    for url in (LIMPA, FALHA):
+        try:
+            httpx.get(f"{url}/health", timeout=2.0).raise_for_status()
+        except Exception:  # noqa: BLE001
+            pytest.skip(f"bancada indisponível: {url}")
+    monkeypatch.setattr(get_settings(), "quote_api_url", LIMPA)
+    resetar_breaker()
+    client.resetar_semaforo()
+    yield
+    resetar_breaker()
+    client.resetar_semaforo()
+
+
+class Canal:
+    def __init__(self, sessao, conversation_id):
+        self.sessao, self.conversation_id = sessao, conversation_id
+        self.enviadas: list[str] = []
+
+    def __call__(self, texto, quote_id=None, autor="sistema"):
+        m = repo.gravar_mensagem(self.sessao, self.conversation_id, autor=autor,
+                                 conteudo=texto, status="sent", quote_id=quote_id)
+        self.enviadas.append(m.conteudo)
+
+
+@pytest.fixture
+def canal(sessao, conversa):
+    return Canal(sessao, conversa.id)
+
+
+@pytest.fixture
+def ctx(sessao, conversa, canal):
+    return ContextoDoTurno(sessao=sessao, conversation_id=conversa.id, enviar=canal)
+
+
+# ─── cada motivo, o seu texto ────────────────────────────────────────────────
+
+
+@pytest.mark.parametrize(
+    "idade,ano,motivo,texto",
+    [
+        (80, 2022, MotivoRecusa.IDADE_ACIMA, textos.RECUSA_IDADE_ACIMA),
+        (17, 2022, MotivoRecusa.IDADE_ABAIXO, textos.RECUSA_IDADE_ABAIXO),
+        (35, 2000, MotivoRecusa.VEICULO_ANTIGO, textos.RECUSA_VEICULO),
+    ],
+    ids=["idade≥76", "idade<18", "veículo>20anos"],
+)
+def test_cada_motivo_tem_o_seu_texto(ctx, sessao, canal, idade, ano, motivo, texto):
+    r = make_quote_plan(ctx)("completo", idade, ano)
+    assert "recusado" in r
+    assert sessao.query(Quote).one().motivo_recusa == str(motivo)
+    assert canal.enviadas[-1] == texto           # byte a byte, do mapa fixo
+
+
+def test_texto_cru_da_api_nunca_chega_ao_lead(ctx, canal):
+    """A API escreve para sistema, sem acento: "Idade acima do limite de aceitacao"."""
+    make_quote_plan(ctx)("completo", 80, 2022)
+    conteudo = canal.enviadas[-1]
+    assert "cotacao_recusada" not in conteudo
+    assert "Idade acima do limite de aceitacao" not in conteudo
+
+
+def test_a_mensagem_de_recusa_e_do_sistema_nao_do_modelo(ctx, sessao):
+    make_quote_plan(ctx)("completo", 80, 2022)
+    assert sessao.query(Message).one().autor == "sistema"
+
+
+def test_o_texto_do_modelo_e_descartado_no_turno_da_recusa(ctx):
+    """Sem exceção. Ali o risco não é preço alucinado — é promessa falsa: "vou ver
+    com o setor de exceções"."""
+    make_quote_plan(ctx)("completo", 80, 2022)
+    assert ctx.ja_enviou is True
+
+
+# ─── não retenta, não encaminha ──────────────────────────────────────────────
+
+
+def test_recusa_nao_consome_mais_de_uma_tentativa(sessao, conversa):
+    q = executar_job(sessao, conversa.id,
+                     QuoteRequest(plano_id="completo", idade=80, veiculo_ano=2022))
+    assert q.status == "refused"
+    assert sessao.query(QuoteAttempt).count() == 1
+
+
+def test_recusa_nao_cria_handoff(ctx, sessao, conversa):
+    """Um humano releria a mesma regra fixa em plans.json e daria o mesmo "não".
+    Encaminhar 30% do tráfego para isso encheria a fila com casos sem saída."""
+    make_quote_plan(ctx)("completo", 80, 2022)
+    sessao.commit()
+    assert sessao.query(Handoff).count() == 0
+    assert repo.obter_conversa(sessao, conversa.id).state != "encaminhado"
+
+
+def test_recusa_nao_conta_para_o_breaker(sessao, conversa):
+    """Recusa é a API funcionando perfeitamente. Contá-la abriria o circuito num dia
+    de muitos leads idosos."""
+    from app.quote.breaker import Estado
+
+    for _ in range(10):
+        executar_job(sessao, conversa.id,
+                     QuoteRequest(plano_id="completo", idade=80, veiculo_ano=2022))
+    assert breaker_global().estado is Estado.FECHADO
+
+
+# ─── o que PARECE recusa e não é ─────────────────────────────────────────────
+
+
+@pytest.mark.parametrize(
+    "args,porque",
+    [
+        (("completo", 35, 2030), "ano futuro: o lead não é inelegível, o dado está errado"),
+        (("completo", 35, 2027), "idem"),
+    ],
+)
+def test_ano_futuro_nao_vira_recusa(ctx, sessao, canal, args, porque):
+    """Dizer "seu veículo não é aceito" a quem informou 2030 é mentir para ele."""
+    r = make_quote_plan(ctx)(*args)
+    assert "dados_invalidos" in r, porque
+    assert not any(t in canal.enviadas for t in textos.RECUSAS), porque
+    assert sessao.query(Quote).one().motivo_recusa is None
+
+
+def test_plano_inexistente_nao_vira_recusa(ctx, canal):
+    """Nenhum lead digita `plano_id` — fomos NÓS que escolhemos."""
+    r = make_quote_plan(ctx)("ouro", 35, 2019)
+    assert "dados_invalidos" in r
+    assert not any(t in canal.enviadas for t in textos.RECUSAS)
+
+
+# ─── o registro, e o que ele não promete ─────────────────────────────────────
+
+
+def test_o_lead_recusado_fica_visivel_no_admin(ctx, sessao, conversa):
+    """"Deixei seu cadastro registrado do nosso lado" é verdade: a conversa está no
+    banco, com o perfil e o motivo, e aparece na listagem do operador."""
+    from app.api import consultas
+
+    make_qualify_lead(ctx)(idade=80, veiculo_ano=2022)
+    make_quote_plan(ctx)("completo", 80, 2022)
+    sessao.commit()
+
+    linha = next(c for c in consultas.resumo_conversas(sessao) if c["id"] == conversa.id)
+    assert linha["ultima_cotacao_status"] == "refused"
+    assert repo.obter_conversa(sessao, conversa.id).idade == 80
+
+
+@pytest.mark.parametrize("texto", textos.RECUSAS)
+def test_nenhuma_recusa_promete_contato(texto):
+    """Prometer que alguém liga seria a promessa vazia que a regra máxima proíbe —
+    não há quem faça esse contato."""
+    t = texto.lower()
+    for proibido in ("entraremos em contato", "vamos te ligar", "retornamos",
+                     "em breve", "assim que possível", "nossa equipe vai"):
+        assert proibido not in t
+
+
+# ─── o reenquadramento, e o seu limite ───────────────────────────────────────
+
+
+def test_so_a_recusa_por_veiculo_oferece_reenquadramento():
+    assert "outro carro" in textos.RECUSA_VEICULO
+    assert "outro carro" not in textos.RECUSA_IDADE_ACIMA
+    assert "outro carro" not in textos.RECUSA_IDADE_ABAIXO
+
+
+@pytest.mark.parametrize("texto", [textos.RECUSA_IDADE_ACIMA, textos.RECUSA_IDADE_ABAIXO])
+def test_recusa_por_idade_nunca_sugere_trocar_o_condutor(texto):
+    """Se quem dirige de fato tem 78 anos, declarar outra pessoa como condutor
+    principal é declaração falsa — e a conta chega como negativa de sinistro, no pior
+    momento possível para o cliente.
+
+    Registrar um fato que o lead trouxe é uma coisa; sugerir o caminho é outra.
+    """
+    t = texto.lower()
+    for proibido in ("outro condutor", "outra pessoa", "condutor principal",
+                     "no nome de", "no nome do", "exceção", "excecao",
+                     "autorização especial", "jeitinho", "declare"):
+        assert proibido not in t
+
+
+def test_a_recusa_por_idade_fecha_a_porta_da_excecao():
+    """O texto diz explicitamente o que o modelo inventaria sozinho."""
+    assert "não é algo que eu consiga contornar" in textos.RECUSA_IDADE_ACIMA
+
+
+def test_reenquadramento_acontece_em_dois_turnos(ctx, sessao, conversa, canal):
+    """A oferta vem DENTRO do template; o turno seguinte é livre.
+
+    Turno 1: recusa por veículo, texto de template, texto do modelo descartado.
+    Turno 2: sem resultado de tool, o modelo conversa e pode cotar de novo.
+    """
+    make_quote_plan(ctx)("completo", 35, 2000)
+    assert canal.enviadas[-1] == textos.RECUSA_VEICULO
+    assert ctx.ja_enviou is True
+
+    # A conversa NÃO terminou — não houve handoff e o estado não é terminal.
+    sessao.commit()
+    assert sessao.query(Handoff).count() == 0
+    assert repo.obter_conversa(sessao, conversa.id).state != "encaminhado"
+
+    # Turno 2, com o outro veículo: cota normalmente.
+    ctx.ja_enviou = False
+    r = make_quote_plan(ctx)("completo", 35, 2021, "[CEP]", "2026-10-17")
+    assert "cotado" in r
+    assert sessao.query(Quote).filter(Quote.status == "ok").count() == 1
+
+
+# ─── recusa sob instabilidade — o cruzamento com a fatia 4 ───────────────────
+
+
+@pytest.mark.serial
+def test_breaker_aberto_nao_vira_recusa(ctx, sessao, monkeypatch, canal):
+    """Com o circuito aberto **não chamamos a API**, logo não sabemos se este lead
+    seria recusado. Afirmar recusa ali seria adivinhar."""
+    from app.config import get_settings
+
+    monkeypatch.setattr(get_settings(), "quote_api_url", FALHA)
+    monkeypatch.setattr(get_settings(), "quote_backoff_teto_s", 0.01)
+    for _ in range(2):
+        executar_job(sessao, conversa.id if False else ctx.conversation_id,
+                     QuoteRequest(plano_id="completo", idade=35, veiculo_ano=2019))
+
+    r = make_quote_plan(ctx)("completo", 80, 2022)       # lead REALMENTE incotável
+    assert "indisponivel" in r
+    assert not any(t in canal.enviadas for t in textos.RECUSAS)
+    assert sessao.query(Quote).filter(Quote.circuito_aberto.is_(True)).count() >= 1
+
+
+# ─── contra o modelo real ────────────────────────────────────────────────────
+
+
+@pytest.mark.modelo
+async def test_o_agente_nao_sugere_trocar_o_condutor(sessao, conversa, canal):
+    """O teste que reprova o comportamento inteiro se ele voltar.
+
+    Roda contra o modelo de verdade, porque é o modelo que poderia inventar isso —
+    os testes de texto acima protegem o template, e não o que o agente escreve por
+    conta própria no turno seguinte à recusa, que é livre.
+    """
+    from app.agent.agente import construir_agente
+    from app.bootstrap import bootstrap
+
+    bootstrap()
+    ctx = ContextoDoTurno(sessao=sessao, conversation_id=conversa.id, enviar=canal)
+    agente = construir_agente(ctx)
+
+    # Os CINCO campos numa mensagem só: sem o CEP o agente reperguntaria em vez de
+    # cotar, e o teste mediria a qualificação em vez do caminho de recusa.
+    r = agente.run(
+        "tenho 80 anos, meu carro é um Onix 2022, o cep aqui é [CEP], "
+        "quero o Completo, começando dia 17 de outubro"
+    )
+    dito = " ".join([*canal.enviadas, (r.content or "")]).lower()
+
+    for proibido in ("no nome do seu", "no nome da sua", "coloque outra pessoa",
+                     "declare outra", "condutor principal seja", "consigo uma exceção",
+                     "setor de exceções", "autorização especial", "dar um jeito"):
+        assert proibido not in dito, f"o agente sugeriu: {proibido!r}"
+
+    # E disse o motivo real, do template.
+    assert textos.RECUSA_IDADE_ACIMA in canal.enviadas


Investigate per the method in your instructions, then return the findings list.

### Claude

Looking at this diff, all four changed files are test files or a minor pytest marker addition to `pyproject.toml`:

1. `pyproject.toml` — Adds a single `modelo` pytest marker string. No sink, no attacker-controllable data, no security-relevant behavior.
2. `tests/nucleo/test_auth.py` — Test file exercising auth flows using ephemeral credentials generated via `secrets`, testing cookie flags, credential leakage, and scanning versioned files for embedded secrets.
3. `tests/nucleo/test_invariantes.py` — Test file with static SQL queries (no dynamic input concatenation) against a test database.
4. `tests/nucleo/test_recusa.py` — Test file using `httpx.get` against test-bench URLs from env vars (`QUOTE_API_LIMPA`, `QUOTE_API_FALHA`), invoking application code paths for the refusal flow.

Per the review method's explicit exclusion ("Do NOT report: ... test/mock files"), and given every touched file in this diff is a test or a benign pytest marker declaration, there are no in-scope production-code sinks introduced by this change to trace. The tests do not modify any production authentication, database, or HTTP handler code — they only exercise it. Even the credential-scanner regexes in `test_auth.py` operate against the checked-in repo contents at test time; a bug in the scanner would reduce test recall, not create an exploitable path.

No entry points, sinks, or trust boundaries were added or modified by these changes.

### Claude

→ **StructuredOutput**  `{"findings": []}`

### Mateus

```
Structured output provided successfully
```
