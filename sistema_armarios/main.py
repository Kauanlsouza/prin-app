from datetime import datetime

from database import (
    capacidade_armario,
    consultar_armario_flexivel,
    contar_armarios_por_status,
    criar_armarios,
    criar_banco,
    devolver_armario,
    emprestar_armario,
    listar_armarios,
    listar_armarios_livres,
    listar_atrasados,
)

def mostrar_armarios(lista):
    for item in lista:
        linha = (
            f"{item['identificacao']} | Status: {item['status']} | "
            f"Local: {item['localizacao']} | Tamanho: {item['tamanho']}"
        )
        if item["status"] == "ocupado":
            linha += f" | Aluno: {item['nome']} | Email: {item.get('email', '-')} | Prontuario: {item['prontuario']}"
        print(linha)


def menu():
    while True:
        hoje_str = datetime.now().strftime("%d/%m/%Y")
        hoje_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        resumo = contar_armarios_por_status()

        print("\n" + "=" * 70)
        print(f"SISTEMA DE ARMARIOS | Data: {hoje_str}")
        print(
            f"LIVRES: {resumo['livre']} | OCUPADOS: {resumo['ocupado']} | "
            f"ARMARIOS: {resumo['convencional_total']} | "
            f"GRANDES: {resumo['grandes_total']}"
        )
        print("=" * 70)
        print("1 - Listar todos armarios")
        print("2 - Emprestar armario")
        print("3 - Devolver armario")
        print("4 - Sair")
        print("5 - Consultar (por armario ou prontuario)")
        print("6 - Ver apenas armarios livres")
        print("7 - Ver atrasados")

        opcao = input("\nEscolha uma opcao: ").strip()

        if opcao == "1":
            print("\n--- Status Geral ---")
            mostrar_armarios(listar_armarios())

        elif opcao == "2":
            tipo = "convencional"
            try:
                numero = int(input("Numero do armario: "))
                quantidade = capacidade_armario(tipo, numero)
                participantes = []
                print(f"Este armario exige {quantidade} participante(s).")
                for indice in range(quantidade):
                    print(f"\nParticipante {indice + 1}")
                    nome = input("Nome do aluno: ").strip()
                    email = input("Email do responsavel: ").strip().lower()
                    prontuario = input("Prontuario: ").strip().upper()
                    print("Curso: 1-TII | 2-AVI | 3-Superior")
                    c_op = input("Opcao: ").strip()
                    curso = "TII" if c_op == "1" else "AVI" if c_op == "2" else "Superior" if c_op == "3" else ""
                    if not nome or not email or not prontuario or not curso:
                        print("[ERRO] Participante invalido.")
                        participantes = []
                        break
                    participantes.append(
                        {
                            "nome": nome,
                            "email": email,
                            "prontuario": prontuario,
                            "curso": curso,
                        }
                    )
                if len(participantes) != quantidade:
                    continue

                print(f"Data de retirada: {hoje_str}")
                data_prevista_str = input("Data prevista de devolucao (DD/MM/AAAA): ").strip()

                try:
                    dt_prevista = datetime.strptime(data_prevista_str, "%d/%m/%Y")
                    if dt_prevista < hoje_dt:
                        print("\n[ERRO] A data prevista nao pode ser no passado.")
                        continue
                except ValueError:
                    print("\n[ERRO] Formato de data invalido.")
                    continue

                _, mensagem = emprestar_armario(
                    tipo,
                    numero,
                    participantes,
                    hoje_str,
                    data_prevista_str,
                )
                print(mensagem)
            except ValueError:
                print("\n[ERRO] Entrada invalida.")

        elif opcao == "3":
            tipo = "convencional"
            try:
                numero = int(input("Numero do armario para devolucao: "))
                _, mensagem = devolver_armario(tipo, numero, hoje_str)
                print(mensagem)
            except ValueError:
                print("\n[ERRO] Digite um numero valido.")

        elif opcao == "4":
            print("Saindo...")
            break

        elif opcao == "5":
            print("\n--- Consultar por: ---")
            print("1 - Armario especifico")
            print("2 - Prontuario do aluno")
            sub_opcao = input("Escolha: ").strip()

            if sub_opcao == "1":
                tipo = "convencional"
                try:
                    valor = int(input("Digite o numero do armario: "))
                    res = consultar_armario_flexivel(valor, por_prontuario=False, tipo_armario=tipo)
                except ValueError:
                    print("Numero invalido.")
                    continue
            elif sub_opcao == "2":
                valor = input("Digite o prontuario: ").strip()
                res = consultar_armario_flexivel(valor, por_prontuario=True)
            else:
                print("Opcao invalida.")
                continue

            if res:
                print("\n>>> RESULTADO DA CONSULTA <<<")
                print(
                    f"{res['identificacao']} | Status: {res['status']} | "
                    f"Local: {res['localizacao']} | Tamanho: {res['tamanho']}"
                )
                if res["status"] == "ocupado":
                    print(f"Aluno: {res['nome']} (Email: {res.get('email', '-')}, Prontuario: {res['prontuario']})")
                    print(f"Curso: {res['curso']}")
                    print(f"Retirada: {res['data_retirada']} | Prazo: {res['data_prevista']}")
                    if datetime.strptime(res["data_prevista"], "%d/%m/%Y") < hoje_dt:
                        print("STATUS: DEVOLUCAO ATRASADA!")
                print("-" * 40)
            else:
                print("\n[AVISO] Nenhuma ocupacao ativa encontrada para este criterio.")

        elif opcao == "6":
            tipo = "convencional"
            livres = listar_armarios_livres(tipo_armario=tipo)
            print(f"\nArmarios livres ({len(livres)}):")
            if livres:
                print(", ".join(item["identificacao"] for item in livres))

        elif opcao == "7":
            atrasados = listar_atrasados()
            print("\n=== LISTA DE ATRASADOS ===")
            if atrasados:
                for item in atrasados:
                    print(
                        f"{item['identificacao']} | Aluno: {item['nome']} | Email: {item.get('email', '-')} | "
                        f"Vencimento: {item['data_prevista']}"
                    )
            else:
                print("Tudo em dia!")


def main():
    criar_banco()
    criar_armarios()
    menu()


if __name__ == "__main__":
    main()
