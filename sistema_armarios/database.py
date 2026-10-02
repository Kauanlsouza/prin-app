import base64
import hashlib
import hmac
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DB_NAME = BASE_DIR / "armarios.db"
DATE_FORMAT = "%d/%m/%Y"
NUMERO_MAXIMO_CONVENCIONAL = 120
INICIO_FAIXA_BIBLIOTECA = 89
TIPOS_ARMARIO = {
    "convencional": {
        "rotulo": "Armario",
        "localizacao": "Andar de cima",
        "prefixo": "C",
        "numero_min": 1,
        "numero_max": NUMERO_MAXIMO_CONVENCIONAL,
    },
}


def conectar():
    # O servidor atende mais de uma maquina. Aguarda brevemente por uma
    # gravacao em andamento em vez de falhar de imediato com "database is locked".
    conn = sqlite3.connect(DB_NAME, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


def hoje():
    return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)


def parse_data(valor):
    return datetime.strptime(valor, DATE_FORMAT)


def normalizar_prontuario(valor):
    return str(valor or "").strip().upper()


def normalizar_email(valor):
    email = str(valor or "").strip().lower()
    if not email:
        raise ValueError("Informe o email do responsavel.")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError("Informe um email valido para o responsavel.")
    return email


def capacidade_armario(tipo, numero):
    tipo_normalizado = normalizar_tipo_armario(tipo)
    numero_int = validar_numero_armario(tipo_normalizado, numero)
    return 3 if obter_tamanho_armario(tipo_normalizado, numero_int) == "grande" else 2


def normalizar_tipo_armario(tipo):
    chave = str(tipo or "").strip().lower()
    if chave == "livro":
        return "convencional"
    if chave not in TIPOS_ARMARIO:
        raise ValueError("Tipo de armario invalido. Use convencional.")
    return chave


def rotulo_tipo_armario(tipo):
    return TIPOS_ARMARIO[normalizar_tipo_armario(tipo)]["rotulo"]


def validar_numero_armario(tipo, numero):
    tipo_normalizado = normalizar_tipo_armario(tipo)
    numero_int = int(numero)
    minimo = TIPOS_ARMARIO[tipo_normalizado]["numero_min"]
    maximo = TIPOS_ARMARIO[tipo_normalizado]["numero_max"]
    if numero_int < minimo or numero_int > maximo:
        raise ValueError(
            f"Numero invalido para {rotulo_tipo_armario(tipo_normalizado).lower()}. "
            f"Use de {minimo} a {maximo}."
        )
    return numero_int


def gerar_codigo_armario(tipo, numero):
    tipo_normalizado = normalizar_tipo_armario(tipo)
    prefixo = TIPOS_ARMARIO[tipo_normalizado]["prefixo"]
    return f"{prefixo}-{validar_numero_armario(tipo_normalizado, numero):03d}"


def obter_localizacao_armario(tipo, numero=None):
    tipo_normalizado = normalizar_tipo_armario(tipo)
    if tipo_normalizado != "convencional":
        return TIPOS_ARMARIO[tipo_normalizado]["localizacao"]

    if numero is not None and validar_numero_armario(tipo_normalizado, numero) >= INICIO_FAIXA_BIBLIOTECA:
        return "Andar de baixo, ao lado da biblioteca"
    return TIPOS_ARMARIO[tipo_normalizado]["localizacao"]


def obter_tamanho_armario(tipo, numero):
    tipo_normalizado = normalizar_tipo_armario(tipo)
    numero_int = validar_numero_armario(tipo_normalizado, numero)
    if tipo_normalizado == "convencional" and 81 <= numero_int <= 88:
        return "grande"
    return "padrao"


def identificar_armario(tipo, numero):
    return f"{rotulo_tipo_armario(tipo)} {validar_numero_armario(tipo, numero)}"


def _colunas_tabela(conn, tabela):
    return {linha["name"] for linha in conn.execute(f"PRAGMA table_info({tabela})").fetchall()}


def _tabela_existe(conn, tabela):
    resultado = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (tabela,),
    ).fetchone()
    return resultado is not None


