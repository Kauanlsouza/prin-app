class Armario:

    def __init__(self, numero, status="livre"):
        self.numero = numero
        self.status = status

    def ocupar(self):
        self.status = "ocupado"

    def liberar(self):
        self.status = "livre"