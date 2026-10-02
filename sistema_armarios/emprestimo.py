class Emprestimo:

    def __init__(self, armario, alunos, data_retirada):
        self.armario = armario
        self.alunos = alunos
        self.data_retirada = data_retirada
        self.data_devolucao = None

    def devolver(self, data):
        self.data_devolucao = data
        self.armario.liberar()