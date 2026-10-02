import tempfile
import unittest
from pathlib import Path
import sqlite3

import app
import database
from scripts.criar_dados_demo import criar_base_demo


def participante(nome, prontuario):
    return {
        "nome": nome,
        "email": f"{prontuario.lower()}@example.test",
        "prontuario": prontuario,
        "curso": "TII",
    }


class DatabaseTestCase(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_original = database.DB_NAME
        database.DB_NAME = Path(self.tempdir.name) / "teste.db"
        database.criar_banco()
        database.criar_armarios()

    def tearDown(self):
        database.DB_NAME = self.db_original
        self.tempdir.cleanup()

    def test_cria_todos_os_armarios_reais(self):
        resumo = database.contar_armarios_por_status()
        self.assertEqual(resumo["convencional_total"], 120)
        self.assertEqual(database.capacidade_armario("convencional", 81), 3)
        self.assertEqual(database.capacidade_armario("convencional", 120), 2)

    def test_emprestimo_devolucao_e_historico(self):
        alunos = [participante("Ana Lima", "TESTE001"), participante("Bia Alves", "TESTE002")]
        ok, _ = database.emprestar_armario("convencional", 1, alunos, "01/08/2026", "20/08/2026")
        self.assertTrue(ok)
        self.assertEqual(database.listar_armarios_detalhados()[0]["status"], "ocupado")

        ok, _ = database.devolver_armario("convencional", 1, "15/08/2026")
        self.assertTrue(ok)
        historico = database.listar_historico_emprestimos()
        self.assertEqual(len(historico), 1)
        self.assertEqual(historico[0]["data_devolucao"], "15/08/2026")

    def test_impede_mesmo_aluno_em_dois_emprestimos_ativos(self):
        alunos_1 = [participante("Ana Lima", "TESTE001"), participante("Bia Alves", "TESTE002")]
        alunos_2 = [participante("Ana Lima", "TESTE001"), participante("Caio Melo", "TESTE003")]
        self.assertTrue(database.emprestar_armario("convencional", 1, alunos_1, "01/08/2026", "20/08/2026")[0])
        ok, mensagem = database.emprestar_armario("convencional", 2, alunos_2, "01/08/2026", "20/08/2026")
        self.assertFalse(ok)
        self.assertIn("TESTE001", mensagem)

    def test_manutencao_bloqueia_emprestimo(self):
        self.assertTrue(database.definir_manutencao_armario("convencional", 10, True)[0])
        ok, mensagem = database.emprestar_armario(
            "convencional", 10, [participante("Ana Lima", "TESTE001"), participante("Bia Alves", "TESTE002")], "01/08/2026", "20/08/2026"
        )
        self.assertFalse(ok)
        self.assertIn("manutencao", mensagem)

    def test_funcionario_e_autenticado_por_hash(self):
        database.criar_primeiro_funcionario("Pessoa Teste", "teste", "senha-segura")
        funcionario = database.autenticar_funcionario("teste", "senha-segura")
        self.assertIsNotNone(funcionario)
        self.assertEqual(funcionario["papel"], "administrador")
        self.assertIsNone(database.autenticar_funcionario("teste", "senha-incorreta"))

    def test_papeis_e_auditoria(self):
        database.criar_primeiro_funcionario("Admin Teste", "admin", "senha-segura")
        admin = database.autenticar_funcionario("admin", "senha-segura")
        database.criar_funcionario("Operador Teste", "operador", "senha-segura", funcionario=admin)
        operador = database.autenticar_funcionario("operador", "senha-segura")
        self.assertEqual(operador["papel"], "operador")
        self.assertTrue(any(item["acao"] == "criou_funcionario" for item in database.listar_auditoria()))

    def test_impede_intervalo_de_datas_invalido(self):
        with self.assertRaises(ValueError):
            app.validar_intervalo_datas("20/08/2026", "01/08/2026")

    def test_cria_backup_consistente(self):
        destino = Path(self.tempdir.name) / "backup.db"
        database.criar_backup(destino)
        self.assertTrue(destino.is_file())
        conn = sqlite3.connect(destino)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM armarios").fetchone()[0], 120)
        finally:
            conn.close()

    def test_anonimiza_historico_devolvido(self):
        alunos = [participante("Ana Lima", "TESTE001"), participante("Bia Alves", "TESTE002")]
        self.assertTrue(database.emprestar_armario("convencional", 1, alunos, "01/08/2026", "20/08/2026")[0])
        self.assertTrue(database.devolver_armario("convencional", 1, "15/08/2026")[0])
        self.assertEqual(database.anonimizar_historico_ate("31/08/2026"), 1)
        historico = database.listar_historico_emprestimos()
        self.assertEqual(historico[0]["participantes"][0]["nome"], "Dados anonimizados")

    def test_base_demo_contem_somente_dados_ficticios(self):
        destino = Path(self.tempdir.name) / "demonstracao.db"
        criar_base_demo(destino)
        conn = sqlite3.connect(destino)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM armarios").fetchone()[0], 120)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM emprestimos").fetchone()[0], 3)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM armarios WHERE status = 'manutencao'").fetchone()[0], 1)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM emprestimo_participantes WHERE email NOT LIKE '%@example.test'").fetchone()[0],
                0,
            )
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
