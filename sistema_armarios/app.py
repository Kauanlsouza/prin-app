import csv
import hmac
import io
import json
import os
import socket
import smtplib
import atexit
import secrets
import sqlite3
import tempfile
import time
from datetime import datetime, timedelta
from email.message import EmailMessage
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from database import (
    atualizar_emprestimo_ativo,
    anonimizar_historico_ate,
    autenticar_funcionario,
    consultar_armario_flexivel,
    contar_armarios_por_status,
    criar_armarios,
    criar_backup,
    criar_funcionario,
    criar_primeiro_funcionario,
    criar_banco,
    definir_manutencao_armario,
    devolver_armario,
    emprestar_armario,
    listar_armarios_detalhados,
    listar_auditoria,
    listar_armarios_livres,
    listar_atrasados,
    listar_historico_emprestimos,
    listar_funcionarios,
    normalizar_tipo_armario,
    registrar_auditoria,
    tem_funcionarios,
    validar_numero_armario,
)


BASE_DIR = Path(__file__).resolve().parent
INDEX_FILE = BASE_DIR / "index.html"
LOGIN_FILE = BASE_DIR / "login.html"
FAVICON_FILE = BASE_DIR / "static" / "favicon.jpg"
STATIC_DIR = BASE_DIR / "static"
PAGE_FILES = {
    "inicio": INDEX_FILE,
    "movimentacoes": BASE_DIR / "movimentacoes.html",
    "consulta": BASE_DIR / "consulta.html",
    "disponibilidade": BASE_DIR / "disponibilidade.html",
    "historico": BASE_DIR / "historico.html",
    "configuracoes": BASE_DIR / "configuracoes.html",
}
CONFIG_FILE = BASE_DIR / "configuracoes.json"
BACKUP_DIR = BASE_DIR / "backups"
LOCK_FILE = BASE_DIR / ".app.lock"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 5000
DATE_FORMAT = "%d/%m/%Y"
DATE_INPUT_FORMAT = "%Y-%m-%d"
HISTORICO_ORDENACOES_VALIDAS = {
    "armario",
    "tipo",
    "localizacao",
    "tamanho",
    "participante_1",
    "participante_2",
    "participante_3",
    "retirada",
    "prevista",
    "devolucao",
    "status",
}
CONFIGURACOES_PADRAO = {
    "email_assunto": "Devolucao em atraso - {armario}",
    "email_corpo": (
        "Ola {nome},\n\n"
        "identificamos que o {armario} esta com devolucao prevista para {prazo}.\n"
        "Localizacao: {localizacao}.\n\n"
        "Pedimos a regularizacao o quanto antes.\n\n"
        "Equipe de armarios"
    ),
}
SERVER_LOCK_HANDLE = None
SESSIONS = {}
TENTATIVAS_LOGIN = {}
SESSION_DURATION_SECONDS = 8 * 60 * 60
MAX_JSON_BYTES = 1_048_576
PAGE_ROUTES = {
    "/": {"page": "inicio", "title": "Sistema de Armarios"},
    "/index.html": {"page": "inicio", "title": "Sistema de Armarios"},
    "/movimentacoes.html": {"page": "movimentacoes", "title": "Movimentacoes | Sistema de Armarios"},
    "/consulta.html": {"page": "consulta", "title": "Consulta | Sistema de Armarios"},
    "/disponibilidade.html": {"page": "disponibilidade", "title": "Disponibilidade | Sistema de Armarios"},
    "/historico.html": {"page": "historico", "title": "Historico | Sistema de Armarios"},
    "/configuracoes.html": {"page": "configuracoes", "title": "Configuracoes | Sistema de Armarios"},
}

try:
    import msvcrt
except ImportError:  # pragma: no cover - ambiente Windows no uso real
    msvcrt = None


def carregar_dotenv(caminho):
    if not caminho.is_file():
        return

    for linha in caminho.read_text(encoding="utf-8").splitlines():
        conteudo = linha.strip()
        if not conteudo or conteudo.startswith("#") or "=" not in conteudo:
            continue

        chave, valor = conteudo.split("=", 1)
        chave = chave.strip()
        valor = valor.strip().strip('"').strip("'")
        if chave and chave not in os.environ:
            os.environ[chave] = valor


carregar_dotenv(BASE_DIR / ".env")

# Por padrao o sistema fica disponivel para os dispositivos da mesma rede.
# Use APP_HOST=127.0.0.1 no arquivo .env caso seja necessario restringi-lo
# novamente apenas a esta maquina.
HOST = str(os.getenv("APP_HOST", DEFAULT_HOST)).strip() or DEFAULT_HOST
try:
    PORT = int(str(os.getenv("APP_PORT", DEFAULT_PORT)).strip())
except ValueError as exc:
    raise RuntimeError("APP_PORT deve ser um numero inteiro valido.") from exc

if not 1 <= PORT <= 65535:
    raise RuntimeError("APP_PORT deve estar entre 1 e 65535.")


def adquirir_bloqueio_servidor():
    global SERVER_LOCK_HANDLE
    if msvcrt is None:
        return

    lock = open(LOCK_FILE, "a+b")
    try:
        lock.seek(0)
        if not lock.read(1):
            lock.seek(0)
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError as exc:
        lock.close()
        raise RuntimeError(
            "Ja existe uma instancia do app.py em execucao. Feche a anterior antes de iniciar outra."
        ) from exc

    lock.seek(0)
    lock.truncate()
    lock.write(str(os.getpid()).encode("ascii"))
    lock.flush()
    SERVER_LOCK_HANDLE = lock


