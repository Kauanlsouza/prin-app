import threading
import unittest
import os
from http.server import ThreadingHTTPServer
from urllib.request import urlopen

import app


class AppTestCase(unittest.TestCase):
    def test_tela_login_oferece_cadastro_protegido(self):
        conteudo = app.LOGIN_FILE.read_text(encoding="utf-8")
        self.assertIn('data-modo="cadastrar"', conteudo)
        self.assertIn('"/cadastro"', conteudo)

    def test_senha_cadastro_e_lida_do_ambiente(self):
        valor_anterior = os.environ.get("CADASTRO_SENHA_ADM")
        os.environ["CADASTRO_SENHA_ADM"] = "segredo-de-teste"
        try:
            self.assertEqual(app.senha_cadastro_configurada(), "segredo-de-teste")
        finally:
            if valor_anterior is None:
                os.environ.pop("CADASTRO_SENHA_ADM", None)
            else:
                os.environ["CADASTRO_SENHA_ADM"] = valor_anterior

    def test_exportacao_csv_neutraliza_formulas(self):
        self.assertEqual(app._proteger_celula_csv("=1+1"), "'=1+1")
        self.assertEqual(app._proteger_celula_csv("Nome normal"), "Nome normal")

    def test_pagina_referencia_arquivos_estaticos_modularizados(self):
        pagina = app.renderizar_index("historico", "Histórico").decode("utf-8")
        self.assertIn('href="/static/css/app.css"', pagina)
        self.assertIn('src="/static/js/app.js" defer', pagina)
        self.assertIn('window.APP_PAGE = "historico"', pagina)

    def test_servidor_entrega_javascript_estatico(self):
        servidor = ThreadingHTTPServer(("127.0.0.1", 0), app.ArmariosHandler)
        thread = threading.Thread(target=servidor.serve_forever, daemon=True)
        thread.start()
        try:
            with urlopen(f"http://127.0.0.1:{servidor.server_port}/static/js/app.js") as resposta:
                conteudo = resposta.read().decode("utf-8-sig")
                self.assertEqual(resposta.status, 200)
                self.assertIn("function emprestar()", conteudo)
        finally:
            servidor.shutdown()
            servidor.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
