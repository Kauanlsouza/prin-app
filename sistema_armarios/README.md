# Sistema de Armários

Sistema web para controle de empréstimos de armários em ambiente escolar. Foi projetado para uso em rede local, com autenticação de funcionários, rastreabilidade das movimentações e acompanhamento de prazos.

## Destaques

- Autenticação de funcionários com senha armazenada por hash PBKDF2.
- Perfis de administrador e operador, além de registro de atividades importantes.
- Empréstimo, devolução, edição e manutenção de 120 armários.
- Validação da quantidade de participantes conforme o tamanho do armário.
- Histórico paginado, filtros, ordenação, impressão e exportação CSV.
- Alertas de vencimento, consulta por prontuário e cobrança por e-mail via SMTP.
- Interface responsiva, tema claro/escuro e funcionamento em rede local.

## Tecnologias

Python (biblioteca padrão), SQLite, HTML, CSS e JavaScript. Não são necessárias dependências externas para executar a aplicação.

O frontend está organizado em `index.html`, `static/css/app.css` e `static/js/app.js`; o HTML fica focado na estrutura, enquanto estilo e comportamento têm uma fonte única.

## Executar localmente

```bash
python app.py
```

Abra `http://localhost:5000`. No primeiro acesso, crie a conta responsável na tela de login ou configure as variáveis de administrador em `.env` com base em `.env.example`.

## Demonstração segura

Para gerar uma base independente, com somente pessoas e e-mails fictícios, execute:

```bash
python scripts/criar_dados_demo.py --output dados_demo/armarios_demo.db
```

O script não substitui `armarios.db` e se recusa a sobrescrever um arquivo existente. Para abrir a demonstração, faça uma cópia do projeto em outra pasta e substitua o banco dessa cópia por `dados_demo/armarios_demo.db`. Acesso demonstrativo: `demo` / `senha-demo-segura`.

## Testes

```bash
python -m unittest discover -s tests -v
```

Os testes usam um banco temporário e não alteram `armarios.db`. O GitHub Actions também executa essa suíte a cada push e pull request.

## Cuidados antes de publicar

Nunca envie ao repositório `.env`, `armarios.db`, `configuracoes.json` ou outros dados de alunos. O arquivo `.gitignore` já protege esses arquivos novos; se algum deles já tiver sido adicionado ao Git, remova-o do índice antes do primeiro commit.

## Acesso pela rede local

O sistema deve ser iniciado em **uma única máquina da rede**. Essa máquina
mantém o banco de dados e funciona como servidor; as demais acessam pelo
navegador. Não execute cópias do sistema em cada computador.

1. Na máquina servidora, execute `python app.py` na pasta do projeto.
2. O terminal mostrará um ou mais links com `Na rede local`, por exemplo
   `http://192.168.1.50:5000`.
3. Nas outras máquinas conectadas à mesma rede, abra esse link no navegador.

O servidor aceita conexões da rede local por padrão (`APP_HOST=0.0.0.0`). A
porta padrão é `5000`; ambas podem ser alteradas criando um arquivo `.env` a
partir de `.env.example`.

## Login de funcionários

No primeiro acesso, a própria tela de login pede nome, usuário e senha do
responsável inicial. Como alternativa, é possível preencher `ADMIN_NOME`,
`ADMIN_USUARIO` e `ADMIN_SENHA` no `.env`; esses dados criam o primeiro acesso
automaticamente. Depois do login, novos acessos podem ser cadastrados em
**Configurações**. O sistema registra o funcionário responsável por cada
empréstimo e devolução.

## Cadastro de novos usuários

A tela de login possui a aba **Cadastrar**. Ela cria somente contas de **operador**, pede a confirmação da senha e exige a senha secreta de cadastro. O padrão é `armarios`, sem precisar de uma liberação prévia de administrador. Caso necessário, ela pode ser alterada com `CADASTRO_SENHA_ADM` no arquivo `.env`.

## Firewall do Windows

Se o link não abrir nas outras máquinas, permita o Python na rede privada
quando o Windows solicitar. Se o aviso não aparecer, abra o **Firewall do
Windows Defender com Segurança Avançada**, crie uma regra de entrada para TCP
na porta `5000` e limite-a ao perfil **Privado**. Não exponha essa porta à
internet.

## Cuidados

- A máquina servidora precisa ficar ligada enquanto o sistema estiver sendo usado.
- Compartilhe os acessos somente com a equipe autorizada e use senhas distintas.
- Faça cópias de segurança periódicas de `armarios.db`, com o servidor fechado.
- Administradores podem baixar uma cópia consistente pela tela **Configurações**. Para restaurar uma cópia, feche o sistema e arraste o arquivo `.db` sobre `restaurar_backup.bat`.
- A mesma área permite anonimizar dados pessoais de empréstimos devolvidos antigos. Faça uma cópia de segurança antes: essa ação não pode ser desfeita.

## Inicialização simplificada

No Windows, dê dois cliques em `iniciar_sistema.bat`. Ele abre o sistema no navegador; mantenha a janela aberta enquanto estiver usando o sistema.

## Perfis de acesso

- **Operador:** realiza empréstimos, devoluções, consultas e manutenção.
- **Administrador:** além dessas ações, cria contas, configura e-mails, envia cobranças, acessa a auditoria e gera cópias de segurança.