def liberar_bloqueio_servidor():
    global SERVER_LOCK_HANDLE
    if SERVER_LOCK_HANDLE is None or msvcrt is None:
        return

    try:
        SERVER_LOCK_HANDLE.seek(0)
        msvcrt.locking(SERVER_LOCK_HANDLE.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        pass
    try:
        SERVER_LOCK_HANDLE.close()
    finally:
        SERVER_LOCK_HANDLE = None


def renderizar_index(page_key="inicio", page_title="Sistema de Armarios"):
    html = INDEX_FILE.read_text(encoding="utf-8")
    html = html.replace("<title>Sistema de Armarios</title>", f"<title>{page_title}</title>", 1)
    payload = (
        "<script>"
        f"window.APP_PAGE = {json.dumps(page_key, ensure_ascii=False)};"
        "</script>"
    )
    return html.replace("</head>", f"{payload}\n</head>", 1).encode("utf-8")


def resolver_pagina_por_caminho(caminho):
    page_config = PAGE_ROUTES.get(caminho)
    if page_config:
        return page_config

    if caminho.endswith(".html"):
        nome = Path(caminho).name.lower()
        page_key = nome[:-5] if nome.endswith(".html") else nome
        if page_key in PAGE_FILES:
            return {"page": page_key, "title": f"{page_key.title()} | Sistema de Armarios"}

    return None


def hoje():
    return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)


def json_response(handler, status, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def resposta_ok(handler, payload, status=HTTPStatus.OK):
    json_response(handler, status, {"ok": True, **payload})


def resposta_erro(handler, mensagem, status=HTTPStatus.BAD_REQUEST):
    json_response(handler, status, {"ok": False, "mensagem": mensagem})


def texto_limpo(valor):
    if valor is None or isinstance(valor, bool):
        return ""
    return str(valor).strip()


def normalizar_data(data_str):
    valor = texto_limpo(data_str)
    if not valor:
        return ""

    for formato in (DATE_FORMAT, DATE_INPUT_FORMAT):
        try:
            return datetime.strptime(valor, formato).strftime(DATE_FORMAT)
        except ValueError:
            continue

    raise ValueError("Data invalida. Use DD/MM/AAAA.")


def validar_data_prevista(data_prevista):
    dt_prevista = datetime.strptime(data_prevista, DATE_FORMAT)
    if dt_prevista < hoje():
        raise ValueError("A data prevista nao pode ser no passado.")


def validar_intervalo_datas(data_inicio, data_fim):
    if not data_inicio or not data_fim:
        return

    if datetime.strptime(data_inicio, DATE_FORMAT) > datetime.strptime(data_fim, DATE_FORMAT):
        raise ValueError("A data inicial nao pode ser maior que a data final.")


def esta_atrasado(data_prevista):
    if not data_prevista:
        return False

    try:
        return datetime.strptime(data_prevista, DATE_FORMAT) < hoje()
    except ValueError:
        return False


def classificar_vencimento(data_prevista):
    if not data_prevista:
        return "sem_prazo"

    try:
        data = datetime.strptime(data_prevista, DATE_FORMAT)
    except ValueError:
        return "sem_prazo"

    diferenca = (data - hoje()).days
    if diferenca < 0:
        return "atrasado"
    if diferenca == 0:
        return "vence_hoje"
    if diferenca == 1:
        return "vence_amanha"
    return "no_prazo"


def parse_numero(valor, mensagem="Numero invalido."):
    if isinstance(valor, bool):
        raise ValueError(mensagem)
    try:
        return int(valor)
    except (TypeError, ValueError) as exc:
        raise ValueError(mensagem) from exc


def parse_bool(valor):
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, (int, float)):
        return bool(valor)
    texto = str(valor or "").strip().lower()
    return texto in {"1", "true", "yes", "on", "sim"}


def parse_tipo_armario(valor):
    try:
        return normalizar_tipo_armario(valor)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc


def validar_numero_por_tipo(tipo_armario, numero):
    try:
        return validar_numero_armario(tipo_armario, numero)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc


def campos_faltando(dados, obrigatorios):
    return [campo for campo in obrigatorios if not texto_limpo(dados.get(campo, ""))]


def extrair_participantes(dados):
    participantes = dados.get("participantes")
    if isinstance(participantes, list):
        return participantes

    if any(texto_limpo(dados.get(campo, "")) for campo in ("nome", "email", "prontuario", "curso")):
        return [
            {
                "nome": dados.get("nome", ""),
                "email": dados.get("email", ""),
                "prontuario": dados.get("prontuario", ""),
                "curso": dados.get("curso", ""),
            }
        ]

    return []


def ler_bool_env(nome, padrao=False):
    valor = os.getenv(nome)
    if valor is None:
        return padrao
    return str(valor).strip().lower() in {"1", "true", "yes", "on", "sim"}


def smtp_configurado():
    return bool(str(os.getenv("SMTP_HOST", "")).strip() and str(os.getenv("SMTP_FROM_EMAIL", "")).strip())


def senha_cadastro_configurada():
    # A senha compartilhada permite novos cadastros mesmo sem uma configuracao
    # previa de um administrador. A variavel de ambiente continua sendo opcional
    # para quem quiser substitui-la em outra instalacao.
    return str(os.getenv("CADASTRO_SENHA_ADM", "armarios"))


def _normalizar_configuracoes_payload(payload):
    payload = payload or {}
    assunto = str(payload.get("email_assunto", "")).strip() or CONFIGURACOES_PADRAO["email_assunto"]
    corpo = str(payload.get("email_corpo", "")).strip() or CONFIGURACOES_PADRAO["email_corpo"]
    return {
        "email_assunto": assunto,
        "email_corpo": corpo,
    }


def carregar_configuracoes():
    if not CONFIG_FILE.is_file():
        return dict(CONFIGURACOES_PADRAO)

    try:
        bruto = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(CONFIGURACOES_PADRAO)

    if not isinstance(bruto, dict):
        return dict(CONFIGURACOES_PADRAO)

    return _normalizar_configuracoes_payload(bruto)