def _criar_tabelas(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS funcionarios (
            id INTEGER PRIMARY KEY,
            nome TEXT NOT NULL,
            usuario TEXT NOT NULL UNIQUE,
            senha_hash TEXT NOT NULL,
            papel TEXT NOT NULL DEFAULT 'operador',
            ativo INTEGER NOT NULL DEFAULT 1,
            criado_em TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS auditoria (
            id INTEGER PRIMARY KEY,
            criado_em TEXT NOT NULL,
            funcionario_id INTEGER,
            funcionario_nome TEXT,
            acao TEXT NOT NULL,
            recurso TEXT NOT NULL,
            detalhes TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS armarios (
            id INTEGER PRIMARY KEY,
            codigo TEXT NOT NULL UNIQUE,
            tipo TEXT NOT NULL,
            numero INTEGER NOT NULL,
            localizacao TEXT NOT NULL,
            tamanho TEXT NOT NULL,
            status TEXT NOT NULL,
            UNIQUE(tipo, numero)
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS emprestimos (
            id INTEGER PRIMARY KEY,
            armario_codigo TEXT NOT NULL,
            tipo_armario TEXT NOT NULL,
            numero_armario INTEGER NOT NULL,
            nome TEXT NOT NULL,
            email TEXT NOT NULL,
            prontuario TEXT NOT NULL,
            curso TEXT NOT NULL,
            data_retirada TEXT NOT NULL,
            data_prevista TEXT NOT NULL,
            cadeado_proprio INTEGER NOT NULL DEFAULT 0,
            data_devolucao TEXT,
            funcionario_emprestimo_id INTEGER,
            funcionario_emprestimo_nome TEXT,
            funcionario_devolucao_id INTEGER,
            funcionario_devolucao_nome TEXT,
            FOREIGN KEY (armario_codigo) REFERENCES armarios(codigo)
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS emprestimo_participantes (
            id INTEGER PRIMARY KEY,
            emprestimo_id INTEGER NOT NULL,
            nome TEXT NOT NULL,
            email TEXT NOT NULL,
            prontuario TEXT NOT NULL,
            curso TEXT NOT NULL,
            FOREIGN KEY (emprestimo_id) REFERENCES emprestimos(id) ON DELETE CASCADE
        )
        """
    )


def _recriar_schema_completo(conn):
    conn.execute("DROP TABLE IF EXISTS emprestimo_participantes")
    conn.execute("DROP TABLE IF EXISTS emprestimos")
    conn.execute("DROP TABLE IF EXISTS armarios")
    _criar_tabelas(conn)


def _migrar_schema_legado(conn):
    conn.execute("ALTER TABLE armarios RENAME TO armarios_legado")
    if _tabela_existe(conn, "emprestimos"):
        conn.execute("ALTER TABLE emprestimos RENAME TO emprestimos_legado")

    _criar_tabelas(conn)

    legado_armarios = conn.execute(
        "SELECT numero, status FROM armarios_legado ORDER BY numero"
    ).fetchall()
    for item in legado_armarios:
        tipo = "convencional"
        numero = item["numero"]
        conn.execute(
            """
            INSERT INTO armarios (codigo, tipo, numero, localizacao, tamanho, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                gerar_codigo_armario(tipo, numero),
                tipo,
                numero,
                obter_localizacao_armario(tipo, numero),
                obter_tamanho_armario(tipo, numero),
                item["status"] or "livre",
            ),
        )

    if _tabela_existe(conn, "emprestimos_legado"):
        legado_emprestimos = conn.execute(
            """
            SELECT armario_id, nome, prontuario, curso, data_retirada, data_prevista, data_devolucao
            FROM emprestimos_legado
            ORDER BY id
            """
        ).fetchall()
        for item in legado_emprestimos:
            tipo = "convencional"
            numero = item["armario_id"]
            cursor = conn.execute(
                """
                INSERT INTO emprestimos (
                    armario_codigo,
                    tipo_armario,
                    numero_armario,
                    nome,
                    email,
                    prontuario,
                    curso,
                    data_retirada,
                    data_prevista,
                    data_devolucao
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    gerar_codigo_armario(tipo, numero),
                    tipo,
                    numero,
                    item["nome"],
                    "",
                    item["prontuario"],
                    item["curso"],
                    item["data_retirada"],
                    item["data_prevista"],
                    item["data_devolucao"],
                ),
            )
            conn.execute(
                """
                INSERT INTO emprestimo_participantes (emprestimo_id, nome, email, prontuario, curso)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    cursor.lastrowid,
                    item["nome"],
                    "",
                    normalizar_prontuario(item["prontuario"]),
                    item["curso"],
                ),
            )

    conn.execute("DROP TABLE armarios_legado")
    if _tabela_existe(conn, "emprestimos_legado"):
        conn.execute("DROP TABLE emprestimos_legado")


def _migrar_participantes_legado(conn):
    registros = conn.execute(
        """
        SELECT e.id, e.nome, e.prontuario, e.curso
        FROM emprestimos e
        LEFT JOIN emprestimo_participantes ep ON ep.emprestimo_id = e.id
        WHERE ep.id IS NULL
        ORDER BY e.id
        """
    ).fetchall()

    for item in registros:
        if not item["nome"] or not item["prontuario"] or not item["curso"]:
            continue
        conn.execute(
            """
            INSERT INTO emprestimo_participantes (emprestimo_id, nome, email, prontuario, curso)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                item["id"],
                item["nome"],
                "",
                normalizar_prontuario(item["prontuario"]),
                item["curso"],
            ),
        )


def _migrar_cadeado_proprio(conn):
    if _tabela_existe(conn, "emprestimos") and "cadeado_proprio" not in _colunas_tabela(conn, "emprestimos"):
        conn.execute(
            "ALTER TABLE emprestimos ADD COLUMN cadeado_proprio INTEGER NOT NULL DEFAULT 0"
        )


def _migrar_responsaveis_emprestimo(conn):
    if not _tabela_existe(conn, "emprestimos"):
        return
    colunas = _colunas_tabela(conn, "emprestimos")
    novas_colunas = {
        "funcionario_emprestimo_id": "INTEGER",
        "funcionario_emprestimo_nome": "TEXT",
        "funcionario_devolucao_id": "INTEGER",
        "funcionario_devolucao_nome": "TEXT",
    }
    for coluna, tipo in novas_colunas.items():
        if coluna not in colunas:
            conn.execute(f"ALTER TABLE emprestimos ADD COLUMN {coluna} {tipo}")


def _migrar_papeis_funcionarios(conn):
    if "papel" not in _colunas_tabela(conn, "funcionarios"):
        conn.execute("ALTER TABLE funcionarios ADD COLUMN papel TEXT NOT NULL DEFAULT 'operador'")
    if not conn.execute("SELECT 1 FROM funcionarios WHERE papel = 'administrador' LIMIT 1").fetchone():
        conn.execute("UPDATE funcionarios SET papel = 'administrador' WHERE id = (SELECT MIN(id) FROM funcionarios)")


def _criar_indices(conn):
    conn.execute("CREATE INDEX IF NOT EXISTS idx_emprestimos_ativos ON emprestimos(armario_codigo) WHERE data_devolucao IS NULL")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_participantes_prontuario ON emprestimo_participantes(prontuario)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_participantes_emprestimo ON emprestimo_participantes(emprestimo_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_auditoria_criado_em ON auditoria(criado_em DESC)")


def _registrar_auditoria(conn, acao, recurso, funcionario=None, detalhes=""):
    conn.execute(
        """INSERT INTO auditoria (criado_em, funcionario_id, funcionario_nome, acao, recurso, detalhes)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (datetime.now().strftime("%d/%m/%Y %H:%M"), (funcionario or {}).get("id"), (funcionario or {}).get("nome"), acao, recurso, str(detalhes or "")[:500]),
    )


def _hash_senha(senha, salt=None):
    salt_bytes = os.urandom(16) if salt is None else salt
    digest = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), salt_bytes, 210_000)
    return "pbkdf2_sha256$210000$%s$%s" % (
        base64.b64encode(salt_bytes).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def _senha_confere(senha, senha_hash):
    try:
        algoritmo, iteracoes, salt, digest = senha_hash.split("$", 3)
        if algoritmo != "pbkdf2_sha256":
            return False
        calculado = hashlib.pbkdf2_hmac(
            "sha256", senha.encode("utf-8"), base64.b64decode(salt), int(iteracoes)
        )
        return hmac.compare_digest(calculado, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


def _normalizar_dados_funcionario(nome, usuario, senha):
    nome = str(nome or "").strip()
    usuario = str(usuario or "").strip().lower()
    senha = str(senha or "")
    if len(nome) < 2 or len(usuario) < 3 or len(senha) < 6:
        raise ValueError("Informe nome, usuario (minimo 3 caracteres) e senha (minimo 6 caracteres).")
    return nome, usuario, senha


def _inserir_funcionario(conn, nome, usuario, senha, papel="operador"):
    if papel not in {"administrador", "operador"}:
        raise ValueError("Papel de funcionario invalido.")
    conn.execute(
        "INSERT INTO funcionarios (nome, usuario, senha_hash, papel, criado_em) VALUES (?, ?, ?, ?, ?)",
        (nome, usuario, _hash_senha(senha), papel, datetime.now().strftime("%d/%m/%Y %H:%M")),
    )


def criar_funcionario(nome, usuario, senha, papel="operador", funcionario=None):
    nome, usuario, senha = _normalizar_dados_funcionario(nome, usuario, senha)
    conn = conectar()
    try:
        _inserir_funcionario(conn, nome, usuario, senha, papel)
        _registrar_auditoria(conn, "criou_funcionario", f"usuario:{usuario}", funcionario, f"papel={papel}")
        conn.commit()
    except sqlite3.IntegrityError as exc:
        raise ValueError("Este usuario ja esta cadastrado.") from exc
    finally:
        conn.close()


def tem_funcionarios():
    conn = conectar()
    try:
        return conn.execute("SELECT 1 FROM funcionarios LIMIT 1").fetchone() is not None
    finally:
        conn.close()


def criar_primeiro_funcionario(nome, usuario, senha):
    nome, usuario, senha = _normalizar_dados_funcionario(nome, usuario, senha)
    conn = conectar()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM funcionarios LIMIT 1").fetchone():
            conn.rollback()
            raise ValueError("O primeiro acesso ja foi configurado.")
        _inserir_funcionario(conn, nome, usuario, senha, "administrador")
        conn.commit()
    finally:
        conn.close()


def autenticar_funcionario(usuario, senha):
    conn = conectar()
    try:
        funcionario = conn.execute(
            "SELECT id, nome, usuario, papel, senha_hash FROM funcionarios WHERE usuario = ? AND ativo = 1",
            (str(usuario or "").strip().lower(),),
        ).fetchone()
    finally:
        conn.close()
    if not funcionario or not _senha_confere(str(senha or ""), funcionario["senha_hash"]):
        return None
    return {"id": funcionario["id"], "nome": funcionario["nome"], "usuario": funcionario["usuario"], "papel": funcionario["papel"]}


def listar_funcionarios():
    conn = conectar()
    try:
        return [dict(item) for item in conn.execute(
            "SELECT id, nome, usuario, papel, ativo, criado_em FROM funcionarios ORDER BY nome COLLATE NOCASE"
        ).fetchall()]
    finally:
        conn.close()


def _criar_funcionario_inicial(conn):
    existe = conn.execute("SELECT 1 FROM funcionarios LIMIT 1").fetchone()
    if existe:
        return
    nome = os.getenv("ADMIN_NOME", "").strip()
    usuario = os.getenv("ADMIN_USUARIO", "").strip().lower()
    senha = os.getenv("ADMIN_SENHA", "")
    # Sem estas variaveis, o primeiro acesso sera configurado na tela de login.
    if not nome and not usuario and not senha:
        return
    if len(nome) < 2 or len(usuario) < 3 or len(senha) < 6:
        raise RuntimeError("ADMIN_NOME, ADMIN_USUARIO e ADMIN_SENHA devem ser preenchidos juntos no arquivo .env.")
    conn.execute(
        "INSERT INTO funcionarios (nome, usuario, senha_hash, papel, criado_em) VALUES (?, ?, ?, ?, ?)",
        (nome, usuario, _hash_senha(senha), "administrador", datetime.now().strftime("%d/%m/%Y %H:%M")),
    )


def _converter_numero_livro_para_convencional(numero):
    return 88 + int(numero)


def _migrar_armarios_livro_para_convencionais(conn):
    if not _tabela_existe(conn, "armarios"):
        return

    antigos_livro = conn.execute(
        """
        SELECT id, numero
        FROM armarios
        WHERE tipo = 'livro'
        ORDER BY numero
        """
    ).fetchall()

    for item in antigos_livro:
        novo_numero = _converter_numero_livro_para_convencional(item["numero"])
        conn.execute(
            """
            INSERT OR IGNORE INTO armarios (codigo, tipo, numero, localizacao, tamanho, status)
            SELECT ?, 'convencional', ?, ?, ?, status
            FROM armarios
            WHERE id = ?
            """,
            (
                gerar_codigo_armario("convencional", novo_numero),
                novo_numero,
                obter_localizacao_armario("convencional", novo_numero),
                obter_tamanho_armario("convencional", novo_numero),
                item["id"],
            ),
        )

    if not _tabela_existe(conn, "emprestimos"):
        return

    emprestimos_livro = conn.execute(
        """
        SELECT id, numero_armario
        FROM emprestimos
        WHERE tipo_armario = 'livro'
        ORDER BY id
        """
    ).fetchall()

    for item in emprestimos_livro:
        novo_numero = _converter_numero_livro_para_convencional(item["numero_armario"])
        conn.execute(
            """
            UPDATE emprestimos
            SET armario_codigo = ?,
                tipo_armario = 'convencional',
                numero_armario = ?
            WHERE id = ?
            """,
            (
                gerar_codigo_armario("convencional", novo_numero),
                novo_numero,
                item["id"],
            ),
        )

    if antigos_livro:
        conn.execute("DELETE FROM armarios WHERE tipo = 'livro'")


def criar_banco():
    conn = conectar()
    try:
        if _tabela_existe(conn, "armarios") and "tipo" not in _colunas_tabela(conn, "armarios"):
            _migrar_schema_legado(conn)
        else:
            precisa_resetar = False
            if _tabela_existe(conn, "emprestimos") and "email" not in _colunas_tabela(conn, "emprestimos"):
                precisa_resetar = True
            if _tabela_existe(conn, "emprestimo_participantes") and "email" not in _colunas_tabela(conn, "emprestimo_participantes"):
                precisa_resetar = True

            if precisa_resetar:
                _recriar_schema_completo(conn)
            else:
                _criar_tabelas(conn)

        if _tabela_existe(conn, "emprestimos") and _tabela_existe(conn, "emprestimo_participantes"):
            _migrar_participantes_legado(conn)
        _migrar_cadeado_proprio(conn)
        _migrar_responsaveis_emprestimo(conn)
        _migrar_papeis_funcionarios(conn)
        _criar_indices(conn)
        _migrar_armarios_livro_para_convencionais(conn)
        _criar_funcionario_inicial(conn)
        conn.commit()
    finally:
        conn.close()


def criar_armarios(_qtd=None):
    conn = conectar()
    inseridos = 0
    try:
        for tipo, numero in _iterar_armarios_reais():
            cursor = conn.execute(
                """
                INSERT INTO armarios (codigo, tipo, numero, localizacao, tamanho, status)
                VALUES (?, ?, ?, ?, ?, 'livre')
                ON CONFLICT(codigo) DO UPDATE SET
                    tipo = excluded.tipo,
                    numero = excluded.numero,
                    localizacao = excluded.localizacao,
                    tamanho = excluded.tamanho
                """,
                (
                    gerar_codigo_armario(tipo, numero),
                    tipo,
                    numero,
                    obter_localizacao_armario(tipo, numero),
                    obter_tamanho_armario(tipo, numero),
                ),
            )
            if cursor.rowcount > 0:
                inseridos += 1
        conn.commit()
        return inseridos
    finally:
        conn.close()


def registrar_auditoria(acao, recurso, funcionario=None, detalhes=""):
    conn = conectar()
    try:
        _registrar_auditoria(conn, acao, recurso, funcionario, detalhes)
        conn.commit()
    finally:
        conn.close()


def listar_auditoria(limite=50):
    conn = conectar()
    try:
        return [dict(item) for item in conn.execute(
            """SELECT criado_em, funcionario_nome, acao, recurso, detalhes
               FROM auditoria ORDER BY id DESC LIMIT ?""",
            (max(1, min(int(limite), 200)),),
        ).fetchall()]
    finally:
        conn.close()


def criar_backup(destino):
    """Cria uma copia consistente mesmo com o sistema em funcionamento."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    origem = conectar()
    copia = sqlite3.connect(destino)
    try:
        origem.backup(copia)
    finally:
        copia.close()
        origem.close()
    return destino


def anonimizar_historico_ate(data_limite, funcionario=None):
    """Remove dados pessoais de emprestimos ja devolvidos ate a data informada."""
    limite = parse_data(data_limite)
    conn = conectar()
    try:
        conn.execute("BEGIN IMMEDIATE")
        registros = conn.execute(
            "SELECT id, data_devolucao FROM emprestimos WHERE data_devolucao IS NOT NULL"
        ).fetchall()
        ids = [item["id"] for item in registros if parse_data(item["data_devolucao"]) <= limite]
        for emprestimo_id in ids:
            conn.execute(
                """UPDATE emprestimos SET nome = 'Dados anonimizados', email = '', prontuario = '', curso = ''
                   WHERE id = ?""",
                (emprestimo_id,),
            )
            conn.execute(
                """UPDATE emprestimo_participantes SET nome = 'Dados anonimizados', email = '', prontuario = '', curso = ''
                   WHERE emprestimo_id = ?""",
                (emprestimo_id,),
            )
        _registrar_auditoria(conn, "anonimizou_historico", "dados_pessoais", funcionario, f"registros={len(ids)}; ate={data_limite}")
        conn.commit()
        return len(ids)
    except sqlite3.Error:
        conn.rollback()
        raise
    finally:
        conn.close()


def _iterar_armarios_reais():
    for numero in range(1, NUMERO_MAXIMO_CONVENCIONAL + 1):
        yield "convencional", numero


def _ordenacao_tipo_sql(alias="a"):
    return f"{alias}.numero"


def _resumir_valores(valores, unicos=False):
    itens = [str(valor).strip() for valor in valores if str(valor or "").strip()]
    if unicos:
        itens = list(dict.fromkeys(itens))
    return " | ".join(itens)


def _resumir_participantes(participantes, fallback=None):
    fallback = fallback or {}
    return {
        "nome": _resumir_valores([item["nome"] for item in participantes]) or fallback.get("nome", ""),
        "email": _resumir_valores([item["email"] for item in participantes], unicos=True) or fallback.get("email", ""),
        "prontuario": _resumir_valores([item["prontuario"] for item in participantes]) or fallback.get("prontuario", ""),
        "curso": _resumir_valores([item["curso"] for item in participantes], unicos=True) or fallback.get("curso", ""),
    }


def _buscar_participantes_por_emprestimo(conn, emprestimo_ids):
    ids = [emprestimo_id for emprestimo_id in emprestimo_ids if emprestimo_id]
    if not ids:
        return {}

    placeholders = ", ".join("?" for _ in ids)
    rows = conn.execute(
        f"""
        SELECT emprestimo_id, nome, email, prontuario, curso
        FROM emprestimo_participantes
        WHERE emprestimo_id IN ({placeholders})
        ORDER BY emprestimo_id, id
        """,
        ids,
    ).fetchall()

    participantes = {}
    for row in rows:
        participantes.setdefault(row["emprestimo_id"], []).append(
            {
                "nome": row["nome"],
                "email": row["email"],
                "prontuario": row["prontuario"],
                "curso": row["curso"],
            }
        )
    return participantes


def _validar_participantes(participantes, tipo, numero):
    participantes_validos = []
    for indice, participante in enumerate(participantes or [], start=1):
        if not isinstance(participante, dict):
            raise ValueError("Cada participante precisa ter nome, email, prontuario e curso.")

        nome = str(participante.get("nome", "")).strip()
        email = normalizar_email(participante.get("email", ""))
        prontuario = normalizar_prontuario(participante.get("prontuario", ""))
        curso = str(participante.get("curso", "")).strip()
        if not nome or not email or not prontuario or not curso:
            raise ValueError(f"Preencha nome, email, prontuario e curso do participante {indice}.")

        participantes_validos.append(
            {
                "nome": nome,
                "email": email,
                "prontuario": prontuario,
                "curso": curso,
            }
        )

    quantidade_esperada = capacidade_armario(tipo, numero)
    if len(participantes_validos) != quantidade_esperada:
        raise ValueError(
            f"Este armario exige {quantidade_esperada} participante(s) cadastrados."
        )

    prontuarios = [item["prontuario"] for item in participantes_validos]
    if len(prontuarios) != len(set(prontuarios)):
        raise ValueError("Nao repita o mesmo prontuario no mesmo armario.")

    return participantes_validos


def _armario_para_dict(linha, participantes=None):
    participantes = participantes or []
    resumo = _resumir_participantes(
        participantes,
        {
            "nome": linha["nome"],
            "email": linha["email"],
            "prontuario": linha["prontuario"],
            "curso": linha["curso"],
        },
    )
    return {
        "codigo": linha["codigo"],
        "tipo": linha["tipo"],
        "tipo_rotulo": rotulo_tipo_armario(linha["tipo"]),
        "numero": linha["numero"],
        "identificacao": identificar_armario(linha["tipo"], linha["numero"]),
        "localizacao": linha["localizacao"],
        "tamanho": linha["tamanho"],
        "status": linha["status"],
        "nome": resumo["nome"],
        "email": resumo["email"],
        "prontuario": resumo["prontuario"],
        "curso": resumo["curso"],
        "data_retirada": linha["data_retirada"],
        "data_prevista": linha["data_prevista"],
        "cadeado_proprio": bool(linha["cadeado_proprio"]) if "cadeado_proprio" in linha.keys() else False,
        "participantes": participantes,
        "capacidade": capacidade_armario(linha["tipo"], linha["numero"]),
    }


def _consulta_detalhada_armarios(conn, where="", params=()):
    query = f"""
        SELECT
            a.codigo,
            a.tipo,
            a.numero,
            a.localizacao,
            a.tamanho,
            a.status,
            e.id AS emprestimo_id,
            e.nome,
            e.email,
            e.prontuario,
            e.curso,
            e.data_retirada,
            e.data_prevista,
            e.cadeado_proprio
        FROM armarios a
        LEFT JOIN emprestimos e
            ON a.codigo = e.armario_codigo
            AND e.data_devolucao IS NULL
        {where}
        ORDER BY {_ordenacao_tipo_sql("a")}
    """
    linhas = conn.execute(query, params).fetchall()
    participantes = _buscar_participantes_por_emprestimo(
        conn,
        [linha["emprestimo_id"] for linha in linhas if linha["emprestimo_id"]],
    )
    return [
        _armario_para_dict(linha, participantes.get(linha["emprestimo_id"], []))
        for linha in linhas
    ]


def listar_armarios():
    conn = conectar()
    try:
        return _consulta_detalhada_armarios(conn)
    finally:
        conn.close()


def listar_armarios_detalhados():
    return listar_armarios()


def contar_armarios_por_status():
    conn = conectar()
    try:
        resultados = dict(
            conn.execute("SELECT status, COUNT(*) AS total FROM armarios GROUP BY status").fetchall()
        )
        convencional_total = conn.execute(
            "SELECT COUNT(*) AS total FROM armarios WHERE tipo = 'convencional'"
        ).fetchone()["total"]
        grandes_total = conn.execute(
            "SELECT COUNT(*) AS total FROM armarios WHERE tamanho = 'grande'"
        ).fetchone()["total"]
        return {
            "livre": resultados.get("livre", 0),
            "ocupado": resultados.get("ocupado", 0),
            "manutencao": resultados.get("manutencao", 0),
            "convencional_total": convencional_total,
            "grandes_total": grandes_total,
        }
    finally:
        conn.close()


def _buscar_armario_por_tipo_numero(conn, tipo, numero):
    return conn.execute(
        """
        SELECT codigo, status
        FROM armarios
        WHERE tipo = ? AND numero = ?
        """,
        (tipo, numero),
    ).fetchone()


def _buscar_emprestimo_ativo_por_codigo(conn, armario_codigo):
    return conn.execute(
        """
        SELECT id, armario_codigo, tipo_armario, numero_armario, data_retirada, data_prevista, cadeado_proprio
        FROM emprestimos
        WHERE armario_codigo = ? AND data_devolucao IS NULL
        ORDER BY id DESC
        LIMIT 1
        """,
        (armario_codigo,),
    ).fetchone()


def emprestar_armario(tipo_armario, numero_armario, participantes, data_retirada, data_prevista, cadeado_proprio=False, funcionario=None):
    tipo = normalizar_tipo_armario(tipo_armario)
    numero = validar_numero_armario(tipo, numero_armario)
    participantes_validos = _validar_participantes(participantes, tipo, numero)
    conn = conectar()
    try:
        conn.execute("BEGIN IMMEDIATE")

        placeholders = ", ".join("?" for _ in participantes_validos)
        conflitos = conn.execute(
            """
            SELECT ep.prontuario
            FROM emprestimo_participantes ep
            JOIN emprestimos e ON e.id = ep.emprestimo_id
            WHERE ep.prontuario IN ("""
            + placeholders
            + """)
              AND e.data_devolucao IS NULL
            ORDER BY ep.prontuario
            """,
            [item["prontuario"] for item in participantes_validos],
        ).fetchall()

        if conflitos:
            prontuarios = ", ".join(dict.fromkeys(item["prontuario"] for item in conflitos))
            mensagem = f"[ERRO] Os prontuarios {prontuarios} ja possuem um armario emprestado."
            conn.rollback()
            return False, mensagem

        armario = _buscar_armario_por_tipo_numero(conn, tipo, numero)

        if not armario:
            mensagem = "[ERRO] Armario nao encontrado."
            conn.rollback()
            return False, mensagem

        if armario["status"] != "livre":
            mensagem = (
                "[ERRO] Este armario esta em manutencao e nao pode ser reservado."
                if armario["status"] == "manutencao"
                else "[ERRO] Este armario ja esta ocupado."
            )
            conn.rollback()
            return False, mensagem

        conn.execute(
            "UPDATE armarios SET status = 'ocupado' WHERE codigo = ?",
            (armario["codigo"],),
        )
        resumo = _resumir_participantes(participantes_validos)
        cursor = conn.execute(
            """
            INSERT INTO emprestimos (
                armario_codigo,
                tipo_armario,
                numero_armario,
                nome,
                email,
                prontuario,
                curso,
                data_retirada,
                data_prevista,
                cadeado_proprio,
                funcionario_emprestimo_id,
                funcionario_emprestimo_nome
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                armario["codigo"],
                tipo,
                numero,
                resumo["nome"],
                resumo["email"],
                resumo["prontuario"],
                resumo["curso"],
                data_retirada,
                data_prevista,
                1 if cadeado_proprio else 0,
                (funcionario or {}).get("id"),
                (funcionario or {}).get("nome"),
            ),
        )
        for participante in participantes_validos:
            conn.execute(
                """
                INSERT INTO emprestimo_participantes (emprestimo_id, nome, email, prontuario, curso)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    cursor.lastrowid,
                    participante["nome"],
                    participante["email"],
                    participante["prontuario"],
                    participante["curso"],
                ),
            )
        _registrar_auditoria(conn, "criou_emprestimo", armario["codigo"], funcionario, f"participantes={len(participantes_validos)}; prazo={data_prevista}")
        conn.commit()
        mensagem = (
            f"[SUCESSO] {identificar_armario(tipo, numero)} emprestado para {resumo['nome']}."
        )
        return True, mensagem
    except sqlite3.Error:
        conn.rollback()
        raise
    finally:
        conn.close()


def atualizar_emprestimo_ativo(tipo_armario, numero_armario, participantes, data_prevista, cadeado_proprio=False, funcionario=None):
    tipo = normalizar_tipo_armario(tipo_armario)
    numero = validar_numero_armario(tipo, numero_armario)
    participantes_validos = _validar_participantes(participantes, tipo, numero)
    conn = conectar()
    try:
        conn.execute("BEGIN IMMEDIATE")

        armario = _buscar_armario_por_tipo_numero(conn, tipo, numero)
        if not armario:
            conn.rollback()
            return False, "[ERRO] Armario nao encontrado."

        if armario["status"] != "ocupado":
            conn.rollback()
            return False, "[ERRO] Nao existe emprestimo ativo para este armario."

        emprestimo = _buscar_emprestimo_ativo_por_codigo(conn, armario["codigo"])
        if not emprestimo:
            conn.rollback()
            return False, "[ERRO] Nao foi possivel localizar o emprestimo ativo."

        if parse_data(data_prevista) < parse_data(emprestimo["data_retirada"]):
            conn.rollback()
            return False, "[ERRO] A data prevista nao pode ser anterior a retirada."

        placeholders = ", ".join("?" for _ in participantes_validos)
        conflitos = conn.execute(
            """
            SELECT ep.prontuario
            FROM emprestimo_participantes ep
            JOIN emprestimos e ON e.id = ep.emprestimo_id
            WHERE ep.prontuario IN ("""
            + placeholders
            + """)
              AND e.data_devolucao IS NULL
              AND e.id <> ?
            ORDER BY ep.prontuario
            """,
            [item["prontuario"] for item in participantes_validos] + [emprestimo["id"]],
        ).fetchall()

        if conflitos:
            prontuarios = ", ".join(dict.fromkeys(item["prontuario"] for item in conflitos))
            conn.rollback()
            return False, f"[ERRO] Os prontuarios {prontuarios} ja possuem outro armario emprestado."

        resumo = _resumir_participantes(participantes_validos)
        conn.execute(
            """
            UPDATE emprestimos
            SET nome = ?, email = ?, prontuario = ?, curso = ?, data_prevista = ?, cadeado_proprio = ?
            WHERE id = ?
            """,
            (
                resumo["nome"],
                resumo["email"],
                resumo["prontuario"],
                resumo["curso"],
                data_prevista,
                1 if cadeado_proprio else 0,
                emprestimo["id"],
            ),
        )
        conn.execute(
            "DELETE FROM emprestimo_participantes WHERE emprestimo_id = ?",
            (emprestimo["id"],),
        )
        for participante in participantes_validos:
            conn.execute(
                """
                INSERT INTO emprestimo_participantes (emprestimo_id, nome, email, prontuario, curso)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    emprestimo["id"],
                    participante["nome"],
                    participante["email"],
                    participante["prontuario"],
                    participante["curso"],
                ),
            )
        _registrar_auditoria(conn, "atualizou_emprestimo", armario["codigo"], funcionario, f"participantes={len(participantes_validos)}; prazo={data_prevista}")
        conn.commit()
        return True, f"[SUCESSO] {identificar_armario(tipo, numero)} atualizado com sucesso."
    except sqlite3.Error:
        conn.rollback()
        raise
    finally:
        conn.close()


def devolver_armario(tipo_armario, numero_armario, data_devolucao, funcionario=None):
    tipo = normalizar_tipo_armario(tipo_armario)
    numero = validar_numero_armario(tipo, numero_armario)
    conn = conectar()
    try:
        conn.execute("BEGIN IMMEDIATE")

        armario = _buscar_armario_por_tipo_numero(conn, tipo, numero)

        if not armario:
            conn.rollback()
            return False, "[ERRO] Armario nao encontrado."

        if armario["status"] != "ocupado":
            conn.rollback()
            if armario["status"] == "manutencao":
                return False, "[ERRO] Este armario esta em manutencao e nao possui emprestimo para devolucao."
            return False, "[ERRO] Este armario ja esta livre."

        emprestimo = _buscar_emprestimo_ativo_por_codigo(conn, armario["codigo"])
        if not emprestimo:
            conn.rollback()
            return False, "[ERRO] Nao foi possivel localizar o emprestimo ativo."
        if parse_data(data_devolucao) < parse_data(emprestimo["data_retirada"]):
            conn.rollback()
            return False, "[ERRO] A data de devolucao nao pode ser anterior a retirada."

        cursor = conn.execute(
            """
            UPDATE emprestimos
            SET data_devolucao = ?,
                funcionario_devolucao_id = ?,
                funcionario_devolucao_nome = ?
            WHERE armario_codigo = ? AND data_devolucao IS NULL
            """,
            (data_devolucao, (funcionario or {}).get("id"), (funcionario or {}).get("nome"), armario["codigo"]),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            return False, "[ERRO] Nao foi possivel localizar o emprestimo ativo."

        conn.execute("UPDATE armarios SET status = 'livre' WHERE codigo = ?", (armario["codigo"],))
        _registrar_auditoria(conn, "devolveu_emprestimo", armario["codigo"], funcionario, f"devolucao={data_devolucao}")
        conn.commit()
        return True, f"[SUCESSO] {identificar_armario(tipo, numero)} liberado com sucesso."
    except sqlite3.Error:
        conn.rollback()
        raise
    finally:
        conn.close()


def definir_manutencao_armario(tipo_armario, numero_armario, em_manutencao, funcionario=None):
    """Coloca um armario livre em manutencao ou o devolve a disponibilidade."""
    tipo = normalizar_tipo_armario(tipo_armario)
    numero = validar_numero_armario(tipo, numero_armario)
    novo_status = "manutencao" if em_manutencao else "livre"
    status_esperado = "livre" if em_manutencao else "manutencao"
    conn = conectar()
    try:
        conn.execute("BEGIN IMMEDIATE")
        armario = _buscar_armario_por_tipo_numero(conn, tipo, numero)
        if not armario:
            conn.rollback()
            return False, "[ERRO] Armario nao encontrado."
        if armario["status"] != status_esperado:
            conn.rollback()
            if em_manutencao:
                return False, "[ERRO] Apenas armarios livres podem entrar em manutencao."
            return False, "[ERRO] Este armario nao esta em manutencao."

        conn.execute(
            "UPDATE armarios SET status = ? WHERE codigo = ?",
            (novo_status, armario["codigo"]),
        )
        _registrar_auditoria(conn, "alterou_manutencao", armario["codigo"], funcionario, f"status={novo_status}")
        conn.commit()
        acao = "colocado em manutencao" if em_manutencao else "liberado da manutencao"
        return True, f"[SUCESSO] {identificar_armario(tipo, numero)} {acao}."
    except sqlite3.Error:
        conn.rollback()
        raise
    finally:
        conn.close()


def consultar_armario_flexivel(valor, por_prontuario=False, tipo_armario=None):
    conn = conectar()
    try:
        if por_prontuario:
            query = f"""
                SELECT
                    a.codigo,
                    a.tipo,
                    a.numero,
                    a.localizacao,
                    a.tamanho,
                    a.status,
                    e.id AS emprestimo_id,
                    e.nome,
                    e.email,
                    e.prontuario,
                    e.curso,
                    e.data_retirada,
                    e.data_prevista,
                    e.cadeado_proprio
                FROM emprestimos e
                JOIN emprestimo_participantes ep ON ep.emprestimo_id = e.id
                JOIN armarios a ON a.codigo = e.armario_codigo
                WHERE ep.prontuario = ? AND e.data_devolucao IS NULL
                ORDER BY e.id DESC
                LIMIT 1
            """
            params = (normalizar_prontuario(valor),)
        else:
            tipo = normalizar_tipo_armario(tipo_armario)
            numero = validar_numero_armario(tipo, valor)
            query = f"""
                SELECT
                    a.codigo,
                    a.tipo,
                    a.numero,
                    a.localizacao,
                    a.tamanho,
                    a.status,
                    e.id AS emprestimo_id,
                    e.nome,
                    e.email,
                    e.prontuario,
                    e.curso,
                    e.data_retirada,
                    e.data_prevista,
                    e.cadeado_proprio
                FROM armarios a
                LEFT JOIN emprestimos e
                    ON a.codigo = e.armario_codigo
                    AND e.data_devolucao IS NULL
                WHERE a.tipo = ? AND a.numero = ?
                ORDER BY {_ordenacao_tipo_sql("a")}
                LIMIT 1
            """
            params = (tipo, numero)

        resultado = conn.execute(query, params).fetchone()
        if not resultado:
            return None
        participantes = _buscar_participantes_por_emprestimo(conn, [resultado["emprestimo_id"]])
        return _armario_para_dict(resultado, participantes.get(resultado["emprestimo_id"], []))
    finally:
        conn.close()


def listar_armarios_livres(tipo_armario=""):
    conn = conectar()
    try:
        where = "WHERE a.status = 'livre'"
        params = []
        if tipo_armario:
            where += " AND a.tipo = ?"
            params.append(normalizar_tipo_armario(tipo_armario))
        return _consulta_detalhada_armarios(conn, where, tuple(params))
    finally:
        conn.close()


def listar_atrasados():
    conn = conectar()
    try:
        ativos = conn.execute(
            f"""
            SELECT
                a.codigo,
                a.tipo,
                a.numero,
                a.localizacao,
                a.tamanho,
                a.status,
                e.id AS emprestimo_id,
                e.nome,
                e.email,
                e.prontuario,
                e.curso,
                e.data_retirada,
                e.data_prevista,
                e.cadeado_proprio
            FROM emprestimos e
            JOIN armarios a ON a.codigo = e.armario_codigo
            WHERE e.data_devolucao IS NULL
            ORDER BY {_ordenacao_tipo_sql("a")}
            """
        ).fetchall()
        participantes = _buscar_participantes_por_emprestimo(
            conn,
            [item["emprestimo_id"] for item in ativos if item["emprestimo_id"]],
        )
    finally:
        conn.close()

    atrasados = []
    for item in ativos:
        try:
            if parse_data(item["data_prevista"]) < hoje():
                atrasados.append(_armario_para_dict(item, participantes.get(item["emprestimo_id"], [])))
        except ValueError:
            continue
    return atrasados


def listar_historico_emprestimos(
    nome="",
    prontuario="",
    status="",
    data_inicio="",
    data_fim="",
    tipo_armario="",
):
    conn = conectar()
    try:
        query = """
            SELECT
                id AS emprestimo_id,
                armario_codigo,
                tipo_armario,
                numero_armario,
                nome,
                email,
                prontuario,
                curso,
                data_retirada,
                data_prevista,
                cadeado_proprio,
                data_devolucao,
                funcionario_emprestimo_nome,
                funcionario_devolucao_nome
            FROM emprestimos
            WHERE 1 = 1
        """
        params = []

        if nome:
            query += """
                AND EXISTS (
                    SELECT 1
                    FROM emprestimo_participantes ep
                    WHERE ep.emprestimo_id = emprestimos.id
                      AND ep.nome LIKE ?
                )
            """
            params.append(f"%{nome}%")

        if prontuario:
            query += """
                AND EXISTS (
                    SELECT 1
                    FROM emprestimo_participantes ep
                    WHERE ep.emprestimo_id = emprestimos.id
                      AND ep.prontuario LIKE ?
                )
            """
            params.append(f"%{normalizar_prontuario(prontuario)}%")

        if tipo_armario:
            query += " AND tipo_armario = ?"
            params.append(normalizar_tipo_armario(tipo_armario))

        if status == "ativos":
            query += " AND data_devolucao IS NULL"
        elif status == "devolvidos":
            query += " AND data_devolucao IS NOT NULL"

        query += " ORDER BY id DESC"
        resultados = conn.execute(query, params).fetchall()
        participantes = _buscar_participantes_por_emprestimo(
            conn,
            [item["emprestimo_id"] for item in resultados if item["emprestimo_id"]],
        )
    finally:
        conn.close()

    historico = []
    data_inicio_dt = parse_data(data_inicio) if data_inicio else None
    data_fim_dt = parse_data(data_fim) if data_fim else None

    for item in resultados:
        try:
            retirada_dt = parse_data(item["data_retirada"])
        except ValueError:
            continue

        if data_inicio_dt and retirada_dt < data_inicio_dt:
            continue
        if data_fim_dt and retirada_dt > data_fim_dt:
            continue

        historico.append(
            {
                **_resumir_participantes(
                    participantes.get(item["emprestimo_id"], []),
                    {
                        "nome": item["nome"],
                        "email": item["email"],
                        "prontuario": item["prontuario"],
                        "curso": item["curso"],
                    },
                ),
                "codigo": item["armario_codigo"],
                "tipo": item["tipo_armario"],
                "tipo_rotulo": rotulo_tipo_armario(item["tipo_armario"]),
                "numero": item["numero_armario"],
                "identificacao": identificar_armario(item["tipo_armario"], item["numero_armario"]),
                "localizacao": obter_localizacao_armario(item["tipo_armario"], item["numero_armario"]),
                "tamanho": obter_tamanho_armario(item["tipo_armario"], item["numero_armario"]),
                "data_retirada": item["data_retirada"],
                "data_prevista": item["data_prevista"],
                "cadeado_proprio": bool(item["cadeado_proprio"]),
                "data_devolucao": item["data_devolucao"],
                "funcionario_emprestimo": item["funcionario_emprestimo_nome"] or "Nao informado",
                "funcionario_devolucao": item["funcionario_devolucao_nome"] or "Nao informado",
                "status": "ativo" if item["data_devolucao"] is None else "devolvido",
                "participantes": participantes.get(item["emprestimo_id"], []),
                "capacidade": capacidade_armario(item["tipo_armario"], item["numero_armario"]),
            }
        )

    return historico
