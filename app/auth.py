"""A autenticação da área de operação — sessão em cookie, senha nunca em texto puro.

**O problema.** `ADMIN_TOKEN` (CLAUDE.md 14c) é um mecanismo de máquina: um segredo
único, colado num cabeçalho. Serve a `curl` e a CI, e é péssimo para uma pessoa —
quem abre `/admin` no navegador não tem onde digitar um cabeçalho, e a solução que
existia era guardar o token no `localStorage`, que é exatamente onde um XSS o lê.

Esta camada acrescenta o mecanismo de **gente**: usuário e senha, sessão em cookie
`httpOnly`. Ela **não substitui** o token — os dois convivem, e a ordem está em
`exigir_admin`.

**Cinco restrições, e todas nascem de o repositório ser público** (CLAUDE.md 13):

1. *Nenhuma credencial no código.* Nem constante, nem default de `Settings`, nem
   fixture, nem exemplo copiável. `ADMIN_USER` e `ADMIN_PASSWORD` vêm do ambiente e
   **não têm valor padrão**. Um default aqui seria um achado autoinfligido no
   `insecure-defaults@trailofbits` — num critério que é justamente sobre cuidado com
   dados.
2. *Sem as duas variáveis, o login não existe e `/admin` abre direto*, como antes.
   Isso preserva o item 14: o caminho de um comando não muda, e quem sobe o compose
   vê tudo sem procurar senha. A proteção efetiva no caminho padrão continua sendo o
   bind em `127.0.0.1` (14b), que não depende de autenticação nenhuma.
3. *A senha nunca é comparada nem guardada em texto puro.* No boot ela é derivada com
   `hashlib.scrypt` e um salt aleatório do processo, e o texto puro é **apagado do
   `os.environ`** logo em seguida — para que nem um `/debug` acidental, nem um
   subprocesso herdado, nem um dump de ambiente o encontrem.
4. *Comparação em tempo constante*, com `hmac.compare_digest`, e para **os dois**
   campos. Comparar o usuário com `==` vazaria, por tempo, se aquele nome existe.
5. *A sessão vive num cookie `httpOnly`, `SameSite=Strict`, `Secure` fora de dev.*
   Nada em `localStorage`: o ponto de trocar o token pela senha era tirar o segredo
   do alcance do JavaScript da página.

**A sessão não tem armazenamento.** O cookie carrega `usuario|expiração` assinado por
HMAC com uma chave derivada da credencial. Consequência desejada: trocar a senha
invalida toda sessão viva, sem lista de revogação. **Reiniciar o processo NÃO
invalida** — isso já foi assim, por a chave depender do salt sorteado a cada boot, e
era um efeito colateral vendido como decisão: cada `docker compose up` deslogava quem
estivesse trabalhando. O benefício de não haver armazenamento continua: nenhuma
tabela de sessão para crescer, vazar ou dessincronizar.

Sem dependência nova: `hashlib`, `hmac` e `secrets` são da biblioteca padrão.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
import time
from dataclasses import dataclass

from fastapi import Cookie, FastAPI, Header, HTTPException, Response
from pydantic import BaseModel, Field

log = logging.getLogger("autoseguro")

#: Nome do cookie de sessão. Prefixo do projeto para não colidir com outra coisa
#: servida do mesmo host em desenvolvimento.
COOKIE_SESSAO = "autoseguro_sessao"

#: Oito horas: um turno. Mais que isso é uma sessão que sobrevive à pessoa sair da
#: mesa; muito menos é login no meio de uma investigação de handoff.
VALIDADE_S = 8 * 60 * 60

#: Parâmetros do `scrypt`. N=2^14 com r=8 usa ~16 MiB e leva dezenas de milissegundos
#: — caro o bastante para uma tentativa por vez ser lenta em força bruta, barato o
#: bastante para não ser ele o DoS. São os valores de referência do RFC 7914.
_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}

#: As três rotas desta camada. Elas ficam **fora** do OpenAPI congelado de propósito,
#: e a lista existe para que essa exceção seja nominal e fechada — é o que
#: `tests/nucleo/test_auth.py` verifica, para que `include_in_schema=False` não vire
#: uma porta por onde superfície não documentada entra em silêncio.
ROTAS_FORA_DO_CONTRATO = (
    ("/api/auth/estado", "GET"),
    ("/api/auth/login", "POST"),
    ("/api/auth/logout", "POST"),
)

#: Mensagem única para usuário inexistente e senha errada. Distinguir os dois casos
#: entrega ao atacante metade do trabalho — e não ajuda em nada quem só errou.
FALHA = "usuário ou senha inválidos"


def _dev() -> bool:
    """`Secure` no cookie exige HTTPS; em desenvolvimento o serviço é HTTP puro e um
    cookie `Secure` simplesmente não voltaria — o login pareceria quebrado."""
    return os.getenv("APP_ENV", "prod") == "dev"


@dataclass(frozen=True)
class Credencial:
    """O que sobra da senha depois do boot: nunca ela mesma."""

    usuario: str
    salt: bytes
    digest: bytes
    #: Chave HMAC da assinatura do cookie. Calculada no boot, ANTES de a senha ser
    #: apagada do processo — ver `chave_de_sessao` e `redefinir_credenciais`.
    chave_de_sessao: bytes

    def confere(self, usuario: str, senha: str) -> bool:
        """Tempo constante nos dois campos, e **sem curto-circuito**.

        Um `and` entre as duas comparações deixaria de derivar o hash quando o usuário
        não bate, e a diferença de tempo (dezenas de milissegundos do `scrypt`) diria
        ao atacante que aquele nome existe. Por isso as duas linhas são avaliadas
        sempre, e só depois combinadas.
        """
        nome_ok = hmac.compare_digest(usuario.encode("utf-8"), self.usuario.encode("utf-8"))
        senha_ok = hmac.compare_digest(_derivar(senha, self.salt), self.digest)
        return nome_ok & senha_ok



def _derivar(senha: str, salt: bytes) -> bytes:
    return hashlib.scrypt(senha.encode("utf-8"), salt=salt, **_SCRYPT)


#: Salt do `scrypt` que produz a chave de SESSÃO. Derivado do usuário, não sorteado.
#:
#: Um salt aleatório por boot dá uma chave nova a cada reinício — que era o defeito
#: que derrubava a sessão de quem estava trabalhando a cada `docker compose up`. Aqui
#: ele precisa ser estável, e derivá-lo do usuário mantém a propriedade que o salt de
#: fato entrega quando não há banco de hashes: duas instalações com a mesma senha e
#: usuários diferentes não compartilham chave.
def _salt_de_sessao(usuario: str) -> bytes:
    return hashlib.sha256(b"autoseguro/salt-sessao/v1|" + usuario.encode("utf-8")).digest()[:16]


def _chave_de_sessao(usuario: str, senha: str) -> bytes:
    """A chave que assina o cookie: **estável entre reinícios, presa à credencial.**

    Antes ela vinha do `digest`, que depende de um salt sorteado a cada boot — então
    todo `docker compose up` invalidava as sessões abertas. Estava escrito como
    "consequência desejada", e não era: o que se quer é que **trocar a senha** derrube
    as sessões, não que reiniciar o serviço derrube. As duas propriedades pareciam a
    mesma porque a chave dependia do salt; separá-las custa esta função.

    **Passa pelo `scrypt`, e essa linha é o conserto de um achado de auditoria.** A
    primeira versão era `SHA-256(usuario|senha)` — determinística e BARATA. Quem
    obtivesse um cookie por qualquer via (captura de tela, log, acesso à máquina;
    XSS não, porque ele é `httpOnly`) teria um oráculo offline: para cada senha
    candidata, computar o SHA-256 e conferir o HMAC, a milhões de tentativas por
    segundo. Era exatamente a proteção que o `scrypt` do login existe para dar, e eu
    a tinha jogado fora ao trocar a origem da chave para consertar o reinício.

    Com o `scrypt` no caminho, cada tentativa custa dezenas de milissegundos e ~16 MiB
    — a mesma barreira do login. O salt é derivado do usuário (`_salt_de_sessao`), e
    não sorteado, que é o que mantém a chave estável entre reinícios.

    Preserva tudo que importava:

    - **trocar usuário ou senha muda a chave**, e toda sessão viva morre, sem lista de
      revogação — a propriedade que de fato se queria;
    - **nada que assine um cookie serve para conferir uma senha**: o rótulo é outro, e
      um SHA-256 direto não é comparável ao `scrypt` que a conferência usa;
    - **a senha continua saindo do processo.** Esta função roda uma vez, no boot, e o
      texto puro é apagado logo depois — o que fica guardado é a chave, que não
      permite recuperar a senha nem se passar pela conferência.

    O `scrypt` da senha continua com salt aleatório: ele defende a conferência, e não
    tem relação com a assinatura do cookie.
    """
    return hashlib.sha256(
        b"autoseguro/sessao/v3|" + _derivar(senha, _salt_de_sessao(usuario))
    ).digest()


_credencial: Credencial | None = None
_lida = False


def redefinir_credenciais() -> Credencial | None:
    """Lê o ambiente, deriva o hash e **apaga a senha em texto puro do processo**.

    Chamada uma vez no boot e explicitamente pelos testes. Devolve `None` — o modo
    aberto — quando qualquer uma das duas variáveis está ausente ou vazia: exigir
    usuário sem senha, ou senha sem usuário, seria uma meia-autenticação pior que
    nenhuma, porque pareceria protegida.
    """
    global _credencial, _lida

    usuario = (os.getenv("ADMIN_USER") or "").strip()
    senha = os.getenv("ADMIN_PASSWORD") or ""

    _lida = True
    if not usuario or not senha:
        _credencial = None
        return None

    salt = secrets.token_bytes(16)
    _credencial = Credencial(
        usuario=usuario,
        salt=salt,
        digest=_derivar(senha, salt),
        # Calculada AQUI, com a senha ainda em mãos, e estável entre boots.
        chave_de_sessao=_chave_de_sessao(usuario, senha),
    )

    # A partir daqui a senha não existe mais neste processo. `del` no environ também
    # a remove do ambiente herdado por qualquer subprocesso.
    os.environ.pop("ADMIN_PASSWORD", None)
    os.environ.pop("APP_ADMIN_PASSWORD", None)
    del senha

    return _credencial


def credencial() -> Credencial | None:
    """A credencial ativa, ou `None` quando o login não está configurado."""
    if not _lida:
        redefinir_credenciais()
    return _credencial


def login_configurado() -> bool:
    return credencial() is not None


# ─── a sessão assinada ───────────────────────────────────────────────────────


def _b64(dados: bytes) -> str:
    return base64.urlsafe_b64encode(dados).decode("ascii").rstrip("=")


def _desb64(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def emitir_sessao(cred: Credencial, agora: float | None = None) -> str:
    exp = int((agora if agora is not None else time.time()) + VALIDADE_S)
    corpo = f"{cred.usuario}|{exp}".encode("utf-8")
    assinatura = hmac.new(cred.chave_de_sessao, corpo, hashlib.sha256).digest()
    return f"{_b64(corpo)}.{_b64(assinatura)}"


def sessao_valida(token: str | None, agora: float | None = None) -> bool:
    """Verifica assinatura **antes** de olhar o conteúdo, e nunca levanta.

    Um cookie é entrada de rede: qualquer coisa pode chegar aqui, e o caminho de
    rejeição precisa ser o mesmo para lixo, para assinatura errada e para expirado.
    """
    cred = credencial()
    if cred is None or not token:
        return False
    try:
        parte_corpo, _, parte_sig = token.partition(".")
        if not parte_sig:
            return False
        corpo = _desb64(parte_corpo)
        esperada = hmac.new(cred.chave_de_sessao, corpo, hashlib.sha256).digest()
        if not hmac.compare_digest(_desb64(parte_sig), esperada):
            return False
        usuario, _, exp = corpo.decode("utf-8").rpartition("|")
        if usuario != cred.usuario:
            return False
        return int(exp) > (agora if agora is not None else time.time())
    except Exception:  # noqa: BLE001 - entrada de rede: rejeita, não explode
        return False


def _gravar_cookie(resposta: Response, token: str) -> None:
    resposta.set_cookie(
        COOKIE_SESSAO,
        token,
        max_age=VALIDADE_S,
        httponly=True,
        samesite="strict",
        secure=not _dev(),
        path="/",
    )


# ─── a porta ─────────────────────────────────────────────────────────────────


def autorizado_para_operacao(*, sessao: str | None, token: str | None) -> bool:
    """A REGRA, num lugar só — porque duas cópias de uma regra de autorização divergem.

    Elas divergiram: o WebSocket `/api/events` reimplementava a checagem e só sabia
    olhar `ADMIN_TOKEN`. Como `admin_exigido` é `admin_token is not None`, a
    configuração recomendada para navegador (`ADMIN_USER`/`ADMIN_PASSWORD`, sem token)
    deixava aquele socket **aberto para anônimos** — e por ele saíam os
    `conversation_id` dos handoffs, que `docs/SEGURANCA.md` trata como capacidade.

    `exigir_admin` (HTTP) e o WebSocket agora chamam esta função. O transporte muda
    de onde vêm os dois valores; a decisão não muda com o transporte.
    """
    from app.config import get_settings

    cfg = get_settings()
    token_ok = cfg.admin_exigido and hmac.compare_digest(
        (token or "").encode("utf-8"), (cfg.admin_token or "").encode("utf-8")
    )
    if login_configurado():
        return sessao_valida(sessao) or token_ok
    if cfg.admin_exigido:
        return token_ok
    # Nenhum dos dois configurados: instalação aberta, e o boot avisa no log.
    return True


def exigir_admin(
    autoseguro_sessao: str | None = Cookie(default=None),
    x_admin_token: str | None = Header(default=None),
) -> None:
    """A dependência das rotas de operação. **Três modos, nesta ordem:**

    1. `ADMIN_USER` + `ADMIN_PASSWORD` definidos ⇒ exige sessão válida (ou, para
       máquina, o `ADMIN_TOKEN` quando este também estiver definido);
    2. só `ADMIN_TOKEN` definido ⇒ o comportamento de sempre (CLAUDE.md 14c);
    3. nenhum dos dois ⇒ aberto, e o boot avisa no log.

    O token continua valendo com o login ligado porque ele é o caminho de CI e de
    `curl`: tirá-lo quebraria automação para não ganhar nada — quem tem o token já
    teria acesso pelos dois caminhos de qualquer forma.
    """
    if autorizado_para_operacao(sessao=autoseguro_sessao, token=x_admin_token):
        return
    # A mensagem distingue os dois modos porque o operador precisa saber o que fazer:
    # entrar de novo é uma ação, conferir um token é outra.
    detalhe = (
        "sessão de operação ausente ou expirada"
        if login_configurado()
        else "token de admin inválido ou ausente"
    )
    raise HTTPException(status_code=401, detail=detalhe)


# ─── as rotas ────────────────────────────────────────────────────────────────


class Entrada(BaseModel):
    usuario: str = Field(max_length=200)
    senha: str = Field(max_length=1024)


class EstadoAuth(BaseModel):
    """O que a tela precisa saber antes de decidir se mostra o login.

    Nunca inclui o nome do usuário configurado: quem ainda não entrou não tem por que
    receber metade da credencial de presente.
    """

    exigido: bool
    autenticado: bool


def registrar_autenticacao(app: FastAPI) -> None:
    """Monta as três rotas.

    **`include_in_schema=False` é deliberado**, pelo mesmo motivo de `GET /`: o
    `docs/openapi.yaml` foi congelado na Fase 0 como o contrato do produto, e
    `tests/nucleo/test_contrato_openapi.py` o defende nos dois sentidos. Estas rotas
    não são produto — são o mecanismo pelo qual um humano alcança o produto, e
    reabrir o congelado para acomodá-las trocaria uma decisão escrita por um conserto
    de teste.

    Para que a exclusão não vire uma porta aberta, ela é **nominal e fechada**:
    `ROTAS_FORA_DO_CONTRATO` lista exatamente estas três, e `tests/nucleo/test_auth.py`
    falha se aparecer uma quarta rota escondida do schema.
    """

    @app.get("/api/auth/estado", include_in_schema=False, response_model=EstadoAuth)
    def estado(autoseguro_sessao: str | None = Cookie(default=None)) -> EstadoAuth:
        return EstadoAuth(
            exigido=login_configurado(),
            autenticado=(not login_configurado()) or sessao_valida(autoseguro_sessao),
        )

    @app.post("/api/auth/login", include_in_schema=False, status_code=204)
    def login(corpo: Entrada, resposta: Response) -> Response:
        cred = credencial()
        if cred is None:
            # Sem login configurado não há o que autenticar — e responder 200 aqui
            # faria a tela acreditar numa sessão que não existe.
            raise HTTPException(status_code=404, detail="esta instalação não exige login")

        if not cred.confere(corpo.usuario, corpo.senha):
            # Só o nome entra no log, e ainda assim truncado. A senha não é logada em
            # lugar nenhum, nem em `debug`, nem no corpo da resposta — é o que
            # `test_auth.py` verifica, porque "não logar senha" é uma promessa que
            # ninguém quebra de propósito e todo mundo quebra por descuido.
            log.warning("tentativa de login recusada para %r", corpo.usuario[:32])
            raise HTTPException(status_code=401, detail=FALHA)

        _gravar_cookie(resposta, emitir_sessao(cred))
        resposta.status_code = 204
        return resposta

    @app.post("/api/auth/logout", include_in_schema=False, status_code=204)
    def logout(resposta: Response) -> Response:
        # Os mesmos atributos da gravação: um `delete_cookie` com `path` ou `samesite`
        # diferentes deixa o cookie original vivo no navegador.
        resposta.delete_cookie(
            COOKIE_SESSAO, path="/", httponly=True, samesite="strict", secure=not _dev()
        )
        resposta.status_code = 204
        return resposta


def aviso_de_boot() -> str | None:
    """A frase que o `lifespan` registra. `None` quando há alguma proteção ativa."""
    from app.config import get_settings

    if login_configurado():
        return None
    if get_settings().admin_exigido:
        return None
    return (
        "Sem ADMIN_USER/ADMIN_PASSWORD e sem ADMIN_TOKEN: /api/* está sem "
        "autenticação. A proteção efetiva é o bind em 127.0.0.1 do "
        "docker-compose.yml. Defina ADMIN_USER e ADMIN_PASSWORD para exigir login, "
        "ou ADMIN_TOKEN para exigir o cabeçalho X-Admin-Token."
    )