def salvar_configuracoes(payload):
    configuracoes = _normalizar_configuracoes_payload(payload)
    CONFIG_FILE.write_text(
        json.dumps(configuracoes, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return configuracoes


def csv_response(handler, filename, rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    for row in rows:
        writer.writerow([_proteger_celula_csv(valor) for valor in row])
    body = buffer.getvalue().encode("utf-8-sig")
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", "text/csv; charset=utf-8")
    handler.send_header("Content-Disposition", f'attachment; filename="{filename}"')
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _proteger_celula_csv(valor):
    """Evita que planilhas interpretem dados cadastrados como formulas."""
    texto = "" if valor is None else str(valor)
    return f"'{texto}" if texto.lstrip().startswith(("=", "+", "-", "@")) else texto


def obter_config_email():
    host = str(os.getenv("SMTP_HOST", "")).strip()
    from_email = str(os.getenv("SMTP_FROM_EMAIL", "")).strip()
    from_name = str(os.getenv("SMTP_FROM_NAME", "")).strip() or "Sistema de Armarios"
    username = str(os.getenv("SMTP_USERNAME", "")).strip()
    password = os.getenv("SMTP_PASSWORD", "")
    port_raw = str(os.getenv("SMTP_PORT", "587")).strip()
    use_ssl = ler_bool_env("SMTP_USE_SSL", False)
    use_tls = ler_bool_env("SMTP_USE_TLS", not use_ssl)

    if not host or not from_email:
        raise ValueError(
            "Envio de email nao configurado. Defina SMTP_HOST e SMTP_FROM_EMAIL nas variaveis de ambiente."
        )

    try:
        port = int(port_raw)
    except ValueError as exc:
        raise ValueError("SMTP_PORT invalido.") from exc

    return {
        "host": host,
        "port": port,
        "username": username,
        "password": password,
        "from_email": from_email,
        "from_name": from_name,
        "use_ssl": use_ssl,
        "use_tls": use_tls,
    }


def enviar_email(destinatario, assunto, corpo):
    config = obter_config_email()
    mensagem = EmailMessage()
    mensagem["Subject"] = assunto
    mensagem["From"] = f'{config["from_name"]} <{config["from_email"]}>'
    mensagem["To"] = destinatario
    mensagem.set_content(corpo)

    smtp_cls = smtplib.SMTP_SSL if config["use_ssl"] else smtplib.SMTP
    with smtp_cls(config["host"], config["port"], timeout=20) as servidor:
        servidor.ehlo()
        if not config["use_ssl"] and config["use_tls"]:
            servidor.starttls()
            servidor.ehlo()
        if config["username"]:
            servidor.login(config["username"], config["password"])
        servidor.send_message(mensagem)


def renderizar_template_email(template, participante, armario):
    valores = {
        "{nome}": participante.get("nome") or "responsavel",
        "{armario}": armario.get("identificacao") or "armario",
        "{prazo}": armario.get("data_prevista") or "-",
        "{localizacao}": armario.get("localizacao") or "-",
        "{tipo}": armario.get("tipo_rotulo") or "armario",
        "{curso}": participante.get("curso") or "-",
        "{email}": participante.get("email") or "-",
    }
    conteudo = str(template or "")
    for marcador, valor in valores.items():
        conteudo = conteudo.replace(marcador, str(valor))
    return conteudo


def enviar_cobranca_armario(armario, assunto_template="", corpo_template=""):
    participantes = [
        participante
        for participante in (armario.get("participantes") or [])
        if str(participante.get("email", "")).strip()
    ]
    if not participantes:
        raise ValueError("Nao ha emails cadastrados para este armario.")

    configuracoes = carregar_configuracoes()
    assunto_base = str(assunto_template or configuracoes["email_assunto"]).strip()
    corpo_base = str(corpo_template or configuracoes["email_corpo"]).strip()
    enviados = 0

    for participante in participantes:
        assunto = renderizar_template_email(assunto_base, participante, armario)
        corpo = renderizar_template_email(corpo_base, participante, armario)
        enviar_email(participante["email"], assunto, corpo)
        enviados += 1

    return enviados


def enriquecer_armario(item):
    return {
        **item,
        "atrasado": esta_atrasado(item.get("data_prevista")),
        "vencimento": classificar_vencimento(item.get("data_prevista")),
    }


def formatar_consulta(resultado):
    if not resultado:
        return None
    return enriquecer_armario(resultado)


def normalizar_inteiro_param(valor, padrao, minimo=1, maximo=500):
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        return padrao
    return max(minimo, min(numero, maximo))


def normalizar_ordenacao_historico(valor):
    campo = str(valor or "").strip().lower()
    return campo if campo in HISTORICO_ORDENACOES_VALIDAS else "retirada"


def normalizar_direcao_historico(valor):
    return "asc" if str(valor or "").strip().lower() == "asc" else "desc"


def _valor_data_ordenacao(valor, vazio_ao_final=True):
    if not valor:
        return (1 if vazio_ao_final else -1, datetime.max)
    try:
        return (0, datetime.strptime(valor, DATE_FORMAT))
    except ValueError:
        return (1 if vazio_ao_final else -1, datetime.max)


def _valor_texto_ordenacao(valor):
    return str(valor or "").strip().lower()


def _participante_por_indice(item, indice):
    participantes = item.get("participantes") or []
    return participantes[indice] if indice < len(participantes) else {}


def _ordem_tipo_item(item):
    return 0


def _chave_ordenacao_historico(item, campo):
    if campo == "armario":
        return (_ordem_tipo_item(item), int(item.get("numero") or 0))
    if campo == "tipo":
        return (_ordem_tipo_item(item), int(item.get("numero") or 0))
    if campo == "localizacao":
        return (_valor_texto_ordenacao(item.get("localizacao")), int(item.get("numero") or 0))
    if campo == "tamanho":
        return (_valor_texto_ordenacao(item.get("tamanho")), int(item.get("numero") or 0))
    if campo == "participante_1":
        participante = _participante_por_indice(item, 0)
        return _valor_texto_ordenacao(participante.get("nome") or item.get("nome"))
    if campo == "participante_2":
        return _valor_texto_ordenacao(_participante_por_indice(item, 1).get("nome"))
    if campo == "participante_3":
        return _valor_texto_ordenacao(_participante_por_indice(item, 2).get("nome"))
    if campo == "prevista":
        return _valor_data_ordenacao(item.get("data_prevista"))
    if campo == "devolucao":
        return _valor_data_ordenacao(item.get("data_devolucao"))
    if campo == "status":
        return (_valor_texto_ordenacao(item.get("status")), _valor_data_ordenacao(item.get("data_retirada")))
    return _valor_data_ordenacao(item.get("data_retirada"))


def preparar_historico(params, paginar=True):
    try:
        data_inicio_raw = params.get("data_inicio", [""])[0]
        data_fim_raw = params.get("data_fim", [""])[0]
        data_inicio = normalizar_data(data_inicio_raw) if data_inicio_raw else ""
        data_fim = normalizar_data(data_fim_raw) if data_fim_raw else ""
        validar_intervalo_datas(data_inicio, data_fim)
        tipo_armario = params.get("tipo_armario", [""])[0].strip()
        if tipo_armario:
            tipo_armario = parse_tipo_armario(tipo_armario)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc

    ordenacao = normalizar_ordenacao_historico(params.get("ordenar_por", ["retirada"])[0])
    direcao = normalizar_direcao_historico(params.get("direcao", ["desc"])[0])
    por_pagina = normalizar_inteiro_param(params.get("por_pagina", ["10"])[0], 10, minimo=1, maximo=100)
    pagina = normalizar_inteiro_param(params.get("pagina", ["1"])[0], 1, minimo=1, maximo=9999)

    historico = listar_historico_emprestimos(
        nome=params.get("nome", [""])[0].strip(),
        prontuario=params.get("prontuario", [""])[0].strip(),
        status=params.get("status", [""])[0].strip(),
        data_inicio=data_inicio,
        data_fim=data_fim,
        tipo_armario=tipo_armario,
    )
    historico_ordenado = sorted(
        historico,
        key=lambda item: _chave_ordenacao_historico(item, ordenacao),
        reverse=direcao == "desc",
    )
    resumo = {
        "total": len(historico_ordenado),
        "ativos": sum(1 for item in historico_ordenado if item.get("status") == "ativo"),
        "devolvidos": sum(1 for item in historico_ordenado if item.get("status") == "devolvido"),
        "atrasados": sum(
            1
            for item in historico_ordenado
            if item.get("status") == "ativo" and esta_atrasado(item.get("data_prevista"))
        ),
    }

    total_itens = len(historico_ordenado)
    total_paginas = max(1, (total_itens + por_pagina - 1) // por_pagina)
    pagina = min(pagina, total_paginas)

    if not paginar:
        return {
            "historico": historico_ordenado,
            "resumo": resumo,
            "paginacao": {
                "pagina": 1,
                "por_pagina": total_itens or por_pagina,
                "total_itens": total_itens,
                "total_paginas": 1,
            },
            "ordenacao": {"campo": ordenacao, "direcao": direcao},
        }

    inicio = (pagina - 1) * por_pagina
    fim = inicio + por_pagina
    return {
        "historico": historico_ordenado[inicio:fim],
        "resumo": resumo,
        "paginacao": {
            "pagina": pagina,
            "por_pagina": por_pagina,
            "total_itens": total_itens,
            "total_paginas": total_paginas,
        },
        "ordenacao": {"campo": ordenacao, "direcao": direcao},
    }


def montar_agenda_devolucoes():
    agenda = {
        "vence_hoje": [],
        "vence_amanha": [],
        "proximos_7_dias": [],
    }
    base = hoje()
    limite = base + timedelta(days=7)

    for item in listar_armarios_detalhados():
        if item.get("status") != "ocupado" or not item.get("data_prevista"):
            continue
        try:
            data_prevista = datetime.strptime(item["data_prevista"], DATE_FORMAT)
        except ValueError:
            continue
        if data_prevista < base or data_prevista > limite:
            continue

        item_enriquecido = enriquecer_armario(item)
        diferenca = (data_prevista - base).days
        if diferenca == 0:
            agenda["vence_hoje"].append(item_enriquecido)
        elif diferenca == 1:
            agenda["vence_amanha"].append(item_enriquecido)
        else:
            agenda["proximos_7_dias"].append(item_enriquecido)

    for chave in agenda:
        agenda[chave].sort(
            key=lambda item: (
                datetime.strptime(item["data_prevista"], DATE_FORMAT),
                int(item.get("numero") or 0),
            )
        )

    return agenda


class ArmariosHandler(BaseHTTPRequestHandler):
    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        super().end_headers()

    def _rota_normalizada(self):
        caminho = urlparse(self.path).path.strip()
        if not caminho:
            return "/"
        if caminho != "/" and caminho.endswith("/"):
            caminho = caminho.rstrip("/")
        if caminho == "/api":
            return "/"
        if caminho.startswith("/api/"):
            return caminho[4:]
        return caminho

    def do_OPTIONS(self):
        # A aplicacao e servida no mesmo dominio. Nao habilite CORS aberto,
        # pois ele permitiria que outros sites tentassem chamar a API local.
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def do_GET(self):
        rota = urlparse(self.path)
        caminho = self._rota_normalizada()
        params = parse_qs(rota.query)

        if caminho == "/login":
            if self._funcionario_logado():
                self._redirecionar("/")
            else:
                self._servir_login()
            return

        if caminho == "/favicon.jpg":
            self._servir_favicon()
            return

        if caminho.startswith("/static/"):
            self._servir_arquivo_estatico(caminho)
            return

        if caminho == "/sessao":
            funcionario = self._funcionario_logado()
            if not funcionario:
                resposta_erro(self, "Sessao expirada. Entre novamente.", HTTPStatus.UNAUTHORIZED)
                return
            resposta_ok(self, {"funcionario": funcionario})
            return

        if caminho == "/primeiro-acesso":
            resposta_ok(self, {"tem_funcionarios": tem_funcionarios()})
            return

        if not self._funcionario_logado():
            if caminho in PAGE_ROUTES:
                self._redirecionar("/login")
            else:
                resposta_erro(self, "Sessao expirada. Entre novamente.", HTTPStatus.UNAUTHORIZED)
            return

        page_config = PAGE_ROUTES.get(caminho)
        if page_config:
            self._servir_index(page_config["page"], page_config["title"])
            return

        if caminho == "/resumo":
            resumo = contar_armarios_por_status()
            agenda = montar_agenda_devolucoes()
            resumo["atrasados"] = len(listar_atrasados())
            resumo["vence_hoje"] = len(agenda["vence_hoje"])
            resumo["vence_amanha"] = len(agenda["vence_amanha"])
            resumo["proximos_7_dias"] = len(agenda["proximos_7_dias"])
            total_armarios = resumo["convencional_total"]
            indisponiveis = resumo["ocupado"] + resumo["manutencao"]
            resumo["ocupacao_percentual"] = round((indisponiveis / total_armarios) * 100, 1) if total_armarios else 0
            resposta_ok(self, {"resumo": resumo, "agenda": agenda})
            return

        if caminho == "/armarios":
            armarios = [enriquecer_armario(item) for item in listar_armarios_detalhados()]
            resposta_ok(self, {"armarios": armarios})
            return

        if caminho == "/agenda-devolucoes":
            resposta_ok(self, {"agenda": montar_agenda_devolucoes()})
            return

        if caminho == "/armarios/livres":
            tipo_armario = params.get("tipo_armario", [""])[0].strip()
            livres = listar_armarios_livres(tipo_armario=tipo_armario)
            resposta_ok(self, {"armarios": [enriquecer_armario(item) for item in livres]})
            return

        if caminho == "/atrasados":
            resposta_ok(self, {"atrasados": [enriquecer_armario(item) for item in listar_atrasados()]})
            return

        if caminho == "/consultar":
            self._consultar(params)
            return

        if caminho == "/historico":
            self._historico(params)
            return

        if caminho == "/historico/csv":
            self._historico_csv(params)
            return

        if caminho == "/configuracoes":
            if not self._administrador_logado():
                return
            self._configuracoes()
            return

        if caminho == "/funcionarios":
            if not self._administrador_logado():
                return
            resposta_ok(self, {"funcionarios": listar_funcionarios()})
            return

        if caminho == "/auditoria":
            if not self._administrador_logado():
                return
            resposta_ok(self, {"eventos": listar_auditoria()})
            return

        if caminho == "/backup":
            if not self._administrador_logado():
                return
            self._baixar_backup()
            return

        resposta_erro(self, "Rota nao encontrada.", HTTPStatus.NOT_FOUND)

    def do_POST(self):
        caminho = self._rota_normalizada()

        if caminho == "/login":
            self._login()
            return
        if caminho == "/primeiro-acesso":
            self._criar_primeiro_acesso()
            return
        if caminho == "/cadastro":
            self._cadastrar_acesso()
            return
        if caminho == "/logout":
            self._logout()
            return

        funcionario = self._funcionario_logado()
        if not funcionario:
            resposta_erro(self, "Sessao expirada. Entre novamente.", HTTPStatus.UNAUTHORIZED)
            return

        if caminho == "/emprestar":
            self._emprestar()
            return

        if caminho == "/devolver":
            self._devolver()
            return

        if caminho == "/manutencao":
            self._alterar_manutencao()
            return

        if caminho == "/emprestimo/atualizar":
            self._atualizar_emprestimo()
            return

        if caminho == "/backup/restaurar":
            if not self._administrador_logado():
                return
            self._restaurar_backup()
            return

        if caminho == "/configuracoes":
            if not self._administrador_logado():
                return
            self._salvar_configuracoes()
            return

        if caminho == "/funcionarios":
            if not self._administrador_logado():
                return
            self._criar_funcionario()
            return

        if caminho == "/cobrar-email":
            if not self._administrador_logado():
                return
            self._cobrar_email()
            return

        if caminho == "/privacidade/anonimizar":
            if not self._administrador_logado():
                return
            self._anonimizar_historico()
            return

        resposta_erro(self, "Rota nao encontrada.", HTTPStatus.NOT_FOUND)

    def _servir_index(self, page_key="inicio", page_title="Sistema de Armarios"):
        content = renderizar_index(page_key, page_title)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _servir_login(self):
        content = LOGIN_FILE.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _servir_favicon(self):
        content = FAVICON_FILE.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "public, max-age=604800")
        self.end_headers()
        self.wfile.write(content)

    def _servir_arquivo_estatico(self, caminho):
        """Entrega somente arquivos contidos em static, sem aceitar travessia de diretórios."""
        arquivo = (BASE_DIR / caminho.lstrip("/")).resolve()
        try:
            arquivo.relative_to(STATIC_DIR.resolve())
        except ValueError:
            resposta_erro(self, "Arquivo nao encontrado.", HTTPStatus.NOT_FOUND)
            return

        if not arquivo.is_file():
            resposta_erro(self, "Arquivo nao encontrado.", HTTPStatus.NOT_FOUND)
            return

        tipos = {
            ".css": "text/css; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".svg": "image/svg+xml",
        }
        content = arquivo.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", tipos.get(arquivo.suffix.lower(), "application/octet-stream"))
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "public, max-age=604800")
        self.end_headers()
        self.wfile.write(content)

    def _redirecionar(self, destino):
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", destino)
        self.end_headers()

    def _funcionario_logado(self):
        try:
            agora = time.time()
            for token_expirado, sessao_expirada in list(SESSIONS.items()):
                if sessao_expirada["expira_em"] < agora:
                    SESSIONS.pop(token_expirado, None)
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            token = cookie.get("armarios_session")
            if not token:
                return None
            sessao = SESSIONS.get(token.value)
            if not sessao or sessao["expira_em"] < agora:
                if sessao:
                    SESSIONS.pop(token.value, None)
                return None
            return sessao["funcionario"]
        except (KeyError, ValueError):
            return None

    def _administrador_logado(self):
        funcionario = self._funcionario_logado()
        if not funcionario or funcionario.get("papel") != "administrador":
            resposta_erro(self, "Esta acao exige uma conta de administrador.", HTTPStatus.FORBIDDEN)
            return False
        return True

    def _login(self):
        dados = self._read_json()
        if dados is None:
            return
        endereco = self.client_address[0]
        agora = time.time()
        tentativas = [t for t in TENTATIVAS_LOGIN.get(endereco, []) if t > agora - 15 * 60]
        if len(tentativas) >= 5:
            resposta_erro(self, "Muitas tentativas. Aguarde 15 minutos antes de tentar novamente.", HTTPStatus.TOO_MANY_REQUESTS)
            return
        funcionario = autenticar_funcionario(dados.get("usuario"), dados.get("senha"))
        if not funcionario:
            TENTATIVAS_LOGIN[endereco] = tentativas + [agora]
            resposta_erro(self, "Usuario ou senha invalidos.", HTTPStatus.UNAUTHORIZED)
            return
        TENTATIVAS_LOGIN.pop(endereco, None)
        token = secrets.token_urlsafe(32)
        SESSIONS[token] = {"funcionario": funcionario, "expira_em": time.time() + SESSION_DURATION_SECONDS}
        body = json.dumps({"ok": True, "funcionario": funcionario}, ensure_ascii=False).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Set-Cookie", f"armarios_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_DURATION_SECONDS}")
        self.end_headers()
        self.wfile.write(body)

    def _logout(self):
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        token = cookie.get("armarios_session")
        if token:
            SESSIONS.pop(token.value, None)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Set-Cookie", "armarios_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0")
        body = b'{"ok": true}'
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _criar_funcionario(self):
        dados = self._read_json()
        if dados is None:
            return
        try:
            criar_funcionario(
                dados.get("nome"), dados.get("usuario"), dados.get("senha"),
                dados.get("papel", "operador"), self._funcionario_logado(),
            )
        except ValueError as exc:
            resposta_erro(self, str(exc))
            return
        resposta_ok(self, {"mensagem": "Funcionario cadastrado com sucesso."})

    def _criar_primeiro_acesso(self):
        dados = self._read_json()
        if dados is None:
            return
        if dados.get("senha") != dados.get("senha_confirmacao"):
            resposta_erro(self, "As senhas nao coincidem.")
            return
        try:
            criar_primeiro_funcionario(dados.get("nome"), dados.get("usuario"), dados.get("senha"))
        except ValueError as exc:
            resposta_erro(self, str(exc), HTTPStatus.CONFLICT)
            return
        resposta_ok(self, {"mensagem": "Primeiro acesso criado. Entre com suas credenciais."}, HTTPStatus.CREATED)

    def _cadastrar_acesso(self):
        dados = self._read_json()
        if dados is None:
            return
        senha_adm = str(dados.get("senha_adm", ""))
        senha_configurada = senha_cadastro_configurada()
        if not hmac.compare_digest(senha_adm, senha_configurada):
            resposta_erro(self, "Senha de cadastro invalida.", HTTPStatus.FORBIDDEN)
            return
        try:
            if dados.get("senha") != dados.get("senha_confirmacao"):
                raise ValueError("As senhas nao coincidem.")
            criar_funcionario(dados.get("nome"), dados.get("usuario"), dados.get("senha"), "operador")
        except ValueError as exc:
            resposta_erro(self, str(exc))
            return
        resposta_ok(self, {"mensagem": "Conta criada. Entre com seu usuario e senha."}, HTTPStatus.CREATED)

    def _consultar(self, params):
        tipo_consulta = params.get("tipo", ["numero"])[0]
        valor = params.get("valor", [""])[0].strip()

        if not valor:
            resposta_erro(self, "Informe um valor para consulta.")
            return

        if tipo_consulta == "numero":
            try:
                tipo_armario = parse_tipo_armario(params.get("tipo_armario", [""])[0].strip())
                numero = validar_numero_por_tipo(tipo_armario, parse_numero(valor))
                resultado = consultar_armario_flexivel(numero, por_prontuario=False, tipo_armario=tipo_armario)
            except ValueError as exc:
                resposta_erro(self, str(exc))
                return
        elif tipo_consulta == "prontuario":
            resultado = consultar_armario_flexivel(valor, por_prontuario=True)
        else:
            resposta_erro(self, "Tipo de consulta invalido.")
            return

        if not resultado:
            resposta_ok(self, {"resultado": None, "mensagem": "Nenhuma ocupacao ativa encontrada."})
            return

        resposta_ok(self, {"resultado": formatar_consulta(resultado)})

    def _historico(self, params):
        try:
            historico_payload = preparar_historico(params, paginar=True)
        except ValueError as exc:
            resposta_erro(self, str(exc))
            return

        resposta_ok(self, historico_payload)

    def _historico_csv(self, params):
        try:
            historico_payload = preparar_historico(params, paginar=False)
        except ValueError as exc:
            resposta_erro(self, str(exc))
            return

        historico = historico_payload["historico"]
        rows = [
            [
                "Armario",
                "Tipo",
                "Numero",
                "Localizacao",
                "Tamanho",
                "Participante 1 Nome",
                "Participante 1 Email",
                "Participante 1 Prontuario",
                "Participante 1 Curso",
                "Participante 2 Nome",
                "Participante 2 Email",
                "Participante 2 Prontuario",
                "Participante 2 Curso",
                "Participante 3 Nome",
                "Participante 3 Email",
                "Participante 3 Prontuario",
                "Participante 3 Curso",
                "Retirada",
                "Prevista",
                "Devolucao",
                "Funcionario do emprestimo",
                "Funcionario da devolucao",
                "Status",
            ]
        ]
        for item in historico:
            participantes = list(item.get("participantes") or [])[:3]
            while len(participantes) < 3:
                participantes.append({})
            rows.append(
                [
                    item["identificacao"],
                    item["tipo_rotulo"],
                    item["numero"],
                    item["localizacao"],
                    "Grande" if item["tamanho"] == "grande" else "Padrao",
                    participantes[0].get("nome", ""),
                    participantes[0].get("email", ""),
                    participantes[0].get("prontuario", ""),
                    participantes[0].get("curso", ""),
                    participantes[1].get("nome", ""),
                    participantes[1].get("email", ""),
                    participantes[1].get("prontuario", ""),
                    participantes[1].get("curso", ""),
                    participantes[2].get("nome", ""),
                    participantes[2].get("email", ""),
                    participantes[2].get("prontuario", ""),
                    participantes[2].get("curso", ""),
                    item["data_retirada"],
                    item["data_prevista"],
                    item["data_devolucao"] or "",
                    item.get("funcionario_emprestimo", ""),
                    item.get("funcionario_devolucao", ""),
                    item["status"],
                ]
            )
        csv_response(self, "historico_armarios.csv", rows)

    def _baixar_backup(self):
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        arquivo = criar_backup(BACKUP_DIR / f"armarios_{timestamp}.db")
        conteudo = arquivo.read_bytes()
        registrar_auditoria("criou_backup", arquivo.name, self._funcionario_logado())
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Disposition", f'attachment; filename="{arquivo.name}"')
        self.send_header("Content-Length", str(len(conteudo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(conteudo)

    def _restaurar_backup(self):
        try:
            tamanho = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            resposta_erro(self, "Tamanho do arquivo invalido.", HTTPStatus.BAD_REQUEST)
            return
        if tamanho <= 0:
            resposta_erro(self, "Selecione um arquivo de backup .db.", HTTPStatus.BAD_REQUEST)
            return
        if tamanho > 512 * 1024 * 1024:
            resposta_erro(self, "O arquivo excede o limite de 512 MB.", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return

        conteudo = self.rfile.read(tamanho)
        if len(conteudo) != tamanho:
            resposta_erro(self, "O upload do backup foi interrompido.", HTTPStatus.BAD_REQUEST)
            return

        temporario = None
        origem = None
        destino = None
        try:
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(prefix="restauracao_", suffix=".db", dir=BACKUP_DIR, delete=False) as arquivo:
                temporario = Path(arquivo.name)
                arquivo.write(conteudo)

            origem = sqlite3.connect(temporario)
            integridade = origem.execute("PRAGMA integrity_check").fetchone()
            if not integridade or integridade[0] != "ok":
                raise ValueError("O arquivo selecionado esta corrompido ou nao e um banco SQLite valido.")
            tabelas = {linha[0] for linha in origem.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            obrigatorias = {"funcionarios", "auditoria", "armarios", "emprestimos", "emprestimo_participantes"}
            if not obrigatorias.issubset(tabelas):
                raise ValueError("O arquivo nao contem as tabelas necessarias do Sistema de Armarios.")

            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")
            backup_previo = criar_backup(BACKUP_DIR / f"armarios_antes_restauracao_{timestamp}.db")
            destino = sqlite3.connect(BASE_DIR / "armarios.db", timeout=30)
            origem.backup(destino)
            destino.close()
            destino = None
            registrar_auditoria("restaurou_backup", temporario.name, self._funcionario_logado(), f"backup_previo={backup_previo.name}")
            resposta_ok(self, {"mensagem": f"Backup restaurado. Uma copia do banco anterior foi salva em backups/{backup_previo.name}."})
        except ValueError as exc:
            resposta_erro(self, str(exc), HTTPStatus.BAD_REQUEST)
        except (sqlite3.Error, OSError) as exc:
            resposta_erro(self, f"Nao foi possivel restaurar o backup: {exc}", HTTPStatus.INTERNAL_SERVER_ERROR)
        finally:
            if origem is not None:
                origem.close()
            if destino is not None:
                destino.close()
            if temporario is not None:
                temporario.unlink(missing_ok=True)
    def _anonimizar_historico(self):
        dados = self._read_json()
        if dados is None:
            return
        try:
            data_limite = normalizar_data(dados.get("data_limite"))
            if not data_limite:
                raise ValueError("Informe a data limite para anonimizar o historico.")
            total = anonimizar_historico_ate(data_limite, self._funcionario_logado())
        except ValueError as exc:
            resposta_erro(self, str(exc))
            return
        resposta_ok(self, {"mensagem": f"{total} emprestimo(s) tiveram os dados pessoais anonimizados."})

    def _configuracoes(self):
        resposta_ok(
            self,
            {
                "configuracoes": carregar_configuracoes(),
                "smtp_configurado": smtp_configurado(),
            },
        )

    def _salvar_configuracoes(self):
        dados = self._read_json()
        if dados is None:
            return

        try:
            configuracoes = salvar_configuracoes(dados)
        except OSError:
            resposta_erro(self, "Nao foi possivel salvar as configuracoes.", HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        registrar_auditoria("alterou_configuracoes", "email_cobranca", self._funcionario_logado())

        resposta_ok(
            self,
            {
                "mensagem": "Configuracoes salvas com sucesso.",
                "configuracoes": configuracoes,
                "smtp_configurado": smtp_configurado(),
            },
        )

    def _emprestar(self):
        dados = self._read_json()
        if dados is None:
            return

        faltando = campos_faltando(dados, ["tipo_armario", "numero", "data_prevista"])
        if faltando:
            resposta_erro(self, f"Preencha os campos: {', '.join(faltando)}.")
            return

        participantes = extrair_participantes(dados)
        try:
            tipo_armario = parse_tipo_armario(dados["tipo_armario"])
            numero = validar_numero_por_tipo(tipo_armario, parse_numero(dados["numero"]))
            data_retirada = normalizar_data(dados.get("data_retirada") or datetime.now().strftime(DATE_FORMAT))
            data_prevista = normalizar_data(dados["data_prevista"])
            cadeado_proprio = parse_bool(dados.get("cadeado_proprio"))
            validar_data_prevista(data_prevista)
            validar_intervalo_datas(data_retirada, data_prevista)
        except ValueError as exc:
            resposta_erro(self, str(exc) or "Dados invalidos.")
            return

        ok, mensagem = emprestar_armario(
            tipo_armario,
            numero,
            participantes,
            data_retirada,
            data_prevista,
            cadeado_proprio,
            self._funcionario_logado(),
        )
        resposta = resposta_ok if ok else resposta_erro
        status = HTTPStatus.OK if ok else HTTPStatus.BAD_REQUEST
        resposta(self, {"mensagem": mensagem} if ok else mensagem, status)

    def _devolver(self):
        dados = self._read_json()
        if dados is None:
            return

        try:
            tipo_armario = parse_tipo_armario(dados.get("tipo_armario", ""))
            numero = validar_numero_por_tipo(tipo_armario, parse_numero(dados.get("numero", "")))
            data_devolucao = normalizar_data(dados.get("data") or datetime.now().strftime(DATE_FORMAT))
        except ValueError as exc:
            resposta_erro(self, str(exc) or "Dados invalidos.")
            return

        ok, mensagem = devolver_armario(tipo_armario, numero, data_devolucao, self._funcionario_logado())
        resposta = resposta_ok if ok else resposta_erro
        status = HTTPStatus.OK if ok else HTTPStatus.BAD_REQUEST
        resposta(self, {"mensagem": mensagem} if ok else mensagem, status)

    def _alterar_manutencao(self):
        dados = self._read_json()
        if dados is None:
            return

        try:
            tipo_armario = parse_tipo_armario(dados.get("tipo_armario", ""))
            numero = validar_numero_por_tipo(tipo_armario, parse_numero(dados.get("numero", "")))
            em_manutencao = dados.get("em_manutencao")
            if not isinstance(em_manutencao, bool):
                raise ValueError("Informe se o armario deve entrar ou sair da manutencao.")
        except ValueError as exc:
            resposta_erro(self, str(exc) or "Dados invalidos.")
            return

        ok, mensagem = definir_manutencao_armario(tipo_armario, numero, em_manutencao, self._funcionario_logado())
        resposta = resposta_ok if ok else resposta_erro
        status = HTTPStatus.OK if ok else HTTPStatus.BAD_REQUEST
        resposta(self, {"mensagem": mensagem} if ok else mensagem, status)

    def _atualizar_emprestimo(self):
        dados = self._read_json()
        if dados is None:
            return

        faltando = campos_faltando(dados, ["tipo_armario", "numero", "data_prevista"])
        if faltando:
            resposta_erro(self, f"Preencha os campos: {', '.join(faltando)}.")
            return

        participantes = extrair_participantes(dados)
        try:
            tipo_armario = parse_tipo_armario(dados["tipo_armario"])
            numero = validar_numero_por_tipo(tipo_armario, parse_numero(dados["numero"]))
            data_prevista = normalizar_data(dados["data_prevista"])
            cadeado_proprio = parse_bool(dados.get("cadeado_proprio"))
            validar_data_prevista(data_prevista)
        except ValueError as exc:
            resposta_erro(self, str(exc) or "Dados invalidos.")
            return

        ok, mensagem = atualizar_emprestimo_ativo(
            tipo_armario,
            numero,
            participantes,
            data_prevista,
            cadeado_proprio,
            self._funcionario_logado(),
        )
        resposta = resposta_ok if ok else resposta_erro
        status = HTTPStatus.OK if ok else HTTPStatus.BAD_REQUEST
        resposta(self, {"mensagem": mensagem} if ok else mensagem, status)

    def _cobrar_email(self):
        dados = self._read_json()
        if dados is None:
            return

        try:
            tipo_armario = parse_tipo_armario(dados.get("tipo_armario", ""))
            numero = validar_numero_por_tipo(tipo_armario, parse_numero(dados.get("numero", "")))
            armario = consultar_armario_flexivel(numero, por_prontuario=False, tipo_armario=tipo_armario)
            if not armario or armario.get("status") != "ocupado":
                resposta_erro(self, "Nao foi encontrado emprestimo ativo para este armario.")
                return
            if not esta_atrasado(armario.get("data_prevista")):
                resposta_erro(self, "O email de cobranca so pode ser enviado para armarios atrasados.")
                return

            enviados = enviar_cobranca_armario(
                armario,
                assunto_template=str(dados.get("assunto", "")).strip(),
                corpo_template=str(dados.get("mensagem", "")).strip(),
            )
        except ValueError as exc:
            resposta_erro(self, str(exc), HTTPStatus.BAD_REQUEST)
            return
        except OSError:
            resposta_erro(self, "Nao foi possivel salvar ou acessar as configuracoes.", HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        except (smtplib.SMTPException, ConnectionError):
            resposta_erro(self, "Nao foi possivel enviar o email agora.", HTTPStatus.BAD_GATEWAY)
            return

        registrar_auditoria("enviou_cobranca", f"{tipo_armario}:{numero}", self._funcionario_logado(), f"destinatarios={enviados}")
        resposta_ok(
            self,
            {"mensagem": f"Cobranca enviada automaticamente para {enviados} responsavel(is)."},
        )

    def _read_json(self):
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            resposta_erro(self, "Cabecalho Content-Length invalido.")
            return None

        if content_length < 0:
            resposta_erro(self, "Cabecalho Content-Length invalido.")
            return None
        if content_length > MAX_JSON_BYTES:
            resposta_erro(
                self,
                "A requisicao excede o tamanho maximo permitido.",
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
            return None

        try:
            raw_body = self.rfile.read(content_length).decode("utf-8") if content_length else "{}"
        except UnicodeDecodeError:
            resposta_erro(self, "O corpo da requisicao precisa estar em UTF-8.")
            return None

        try:
            dados = json.loads(raw_body)
        except json.JSONDecodeError:
            resposta_erro(self, "JSON invalido.")
            return None

        if not isinstance(dados, dict):
            resposta_erro(self, "O corpo da requisicao deve ser um objeto JSON.")
            return None

        return dados

    def log_message(self, format, *args):
        return


def obter_enderecos_rede():
    """Retorna os enderecos IPv4 locais que podem ser usados na rede."""
    enderecos = set()
    try:
        resultados = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
        enderecos.update(resultado[4][0] for resultado in resultados)
    except socket.gaierror:
        pass

    # Este connect apenas consulta a rota de rede do sistema; nenhum dado e enviado.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as conexao:
            conexao.connect(("8.8.8.8", 80))
            enderecos.add(conexao.getsockname()[0])
    except OSError:
        pass

    return sorted(
        endereco
        for endereco in enderecos
        if not endereco.startswith("127.") and endereco != "0.0.0.0"
    )


def main():
    adquirir_bloqueio_servidor()
    atexit.register(liberar_bloqueio_servidor)
    criar_banco()
    criar_armarios()
    server = ThreadingHTTPServer((HOST, PORT), ArmariosHandler)
    print(f"Servidor rodando (PID {os.getpid()}).")
    if HOST in {"0.0.0.0", "::"}:
        print(f"Nesta maquina: http://localhost:{PORT}")
        for endereco in obter_enderecos_rede():
            print(f"Na rede local: http://{endereco}:{PORT}")
    else:
        print(f"Endereco configurado: http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print(f"[ERRO] {exc}")
