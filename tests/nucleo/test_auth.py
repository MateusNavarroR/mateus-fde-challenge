"""A autenticação da área de operação, provada pelos caminhos que importam.

Cinco perguntas, e todas foram feitas porque a resposta errada é plausível:

1. **`/admin` abre sem as variáveis?** É o item 14 do `CLAUDE.md` — o caminho de um
   comando não pode passar a exigir senha. Um login que se liga sozinho quebraria a
   promessa de `docker compose up` e nada no resto da suíte perceberia.
2. **`/admin` exige sessão com as variáveis?** O inverso: um login configurado e não
   aplicado é pior que login nenhum, porque parece protegido.
3. **Senha errada não autentica?** Inclusive quando o *usuário* está certo, que é o
   caso que um `or` trocado por `and` faria passar.
4. **A senha aparece em log ou em corpo de erro?** Esta é a que ninguém quebra de
   propósito e todo mundo quebra por descuido: um `detail=f"senha {senha} inválida"`
   escrito para depurar, ou um `log.debug(corpo)`. Num repositório público, o log da
   sessão de construção vai junto.
5. **Algum literal com cara de credencial entrou em arquivo versionado?** Reusa a
   listagem de `test_repo_publico.py` — a mesma fonte de "o que é versionado" —, em
   vez de abrir uma segunda varredura para divergir da primeira.

**Nenhuma senha literal neste arquivo.** As credenciais dos casos são geradas em
tempo de execução com `secrets`, pelo mesmo princípio do gerador semeado de PII
(CLAUDE.md 13b): o formato real é exercitado, e a varredura de segurança não tem o
que achar. Um `"senha123"` aqui seria exatamente o achado que o passe procura.
"""

from __future__ import annotations

import logging
import math
import re
import secrets
import subprocess
from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import auth

RAIZ = Path(__file__).resolve().parents[2]


def _credencial_efemera() -> tuple[str, str]:
    """Usuário e senha válidos em formato, inexistentes em qualquer lugar durável."""
    return f"op-{secrets.token_hex(4)}", secrets.token_urlsafe(24)


