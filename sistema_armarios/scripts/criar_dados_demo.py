"""Cria uma base SQLite ficticia para demonstrar o Sistema de Armarios.

Uso:
    python scripts/criar_dados_demo.py --output dados_demo/armarios_demo.db

O argumento --output e obrigatorio para evitar sobrescrever o banco usado pela escola.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import database  # noqa: E402


FUNCIONARIO = {"id": 1, "nome": "Equipe de Demonstração"}
EMPRESTIMOS = (
    (1, ("Ana Lima", "ana.lima@example.test", "DEMO001", "TII"), -2),
    (1, ("Bia Melo", "bia.melo@example.test", "DEMO002", "TII"), -2),
    (2, ("Bruno Souza", "bruno.souza@example.test", "DEMO003", "AVI"), 4),
    (2, ("Caio Reis", "caio.reis@example.test", "DEMO004", "AVI"), 4),
    (81, ("Carla Nunes", "carla.nunes@example.test", "DEMO005", "TII"), 1),
    (81, ("Diego Alves", "diego.alves@example.test", "DEMO006", "TII"), 1),
    (81, ("Elisa Rocha", "elisa.rocha@example.test", "DEMO007", "TII"), 1),
)


def criar_base_demo(destino: Path) -> None:
    destino = destino.resolve()
    if destino == database.DB_NAME.resolve():
        raise ValueError("Escolha outro arquivo: a base de demonstração não pode substituir armarios.db.")
    if destino.exists():
        raise FileExistsError(f"O arquivo já existe: {destino}. Escolha outro nome ou remova-o manualmente.")

    destino.parent.mkdir(parents=True, exist_ok=True)
    banco_original = database.DB_NAME
    database.DB_NAME = destino
    try:
        database.criar_banco()
        database.criar_armarios()
        database.criar_primeiro_funcionario("Equipe de Demonstração", "demo", "senha-demo-segura")

        hoje = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        participantes_por_armario: dict[int, list[dict[str, str]]] = {}
        prazo_por_armario: dict[int, datetime] = {}
        for numero, participante, deslocamento in EMPRESTIMOS:
            participantes_por_armario.setdefault(numero, []).append(
                {"nome": participante[0], "email": participante[1], "prontuario": participante[2], "curso": participante[3]}
            )
            prazo_por_armario[numero] = hoje + timedelta(days=deslocamento)

        for numero, participantes in participantes_por_armario.items():
            prazo = prazo_por_armario[numero]
            ok, mensagem = database.emprestar_armario(
                "convencional",
                numero,
                participantes,
                hoje.strftime(database.DATE_FORMAT),
                prazo.strftime(database.DATE_FORMAT),
                funcionario=FUNCIONARIO,
            )
            if not ok:
                raise RuntimeError(mensagem)

        ok, mensagem = database.definir_manutencao_armario("convencional", 15, True)
        if not ok:
            raise RuntimeError(mensagem)
    finally:
        database.DB_NAME = banco_original


def main() -> None:
    parser = argparse.ArgumentParser(description="Cria uma base fictícia para demonstração.")
    parser.add_argument("--output", type=Path, required=True, help="Arquivo .db novo que será criado.")
    args = parser.parse_args()
    criar_base_demo(args.output)
    print(f"Base de demonstração criada em: {args.output}")
    print("Acesso demonstrativo: usuário demo | senha senha-demo-segura")


if __name__ == "__main__":
    main()
