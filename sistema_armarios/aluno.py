class Aluno:

    def __init__(self, nome, curso, ano, total_anos):
        self.nome = nome
        self.curso = curso
        self.ano = ano
        self.total_anos = total_anos

    def ultimo_ano(self):
        return self.ano == self.total_anos