@pytest.fixture
def sem_login(monkeypatch):
    monkeypatch.delenv("ADMIN_USER", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    auth.redefinir_credenciais()
    yield
    auth.redefinir_credenciais()


@pytest.fixture
def com_login(monkeypatch):
    usuario, senha = _credencial_efemera()
    monkeypatch.setenv("ADMIN_USER", usuario)
    monkeypatch.setenv("ADMIN_PASSWORD", senha)
    auth.redefinir_credenciais()
    yield usuario, senha
    auth.redefinir_credenciais()


@pytest.fixture
def cliente():
    from app.main import app

    # Sem o context manager: o `lifespan` chama `bootstrap()`, que exige credencial de
    # LLM e conecta no banco. Nenhuma rota exercitada aqui precisa dos dois, e amarrar
    # o teste de autenticação à disponibilidade do Postgres o tornaria pulável
    # justamente no ambiente onde ele mais precisa rodar.
    return TestClient(app)


# ─── 1 · sem as variáveis, o admin abre ──────────────────────────────────────


def test_sem_as_variaveis_o_login_nao_existe(sem_login):
    assert auth.login_configurado() is False
    assert auth.credencial() is None


def test_sem_as_variaveis_a_porta_nao_barra(sem_login, monkeypatch):
    """O item 14: `docker compose up` e o avaliador vê tudo, sem procurar senha."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "admin_token", None)
    assert auth.exigir_admin(autoseguro_sessao=None, x_admin_token=None) is None


def test_sem_as_variaveis_o_estado_diz_que_esta_aberto(sem_login, cliente):
    r = cliente.get("/api/auth/estado")
    assert r.status_code == 200
    assert r.json() == {"exigido": False, "autenticado": True}


def test_meia_credencial_nao_liga_o_login(monkeypatch):
    """Usuário sem senha (ou senha sem usuário) é modo aberto, não meia-porta.

    Uma meia-autenticação é o pior dos dois mundos: parece protegida e não é. Se
    isto virasse "exige login com senha vazia", a instalação ficaria trancada sem
    ninguém conseguir entrar; se virasse "aceita qualquer senha", ficaria aberta
    parecendo fechada.
    """
    usuario, senha = _credencial_efemera()

    monkeypatch.setenv("ADMIN_USER", usuario)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    assert auth.redefinir_credenciais() is None

    monkeypatch.delenv("ADMIN_USER", raising=False)
    monkeypatch.setenv("ADMIN_PASSWORD", senha)
    assert auth.redefinir_credenciais() is None
    auth.redefinir_credenciais()


# ─── 2 · com as variáveis, a operação exige sessão ───────────────────────────


def test_com_as_variaveis_a_operacao_exige_sessao(com_login, cliente, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "admin_token", None)
    for rota in ("/api/conversations", "/api/quote-health", "/api/usage", "/api/handoffs"):
        r = cliente.get(rota)
        assert r.status_code == 401, f"{rota} respondeu {r.status_code}"


def test_o_ciclo_completo_entra_le_e_sai(com_login, cliente, monkeypatch):
    from app.config import get_settings

    # `APP_ENV=dev` EXPLÍCITO: o `TestClient` fala http, e desde que o padrão passou a
    # ser `prod` o cookie sai com `Secure` e o cliente não o devolve. Antes o teste
    # herdava o modo aberto por omissão — e um teste que depende de um default
    # inseguro é um teste que impede corrigi-lo.
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setattr(get_settings(), "admin_token", None)
    usuario, senha = com_login

    assert cliente.get("/api/auth/estado").json() == {"exigido": True, "autenticado": False}

    r = cliente.post("/api/auth/login", json={"usuario": usuario, "senha": senha})
    assert r.status_code == 204, r.text
    assert cliente.get("/api/auth/estado").json() == {"exigido": True, "autenticado": True}

    # Com a sessão de pé, a porta deixa de barrar. A rota em si pode estourar por
    # falta de Postgres — e uma exceção de banco já prova o que interessa: a
    # dependência de autenticação deixou o request passar.
    try:
        assert cliente.get("/api/handoffs").status_code != 401
    except Exception as e:  # noqa: BLE001
        assert "401" not in str(e)

    assert cliente.post("/api/auth/logout").status_code == 204
    assert cliente.get("/api/auth/estado").json()["autenticado"] is False


@pytest.mark.parametrize("env,espera_secure", [("prod", True), ("dev", False)])
def test_o_cookie_de_sessao_e_httponly_e_samesite_strict(
    com_login, cliente, monkeypatch, env, espera_secure
):
    """`httpOnly` e `SameSite=Strict` em qualquer modo; `Secure` só fora de dev.

    Os dois casos no mesmo teste porque o interessante é o CONTRASTE: em dev não há
    HTTPS e um cookie `Secure` simplesmente não voltaria, mas essa concessão não pode
    vazar para o modo padrão — que é onde o cookie viaja pela rede.
    """
    monkeypatch.setenv("APP_ENV", env)
    usuario, senha = com_login
    r = cliente.post("/api/auth/login", json={"usuario": usuario, "senha": senha})
    bruto = r.headers["set-cookie"].lower()
    assert auth.COOKIE_SESSAO.lower() in bruto
    assert "httponly" in bruto
    assert "samesite=strict" in bruto
    assert ("secure" in bruto) is espera_secure


def test_secure_liga_fora_de_dev(monkeypatch):
    monkeypatch.setenv("APP_ENV", "prod")
    assert auth._dev() is False
    monkeypatch.setenv("APP_ENV", "dev")
    assert auth._dev() is True


def test_cookie_forjado_ou_de_outra_chave_nao_vale(com_login):
    usuario, senha = com_login
    cred = auth.credencial()
    assert cred is not None
    bom = auth.emitir_sessao(cred)
    assert auth.sessao_valida(bom) is True

    # Adulterar qualquer parte quebra a assinatura.
    corpo, _, sig = bom.partition(".")
    assert auth.sessao_valida(f"{corpo}x.{sig}") is False
    assert auth.sessao_valida(f"{corpo}.{sig[:-2]}zz") is False
    for lixo in ("", "   ", ".", "a.b", "não é base64 . nem isto"):
        assert auth.sessao_valida(lixo) is False

    # Sessão emitida antes da troca de senha morre com ela: a chave HMAC vem do hash.
    auth.redefinir_credenciais()
    assert auth.sessao_valida(bom) is False


def test_sessao_expirada_nao_vale(com_login):
    cred = auth.credencial()
    assert cred is not None
    antigo = auth.emitir_sessao(cred, agora=0.0)
    assert auth.sessao_valida(antigo, agora=0.0) is True
    assert auth.sessao_valida(antigo, agora=auth.VALIDADE_S + 1) is False


# ─── 3 · senha errada não autentica ──────────────────────────────────────────


def test_senha_errada_com_usuario_certo_nao_autentica(com_login, cliente):
    usuario, _ = com_login
    _, outra = _credencial_efemera()
    r = cliente.post("/api/auth/login", json={"usuario": usuario, "senha": outra})
    assert r.status_code == 401
    assert cliente.get("/api/auth/estado").json()["autenticado"] is False


def test_usuario_errado_com_senha_certa_nao_autentica(com_login, cliente):
    _, senha = com_login
    outro, _ = _credencial_efemera()
    assert cliente.post("/api/auth/login", json={"usuario": outro, "senha": senha}).status_code == 401


def test_a_recusa_nao_distingue_usuario_de_senha(com_login, cliente):
    """Mensagens diferentes entregariam ao atacante que aquele nome existe."""
    usuario, senha = com_login
    outro, outra = _credencial_efemera()
    a = cliente.post("/api/auth/login", json={"usuario": usuario, "senha": outra})
    b = cliente.post("/api/auth/login", json={"usuario": outro, "senha": senha})
    assert a.json() == b.json()
    assert a.json()["detail"] == auth.FALHA


def test_a_senha_nunca_e_guardada_em_texto_puro(com_login):
    """Depois do boot a senha não existe no processo — nem no objeto, nem no ambiente."""
    import os

    usuario, senha = com_login
    cred = auth.credencial()
    assert cred is not None

    # `redefinir_credenciais` apaga a variável do ambiente herdado por subprocessos.
    assert os.getenv("ADMIN_PASSWORD") is None

    bytes_do_objeto = repr(vars(cred)).encode() + cred.salt + cred.digest
    assert senha.encode() not in bytes_do_objeto
    assert cred.confere(usuario, senha) is True


# ─── 4 · a senha não vaza por log nem por corpo de resposta ──────────────────


def test_a_senha_nao_aparece_em_log_nem_em_corpo_de_erro(com_login, cliente, caplog):
    usuario, senha = com_login
    _, outra = _credencial_efemera()

    with caplog.at_level(logging.DEBUG):
        recusado = cliente.post("/api/auth/login", json={"usuario": usuario, "senha": outra})
        aceito = cliente.post("/api/auth/login", json={"usuario": usuario, "senha": senha})

    registrado = "\n".join(r.getMessage() for r in caplog.records)
    for segredo in (senha, outra):
        assert segredo not in registrado, "senha no log"
        assert segredo not in recusado.text, "senha no corpo do 401"
        assert segredo not in aceito.text
        assert segredo not in str(dict(recusado.headers))
        assert segredo not in str(dict(aceito.headers))

    # E o cookie não é a senha disfarçada.
    assert senha not in aceito.headers.get("set-cookie", "")


def test_o_login_nao_ecoa_o_que_recebeu(com_login, cliente):
    """Um `detail` que devolve o corpo recebido transforma o 401 num espelho — e o
    corpo recebido contém a senha."""
    usuario, _ = com_login
    tentativa = secrets.token_urlsafe(20)
    r = cliente.post("/api/auth/login", json={"usuario": usuario, "senha": tentativa})
    assert tentativa not in r.text


# ─── 5 · nenhuma credencial embarcada em arquivo versionado ──────────────────

#: Os padrões vivem em `app/privacy/segredos.py`, origem única compartilhada com o
#: exportador de `ai-logs`. Quando cada um tinha o seu, o exportador achava que tinha
#: limpado e o portão achava que não.
from app.privacy.segredos import CREDENCIAIS, PLACEHOLDERS, parece_segredo  # noqa: E402
from app.privacy.segredos import achados as _achados_de_credencial  # noqa: E402


def _versionados() -> list[Path]:
    saida = subprocess.run(
        ["git", "ls-files", "-z"], cwd=RAIZ, capture_output=True, text=True, check=True
    ).stdout
    return [RAIZ / p for p in saida.split("\0") if p]


def _alvos() -> list[Path]:
    """Tudo que é versionado e legível. **Aqui não há recorte por extensão**, ao
    contrário da varredura de PII: PII chega em massa por artefato, credencial chega
    justamente pelo código."""
    return [p for p in _versionados() if p.is_file() and p.stat().st_size > 0]


def test_ha_o_que_varrer():
    assert len(_alvos()) > 20


def _achados(caminho: Path) -> list[str]:
    return _achados_de_credencial(
        caminho.read_bytes().decode("utf-8", errors="ignore")
    )


def test_nenhum_literal_de_credencial_em_arquivo_versionado():
    proprio = Path(__file__).resolve()
    problemas = [
        f"{alvo.relative_to(RAIZ)}: {achado}"
        for alvo in _alvos()
        # Este arquivo carrega os PADRÕES, não valores. Varrer os regexes com os
        # próprios regexes só produziria ruído — e a prova de que a varredura ainda
        # morde está em `test_a_varredura_pega_uma_credencial_plantada`.
        if alvo.resolve() != proprio
        for achado in _achados(alvo)
    ]
    assert not problemas, (
        "credencial embarcada em arquivo versionado — o repositório é público "
        "(CLAUDE.md 13):\n  " + "\n  ".join(problemas)
    )


def test_a_varredura_pega_uma_credencial_plantada(tmp_path):
    """A prova de que a varredura acima morde.

    Sem ela, um regex quebrado passaria verde para sempre — que é o modo de falhar
    mais caro de um teste de segurança, porque produz confiança sem cobertura. As
    três formas são plantadas, cada uma na sintaxe em que apareceria de verdade.
    """
    gerado = secrets.token_urlsafe(16)
    casos = {
        "codigo.py": f'ADMIN_PASSWORD = "{gerado}"',
        ".env": f"ADMIN_PASSWORD={gerado}\nexport API_KEY={gerado}",
        "nota.md": "sk-" + secrets.token_hex(16),
    }
    for nome, conteudo in casos.items():
        alvo = tmp_path / nome
        alvo.write_text(conteudo)
        assert _achados(alvo), f"{nome} passou pela varredura"


def test_a_varredura_nao_acusa_declaracao_sem_valor(tmp_path):
    """O contrário também precisa valer: `.env.example` com as variáveis **vazias**,
    documentação citando o nome, e um `Settings` com `str | None = None` são
    exatamente o que se quer que exista. Uma varredura que os acusa é desligada na
    primeira semana."""
    alvo = tmp_path / "ok.txt"
    alvo.write_text(
        "ADMIN_PASSWORD=\n"
        "ADMIN_USER=\n"
        "ANTHROPIC_API_KEY=<sua-chave-anthropic>\n"
        "admin_token: str | None = None\n"
        'APP_ADMIN_TOKEN: "${ADMIN_TOKEN:-}"\n'
        "Defina ADMIN_PASSWORD no seu .env para exigir login.\n"
    )
    assert _achados(alvo) == []


def test_o_env_example_declara_as_duas_variaveis_vazias():
    """`.env.example` é copiável — é o lugar mais provável de nascer uma senha de
    exemplo, e o mais lido pelo avaliador."""
    linhas = (RAIZ / ".env.example").read_text().splitlines()
    for nome in ("ADMIN_USER", "ADMIN_PASSWORD"):
        declaradas = [linha for linha in linhas if linha.startswith(f"{nome}=")]
        assert declaradas == [f"{nome}="], f"{nome} precisa existir e estar vazia"


def test_o_settings_nao_ganhou_default_de_credencial():
    """O default de um `Settings` é o esconderijo clássico: não parece uma senha
    colada no código, e é."""
    from app.config import Settings

    for campo, info in Settings.model_fields.items():
        if any(p in campo for p in ("password", "senha", "secret", "token", "key")):
            assert info.default in (None, ""), f"{campo} tem default: não pode"


# ─── a exceção do OpenAPI é nominal e fechada ────────────────────────────────


def test_as_rotas_escondidas_do_schema_sao_exatamente_as_declaradas():
    """`include_in_schema=False` é uma porta por onde superfície não documentada
    entraria sem o teste de deriva perceber. Ela existe (a raiz já a usava), então
    precisa de um inventário — este.
    """
    from app.main import app

    # `/docs`, `/redoc` e `/openapi.json` são do próprio FastAPI e já têm regra
    # própria (`test_docs_desligados_fora_de_dev`): não são superfície nossa.
    DO_FRAMEWORK = ("/docs", "/redoc", "/openapi.json")

    escondidas = {
        (r.path, m)
        for r in app.routes
        if getattr(r, "include_in_schema", True) is False
        and not r.path.startswith(DO_FRAMEWORK)
        for m in getattr(r, "methods", set())
        if m in {"GET", "POST", "PUT", "PATCH", "DELETE"}
    }
    # `/{caminho:path}` é o catch-all que serve o SPA pela mesma origem da API. Ele
    # substitui o antigo `GET /` e não entra no OpenAPI porque não é superfície de
    # API: é o `index.html` do frontend, com `/api/*`, `/docs`, `/redoc` e
    # `/openapi.json` explicitamente barrados dentro dele.
    esperadas = {("/{caminho:path}", "GET"), *auth.ROTAS_FORA_DO_CONTRATO}
    assert escondidas == esperadas, (
        "rota fora do OpenAPI congelado sem decisão escrita — acrescente-a ao "
        "contrato ou a esta lista, com o motivo"
    )


# ─── ADMIN_TOKEN vazio é ADMIN_TOKEN ausente ─────────────────────────────────
#
# Achado na vistoria de navegação, no caminho padrão de um comando. O
# `docker-compose.yml` passa `${ADMIN_TOKEN:-}`, que injeta STRING VAZIA quando a
# variável não existe. `admin_exigido` testava `is not None`, então a exigência
# ligava com um token vazio — e as duas superfícies discordavam sobre o que isso
# significa, porque uma coage o ausente para `""` e a outra comparava contra `None`.
#
# O resultado medido no navegador: pílula vermelha "sem conexão em tempo real" em
# toda tela do admin numa instalação saudável, socket reconectando para sempre, e
# nenhuma proteção real — `?token=` vazio abria.


@pytest.mark.parametrize("bruto", ["", "   ", "\t"])
def test_token_vazio_no_ambiente_nao_liga_a_exigencia(bruto):
    """É o compose que produz este valor, não uma configuração exótica."""
    from app.config import Settings

    cfg = Settings(admin_token=bruto)
    assert cfg.admin_token is None
    assert cfg.admin_exigido is False


def test_token_de_verdade_continua_ligando_a_exigencia():
    """O negativo: normalizar vazio não pode desligar a proteção de quem a quer."""
    from app.config import Settings

    cfg = Settings(admin_token="  s3gr3d0  ")
    assert cfg.admin_token == "s3gr3d0", "espaços da borda saem; o valor fica"
    assert cfg.admin_exigido is True


def test_rest_e_websocket_concordam_sobre_o_mesmo_token(cliente, monkeypatch):
    """A regra que faltava: a MESMA requisição não pode passar numa porta e ser
    recusada na outra.

    Medido antes da correção, com o token vazio do compose: `GET /api/handoffs` →
    200 e `WS /api/events` → 403. Um teste por superfície nunca acharia isso; só um
    teste que compara as duas.
    """
    from app.config import get_settings

    cfg = get_settings()

    # ⚠️ O valor CRU, sem `or None`. Escrever `token or None` aqui converteria `""`
    # em `None` no próprio teste e o faria pular exatamente o caso que ele existe
    # para cobrir — foi assim que ele nasceu, e passava com o bug presente.
    for token, esperado_aberto in (("", True), ("s3gr3d0", False)):
        monkeypatch.setattr(cfg, "admin_token", token)

        rest = cliente.get("/api/handoffs")
        rest_aberto = rest.status_code != 401

        try:
            with cliente.websocket_connect("/api/events"):
                ws_aberto = True
        except Exception:  # noqa: BLE001
            ws_aberto = False

        assert rest_aberto == ws_aberto == esperado_aberto, (
            f"token={token!r}: REST aberto={rest_aberto}, WS aberto={ws_aberto}, "
            f"esperado={esperado_aberto}"
        )


def test_um_token_vazio_apresentado_nao_abre_o_websocket(cliente, monkeypatch):
    """`?token=` vazio abria o socket quando a exigência estava ligada com token
    vazio. Com um token de verdade configurado, apresentar vazio tem de fechar."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "admin_token", "s3gr3d0")
    with pytest.raises(Exception):
        with cliente.websocket_connect("/api/events?token="):
            pass


# ─── o canal de tempo real tinha assinante e não tinha produtor ──────────────


def test_publicar_evento_e_de_fato_chamado_pelo_backend():
    """`publicar_evento` não era chamada em lugar NENHUM do código.

    O cliente assinava `/api/events`, o servidor aceitava a conexão, e nada era
    enviado — para sempre. A tela de handoffs anunciava por escrito *"a fila entra em
    tempo real, sem recarregar a página"*, e a fila nunca entrava.

    Um `grep` é o teste certo aqui: o defeito não era um caminho errado, era a
    AUSÊNCIA de qualquer chamada. Um teste de comportamento cobriria um produtor de
    cada vez; este falha no dia em que o último for removido.
    """
    raiz = Path(__file__).resolve().parents[2]
    # `app/channels/web.py` fica FORA da varredura: é onde as duas funções moram, e
    # `publicar_sync` chama `publicar_evento` internamente. Incluí-lo faria o teste
    # passar provando que a função chama a si mesma — foi assim que ele nasceu, e
    # sobreviveu à mutação que removia todos os produtores de verdade.
    definicao = raiz / "app" / "channels" / "web.py"
    chamadas = [
        f"{p.relative_to(raiz)}:{n}"
        for p in (raiz / "app").rglob("*.py")
        if p != definicao
        for n, linha in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if ("publicar_evento(" in linha or "publicar_sync(" in linha)
        and "def " not in linha
        and "import" not in linha
    ]
    assert chamadas, (
        "nenhum produtor de evento no backend: o push de `/api/events` volta a ser "
        "uma conexão que nunca recebe nada"
    )


def test_assumir_um_handoff_empurra_para_o_socket(cliente, monkeypatch):
    """O caminho ponta a ponta: um operador assume, e o socket de QUALQUER outro
    recebe — que é o que impede dois operadores de pegarem o mesmo caso.

    Também é o que faz a badge de pendentes deste mesmo cliente descer de 7 para 6
    sem F5: ela mora no `LayoutAdmin`, longe da página que faz a ação, e escuta o
    push.
    """
    import app.main as main
    from app.channels import web

    empurrados: list[tuple[str, dict]] = []
    monkeypatch.setattr(web, "publicar_sync",
                        lambda tipo, dados: empurrados.append((tipo, dados)))
    monkeypatch.setattr(
        "app.api.montagem.transicionar_handoff",
        lambda s, hid, status: {"id": hid, "status": status},
    )
    monkeypatch.setattr(main, "sessao", lambda: None, raising=False)

    # O `transicionar_handoff` de mentira não satisfaz o `response_model`, e a
    # validação da RESPOSTA acontece depois do push. Isto é aceitável aqui porque o
    # comportamento sob teste é o push: montar um `HandoffOut` completo faria o teste
    # passar a exercitar `montar_handoffs`, que tem os seus próprios testes.
    try:
        cliente.patch("/api/handoffs/ho_1", json={"status": "assumido"})
    except Exception:  # noqa: BLE001
        pass

    assert ("handoff.updated", {"id": "ho_1"}) in empurrados, (
        "assumir um handoff não empurrou nada: a fila e a badge de outro operador "
        "seguem mostrando o caso como pendente até alguém recarregar"
    )


# ─── APP_ENV falha para o lado SEGURO ────────────────────────────────────────


@pytest.mark.parametrize("valor", [None, "", "prod", "producao", "staging", "qualquer"])
def test_sem_APP_ENV_dev_a_documentacao_fica_fechada(monkeypatch, valor):
    """Achado do passe de `insecure-defaults`: o padrão era `dev`, e `dev` abre
    `/docs`, `/redoc` e `/openapi.json` e tira a flag `Secure` do cookie.

    A imagem define `APP_ENV=prod`, então o caminho entregue estava correto — e "a
    configuração de produção sobrescreve" é exatamente a racionalização que aquele
    passe recusa. Quem rodasse `uvicorn app.main:app` fora da imagem ficava exposto
    sem nenhum aviso.

    Só o valor literal `dev` liga o modo aberto. Qualquer outro, e a ausência, fecham.
    """
    import importlib

    if valor is None:
        monkeypatch.delenv("APP_ENV", raising=False)
    else:
        monkeypatch.setenv("APP_ENV", valor)

    assert auth._dev() is False

    import app.main as main

    recarregado = importlib.reload(main)
    try:
        assert recarregado.DEV is False
        assert recarregado.app.docs_url is None
        assert recarregado.app.redoc_url is None
        assert recarregado.app.openapi_url is None
    finally:
        monkeypatch.setenv("APP_ENV", "prod")
        importlib.reload(main)


def test_APP_ENV_dev_continua_abrindo_a_documentacao(monkeypatch):
    """O negativo: fechar por engano em desenvolvimento tiraria a ferramenta de quem
    a usa, e a correção teria trocado um problema por outro."""
    import importlib

    monkeypatch.setenv("APP_ENV", "dev")
    assert auth._dev() is True

    import app.main as main

    recarregado = importlib.reload(main)
    try:
        assert recarregado.app.docs_url == "/docs"
    finally:
        monkeypatch.setenv("APP_ENV", "prod")
        importlib.reload(main)


def test_a_sessao_SOBREVIVE_a_um_reinicio_do_processo(monkeypatch):
    """`docker compose up` não pode deslogar quem está trabalhando.

    A chave que assina o cookie vinha do `digest`, que depende de um salt sorteado a
    cada boot — então todo reinício invalidava as sessões abertas. Estava documentado
    como "consequência desejada", e não era: o que se quer é que **trocar a senha**
    derrube as sessões (teste abaixo), não que reiniciar derrube. As duas pareciam a
    mesma propriedade só porque a chave dependia do salt.
    """
    usuario, senha = _credencial_efemera()
    monkeypatch.setenv("ADMIN_USER", usuario)
    monkeypatch.setenv("ADMIN_PASSWORD", senha)

    primeira = auth.redefinir_credenciais()
    assert primeira is not None
    cookie = auth.emitir_sessao(primeira)

    # O "reinício": o ambiente é o mesmo, o processo relê tudo do zero.
    monkeypatch.setenv("ADMIN_PASSWORD", senha)
    segunda = auth.redefinir_credenciais()
    assert segunda is not None
    assert segunda.salt != primeira.salt, "o salt do scrypt continua sorteado por boot"

    assert auth.sessao_valida(cookie), (
        "a sessão morreu no reinício — é o defeito que fazia o avaliador ser deslogado "
        "a cada `docker compose up`"
    )


def test_trocar_a_senha_CONTINUA_invalidando_toda_sessao_viva():
    """A propriedade que de fato se queria, e que não pode ter sido perdida no caminho.

    Sem lista de revogação: a chave deriva da credencial, então a sessão assinada com
    a senha antiga deixa de conferir no instante em que a senha muda.
    """
    usuario, senha = _credencial_efemera()
    cred = auth.Credencial(
        usuario=usuario,
        salt=b"0" * 16,
        digest=b"1" * 32,
        chave_de_sessao=auth._chave_de_sessao(usuario, senha),
    )
    cookie = auth.emitir_sessao(cred)

    _, outra = _credencial_efemera()
    trocada = auth.Credencial(
        usuario=usuario,
        salt=b"0" * 16,
        digest=b"1" * 32,
        chave_de_sessao=auth._chave_de_sessao(usuario, outra),
    )
    assert trocada.chave_de_sessao != cred.chave_de_sessao

    import hmac as _hmac
    corpo, _, assinatura = cookie.partition(".")
    esperado = _hmac.new(
        trocada.chave_de_sessao, auth._desb64(corpo), __import__("hashlib").sha256
    ).digest()
    assert auth._b64(esperado) != assinatura, (
        "o cookie da senha antiga ainda confere com a nova — trocar a senha deixou de "
        "derrubar as sessões"
    )


def test_a_chave_de_sessao_NAO_serve_para_conferir_a_senha():
    """Nada que assine um cookie pode ser reusado na conferência, e vice-versa.

    Rótulo de domínio próprio, e algoritmos diferentes: a assinatura usa SHA-256
    direto, a conferência usa `scrypt` com salt.
    """
    usuario, senha = _credencial_efemera()
    chave = auth._chave_de_sessao(usuario, senha)
    assert chave != auth._derivar(senha, b"0" * 16)
    assert chave != __import__("hashlib").sha256(senha.encode()).digest()


def test_o_WEBSOCKET_de_eventos_usa_a_MESMA_regra_do_REST(monkeypatch):
    """Achado de auditoria, severidade alta: ele ficava ABERTO para anônimos.

    `/api/events` reimplementava a checagem em vez de reusar a do REST, e só sabia
    olhar `ADMIN_TOKEN`. Como `admin_exigido` é `admin_token is not None`, a
    configuração que o README recomenda para navegador — `ADMIN_USER` e
    `ADMIN_PASSWORD`, sem token — caía no `if` falso e aceitava qualquer conexão.

    O que saía por ali não era pouco: os frames de `handoff.created` carregam o
    `conversation_id`, que `docs/SEGURANCA.md` trata como CAPACIDADE — quem o tem lê
    a conversa inteira pelo WebSocket do chat, que é anônimo por desenho. Escutar
    aqui, colher ids, ler conversas de leads: a cadeia fechava.

    O teste é sobre a REGRA, não sobre o socket: duas cópias de uma regra de
    autorização divergem, e foi o que aconteceu.
    """
    usuario, senha = _credencial_efemera()
    monkeypatch.setenv("ADMIN_USER", usuario)
    monkeypatch.setenv("ADMIN_PASSWORD", senha)
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    auth.redefinir_credenciais()
    from app.config import get_settings

    get_settings.cache_clear() if hasattr(get_settings, "cache_clear") else None
    import app.config as _cfg

    _cfg._settings = None

    # Anônimo: sem cookie e sem token. É a configuração do README para navegador.
    assert not auth.autorizado_para_operacao(sessao=None, token=None), (
        "sem sessão e sem token, a operação foi autorizada — é o buraco pelo qual o "
        "WebSocket de eventos aceitava anônimos"
    )

    # Com sessão válida, entra.
    cred = auth.credencial()
    assert cred is not None
    assert auth.autorizado_para_operacao(sessao=auth.emitir_sessao(cred), token=None)


def test_a_chave_de_sessao_passa_pelo_SCRYPT_e_nao_por_um_hash_barato():
    """Achado de auditoria, severidade alta — e a regressão foi minha.

    A versão anterior era `SHA-256(usuario|senha)`: determinística e BARATA. Quem
    obtivesse um cookie por qualquer via teria um oráculo offline — para cada senha
    candidata, computar o SHA-256 e conferir o HMAC, a milhões por segundo. Era
    exatamente a proteção que o `scrypt` do login dá, jogada fora ao trocar a origem
    da chave para a sessão sobreviver a reinícios.

    O teste mede o que importa: a chave tem que ser o `scrypt` com o salt estável, e
    NÃO o SHA-256 direto da senha.
    """
    import hashlib

    usuario, senha = _credencial_efemera()
    chave = auth._chave_de_sessao(usuario, senha)

    barata = hashlib.sha256(
        b"autoseguro/sessao/v2|" + usuario.encode() + b"|" + senha.encode()
    ).digest()
    assert chave != barata, "a chave voltou a ser um hash barato da senha"

    esperada = hashlib.sha256(
        b"autoseguro/sessao/v3|" + auth._derivar(senha, auth._salt_de_sessao(usuario))
    ).digest()
    assert chave == esperada

    # E continua ESTÁVEL: a mesma credencial dá a mesma chave em processos diferentes.
    assert auth._chave_de_sessao(usuario, senha) == chave
    # ...enquanto trocar a senha continua derrubando toda sessão viva.
    _, outra = _credencial_efemera()
    assert auth._chave_de_sessao(usuario, outra) != chave
