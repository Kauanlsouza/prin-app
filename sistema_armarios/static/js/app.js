
const API = "";
const TIPOS_ARMARIO = {
    convencional: { rotulo: "Armario", localizacao: "Andar de cima" }
};
const CONFIGURACOES_PADRAO = {
    email_assunto: "Devolucao em atraso - {armario}",
    email_corpo:
        "Ola {nome},\n\nidentificamos que o {armario} esta com devolucao prevista para {prazo}.\nLocalizacao: {localizacao}.\n\nPedimos a regularizacao o quanto antes.\n\nEquipe de armarios"
};

let listaArmariosVisivel = true;
let armariosCache = [];
let filtroRapido = "todos";
let debounceHistorico;
let debounceConsulta;
let temaAtual = "claro";
let participantesEmprestimo = [];
let participantesEdicao = [];
let emprestimoEdicaoAtual = null;
let resultadoConsultaAtual = null;
let armarioModalAtual = null;
let historicoPagina = 1;
let historicoPorPagina = 10;
let historicoOrdenacao = "retirada";
let historicoDirecao = "desc";
let configuracoesSistema = { ...CONFIGURACOES_PADRAO };
let smtpConfigurado = false;
let funcionarioAtual = null;
const PAGINA_ATUAL = window.APP_PAGE || "inicio";
const PAGINA_POR_SECAO = {
    "secao-inicio": "inicio",
    "secao-movimentacoes": "movimentacoes",
    "secao-consulta": "consulta",
    "secao-disponibilidade": "disponibilidade",
    "secao-historico": "historico",
    "secao-configuracoes": "configuracoes",
};

const el = (id) => document.getElementById(id);

function obterPrefixoPagina() {
    const caminho = window.location.pathname || "/";
    return caminho === "/api" || caminho.startsWith("/api/") ? "/api" : "";
}

function montarUrlPagina(rota = "") {
    const prefixo = obterPrefixoPagina();
    if (!rota) return prefixo || "/";
    return prefixo ? `${prefixo}/${rota}` : `/${rota}`;
}

function aplicarLinksPagina() {
    document.querySelectorAll("[data-route]").forEach((link) => {
        link.setAttribute("href", montarUrlPagina(link.dataset.route || ""));
    });
}

function definirNavegacaoAtiva(pageKey) {
    document.querySelectorAll(".nav-link").forEach((link) => {
        link.classList.toggle("ativo", link.dataset.page === pageKey);
    });
}

function aplicarPaginaAtual() {
    Object.entries(PAGINA_POR_SECAO).forEach(([secaoId, pageKey]) => {
        const secao = el(secaoId);
        if (!secao) return;
        secao.hidden = pageKey !== PAGINA_ATUAL;
    });

    definirNavegacaoAtiva(PAGINA_ATUAL);
}

function exibirMensagem(texto, tipo = "sucesso", toast = false) {
    el("mensagem").textContent = texto;
    el("mensagem").className = `mensagem ${tipo}`;
    if (toast) mostrarToast(texto, tipo);
}

function mostrarToast(texto, tipo = "sucesso") {
    const stack = el("toast-stack");
    const item = document.createElement("div");
    item.className = `toast ${tipo}`;
    item.textContent = texto;
    stack.appendChild(item);
    setTimeout(() => item.remove(), 3600);
}

function emailValido(valor) {
    return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(String(valor || "").trim());
}

function mostrarResumoOperacao(titulo, detalhes = [], tipo = "sucesso") {
    const painel = el("feedback-operacao");
    if (!painel) return;

    const chips = detalhes
        .filter(Boolean)
        .map((detalhe) => `<span class="mini-tag">${escaparHtml(detalhe)}</span>`)
        .join("");

    painel.className = `feedback-operacao ${tipo}`;
    painel.innerHTML = `
        <div class="feedback-operacao__topo">
            <strong>${escaparHtml(titulo)}</strong>
            <button type="button" class="botao-secundario" onclick="fecharResumoOperacao()">Fechar</button>
        </div>
        ${chips ? `<div class="feedback-operacao__chips">${chips}</div>` : ""}
    `;
    painel.classList.remove("oculto");
}

function fecharResumoOperacao() {
    const painel = el("feedback-operacao");
    if (!painel) return;
    painel.classList.add("oculto");
    painel.innerHTML = "";
}

function aplicarEdicaoPendente() {
    if (PAGINA_ATUAL !== "consulta") return;
    try {
        const bruto = sessionStorage.getItem("armario_edicao_pendente");
        if (!bruto) return;
        sessionStorage.removeItem("armario_edicao_pendente");
        const item = JSON.parse(bruto);
        if (item && typeof item === "object") {
            preencherEdicaoEmprestimo(item, true);
        }
    } catch (erro) {
    }
}

function aplicarTemaSeguro(tema) {
    temaAtual = tema === "escuro" ? "escuro" : "claro";
    document.body.classList.toggle("tema-escuro", temaAtual === "escuro");
    el("tema-icone").innerHTML = temaAtual === "escuro" ? "&#9728;" : "&#9790;";
    el("tema-texto").textContent = temaAtual === "escuro" ? "Modo claro" : "Modo escuro";
    try {
        localStorage.setItem("tema_armarios", temaAtual);
    } catch (erro) {
    }
}

function alternarTema() {
    aplicarTemaSeguro(temaAtual === "escuro" ? "claro" : "escuro");
}

function formatarDataParaBR(valor) {
    if (!valor) return "";
    if (valor.includes("/")) return valor;
    const [ano, mes, dia] = valor.split("-");
    return `${dia}/${mes}/${ano}`;
}

function formatarDataParaInput(valor) {
    if (!valor) return "";
    if (valor.includes("-")) return valor;
    const [dia, mes, ano] = valor.split("/");
    return `${ano}-${mes}-${dia}`;
}

function formatarDataDeInputHoje() {
    const hoje = new Date();
    const ano = hoje.getFullYear();
    const mes = String(hoje.getMonth() + 1).padStart(2, "0");
    const dia = String(hoje.getDate()).padStart(2, "0");
    return `${ano}-${mes}-${dia}`;
}

function rotuloTipo(tipo) {
    return TIPOS_ARMARIO[tipo]?.rotulo || "Armario";
}

function limiteNumero(tipo) {
    return 120;
}

function capacidadePorTipoNumero(tipo, numero) {
    const numeroInt = Number(numero || 0);
    return numeroInt >= 81 && numeroInt <= 88 ? 3 : 2;
}

function rotuloTamanho(tamanho) {
    return tamanho === "grande" ? "Grande" : "Padrao";
}

function escaparHtml(valor) {
    return String(valor ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}

function obterLocalizacao(tipo, fallback = "") {
    if (fallback) return fallback;
    const numeroConsulta = Number(
        resultadoConsultaAtual?.numero
        || emprestimoEdicaoAtual?.numero
        || el("num")?.value
        || 0
    );
    if (numeroConsulta >= 89) return "Andar de baixo, ao lado da biblioteca";
    return fallback || TIPOS_ARMARIO[tipo]?.localizacao || "-";
}

function obterIdentificacao(item) {
    return item.identificacao || `${rotuloTipo(item.tipo)} ${item.numero}`;
}

function obterRotuloVencimento(vencimento) {
    if (vencimento === "atrasado") return "Devolucao atrasada";
    if (vencimento === "vence_hoje") return "Vence hoje";
    if (vencimento === "vence_amanha") return "Vence amanha";
    return "No prazo";
}

function rotuloStatusArmario(status) {
    if (status === "manutencao") return "Em manutencao";
    return status === "ocupado" ? "Ocupado" : "Livre";
}

function normalizarVencimento(item) {
    if (item && item.vencimento) return item.vencimento;
    if (item && item.atrasado) return "atrasado";
    if (item && item.status === "livre") return "sem_prazo";
    return "no_prazo";
}

function criarParticipanteVazio() {
    return { nome: "", email: "", prontuario: "", curso: "" };
}

function capacidadeEmprestimoAtual() {
    return capacidadePorTipoNumero(
        el("tipo-armario")?.value || "convencional",
        Number(el("num")?.value || 0),
    );
}

function descricaoCapacidadeEmprestimo(capacidade) {
    if (capacidade === 2) return "Armarios de tamanho padrao exigem 2 participantes.";
    return "Armarios grandes exigem 3 participantes cadastrados.";
}

function renderizarParticipantesEmprestimo() {
    const capacidade = capacidadeEmprestimoAtual();
    if (!participantesEmprestimo.length) participantesEmprestimo = [criarParticipanteVazio()];
    if (participantesEmprestimo.length > capacidade) {
        participantesEmprestimo = participantesEmprestimo.slice(0, capacidade);
    }

    el("emprestimo-capacidade-titulo").textContent =
        `${capacidade} participantes`;
    el("emprestimo-capacidade-texto").textContent = descricaoCapacidadeEmprestimo(capacidade);
    el("emprestimo-capacidade-badge").textContent = `${participantesEmprestimo.length}/${capacidade}`;

    const podeAdicionar = participantesEmprestimo.length < capacidade;
    const botaoAdicionar = el("botao-adicionar-participante");
    botaoAdicionar.disabled = !podeAdicionar;
    botaoAdicionar.style.display = "inline-flex";

    el("participantes-emprestimo").innerHTML = participantesEmprestimo.map((participante, indice) => `
        <div class="participante-card">
            <div class="participante-card__topo">
                <strong>Participante ${indice + 1}</strong>
                ${participantesEmprestimo.length > 1 ? `
                    <button type="button" class="participante-remover botao-secundario" onclick="removerParticipante(${indice})">-</button>
                ` : ""}
            </div>
            <input
                value="${escaparHtml(participante.nome || "")}"
                placeholder="Nome do aluno"
                oninput="atualizarParticipante(${indice}, 'nome', this.value)"
            >
            <input
                type="email"
                value="${escaparHtml(participante.email || "")}"
                placeholder="Email do responsavel"
                oninput="atualizarParticipante(${indice}, 'email', this.value)"
            >
            <input
                value="${escaparHtml(participante.prontuario || "")}"
                placeholder="Prontuario"
                oninput="atualizarParticipante(${indice}, 'prontuario', this.value)"
            >
            <select onchange="atualizarParticipante(${indice}, 'curso', this.value)">
                <option value="">Selecione o curso</option>
                <option value="TII" ${participante.curso === "TII" ? "selected" : ""}>TII</option>
                <option value="AVI" ${participante.curso === "AVI" ? "selected" : ""}>AVI</option>
                <option value="Superior" ${participante.curso === "Superior" ? "selected" : ""}>Superior</option>
            </select>
        </div>
    `).join("");
}

function atualizarParticipante(indice, campo, valor) {
    if (!participantesEmprestimo[indice]) return;
    participantesEmprestimo[indice][campo] = valor;
}

function adicionarParticipante() {
    const capacidade = capacidadeEmprestimoAtual();
    if (participantesEmprestimo.length >= capacidade) return;
    participantesEmprestimo.push(criarParticipanteVazio());
    renderizarParticipantesEmprestimo();
}

function removerParticipante(indice) {
    if (participantesEmprestimo.length === 1) return;
    participantesEmprestimo.splice(indice, 1);
    renderizarParticipantesEmprestimo();
}

function limparFormularioEmprestimo() {
    el("tipo-armario").value = "convencional";
    el("num").value = "";
    participantesEmprestimo = [criarParticipanteVazio()];
    el("cadeado-proprio").checked = false;
    el("data_prev").value = formatarDataDeInputHoje();
    renderizarParticipantesEmprestimo();
}

function limparFormularioDevolucao() {
    el("modo-devolucao").value = "armario";
    el("tipo-dev").value = "convencional";
    el("num_dev").value = "";
    el("prontuario-dev").value = "";
    atualizarModoDevolucao();
}

function capacidadeEdicaoAtual() {
    if (!emprestimoEdicaoAtual) return capacidadePorTipoNumero(el("tipo-edicao").value, el("num-edicao").value);
    return capacidadePorTipoNumero(emprestimoEdicaoAtual.tipo, emprestimoEdicaoAtual.numero);
}

function renderizarParticipantesEdicao() {
    const capacidade = capacidadeEdicaoAtual();
    if (!participantesEdicao.length) participantesEdicao = [criarParticipanteVazio()];
    if (participantesEdicao.length > capacidade) {
        participantesEdicao = participantesEdicao.slice(0, capacidade);
    }

    el("edicao-capacidade-titulo").textContent =
        `${capacidade} participantes`;
    el("edicao-capacidade-texto").textContent = descricaoCapacidadeEmprestimo(capacidade);
    el("edicao-capacidade-badge").textContent = `${participantesEdicao.length}/${capacidade}`;

    const botaoAdicionar = el("botao-adicionar-edicao");
    const podeAdicionar = participantesEdicao.length < capacidade;
    botaoAdicionar.disabled = !podeAdicionar;
    botaoAdicionar.style.display = "inline-flex";

    el("participantes-edicao").innerHTML = participantesEdicao.map((participante, indice) => `
        <div class="participante-card">
            <div class="participante-card__topo">
                <strong>Participante ${indice + 1}</strong>
                ${participantesEdicao.length > 1 ? `
                    <button type="button" class="participante-remover botao-secundario" onclick="removerParticipanteEdicao(${indice})">-</button>
                ` : ""}
            </div>
            <input
                value="${escaparHtml(participante.nome || "")}"
                placeholder="Nome do aluno"
                oninput="atualizarParticipanteEdicao(${indice}, 'nome', this.value)"
            >
            <input
                type="email"
                value="${escaparHtml(participante.email || "")}"
                placeholder="Email do responsavel"
                oninput="atualizarParticipanteEdicao(${indice}, 'email', this.value)"
            >
            <input
                value="${escaparHtml(participante.prontuario || "")}"
                placeholder="Prontuario"
                oninput="atualizarParticipanteEdicao(${indice}, 'prontuario', this.value)"
            >
            <select onchange="atualizarParticipanteEdicao(${indice}, 'curso', this.value)">
                <option value="">Selecione o curso</option>
                <option value="TII" ${participante.curso === "TII" ? "selected" : ""}>TII</option>
                <option value="AVI" ${participante.curso === "AVI" ? "selected" : ""}>AVI</option>
                <option value="Superior" ${participante.curso === "Superior" ? "selected" : ""}>Superior</option>
            </select>
        </div>
    `).join("");
}

function atualizarParticipanteEdicao(indice, campo, valor) {
    if (!participantesEdicao[indice]) return;
    participantesEdicao[indice][campo] = valor;
}

function adicionarParticipanteEdicao() {
    const capacidade = capacidadeEdicaoAtual();
    if (participantesEdicao.length >= capacidade) return;
    participantesEdicao.push(criarParticipanteVazio());
    renderizarParticipantesEdicao();
}

function removerParticipanteEdicao(indice) {
    if (participantesEdicao.length === 1) return;
    participantesEdicao.splice(indice, 1);
    renderizarParticipantesEdicao();
}

function limparEdicaoEmprestimo() {
    emprestimoEdicaoAtual = null;
    participantesEdicao = [];
    el("tipo-edicao").disabled = false;
    el("num-edicao").disabled = false;
    el("tipo-edicao").value = "convencional";
    el("num-edicao").value = "";
    el("cadeado-proprio-edicao").checked = false;
    el("data_prev_edicao").value = "";
    el("edicao-emprestimo-resumo").innerHTML = "";
    el("participantes-edicao").innerHTML = "";
    el("edicao-capacidade-titulo").textContent = "2 participantes";
    el("edicao-capacidade-texto").textContent = "Carregue um emprestimo para editar os participantes.";
    el("edicao-capacidade-badge").textContent = "0/0";
    el("edicao-emprestimo").classList.add("oculto");
    el("painel-edicao-consulta").classList.add("oculto");
    el("botao-adicionar-edicao").style.display = "none";
}

function preencherEdicaoEmprestimo(item, destacar = false) {
    const participantes = (item.participantes || []).map((participante) => ({
        nome: participante.nome || "",
        email: participante.email || "",
        prontuario: participante.prontuario || "",
        curso: participante.curso || "",
    }));
    emprestimoEdicaoAtual = item;
    participantesEdicao = participantes.length ? participantes : [criarParticipanteVazio()];
    el("tipo-edicao").value = item.tipo;
    el("num-edicao").value = item.numero;
    el("tipo-edicao").disabled = true;
    el("num-edicao").disabled = true;
    el("cadeado-proprio-edicao").checked = !!item.cadeado_proprio;
    el("data_prev_edicao").value = formatarDataParaInput(item.data_prevista || "");
    el("edicao-emprestimo-resumo").innerHTML = `
        <strong>${escaparHtml(obterIdentificacao(item))}</strong>
        <p>Retirada em ${escaparHtml(item.data_retirada || "-")} | Prazo atual ${escaparHtml(item.data_prevista || "-")} | ${escaparHtml(obterLocalizacao(item.tipo, item.localizacao))}</p>
    `;
    el("painel-edicao-consulta").classList.remove("oculto");
    el("edicao-emprestimo").classList.remove("oculto");
    renderizarParticipantesEdicao();
    if (destacar) {
        document.getElementById("edicao-emprestimo").scrollIntoView({ behavior: "smooth", block: "start" });
        exibirMensagem("Emprestimo carregado para edicao.", "sucesso", true);
    }
}

function abrirEdicaoDaConsulta() {
    if (!resultadoConsultaAtual) {
        exibirMensagem("Faça uma consulta de um emprestimo ativo primeiro.", "erro", true);
        return;
    }
    if (PAGINA_ATUAL !== "consulta") {
        try {
            sessionStorage.setItem("armario_edicao_pendente", JSON.stringify(resultadoConsultaAtual));
        } catch (erro) {
        }
        window.location.href = montarUrlPagina("consulta.html");
        return;
    }
    preencherEdicaoEmprestimo(resultadoConsultaAtual, true);
}

function abrirEdicaoDoArmario(item) {
    if (!item || item.status !== "ocupado") {
        exibirMensagem("Somente armarios ocupados possuem emprestimo para editar.", "erro", true);
        return;
    }
    resultadoConsultaAtual = item;
    fecharModalArmario();
    abrirEdicaoDaConsulta();
}

function abrirEdicaoDoArmarioPorNumero(numero) {
    const item = armariosCache.find((armario) => Number(armario.numero) === Number(numero));
    abrirEdicaoDoArmario(item);
}

async function salvarEdicaoEmprestimo() {
    if (!emprestimoEdicaoAtual) {
        exibirMensagem("Carregue um emprestimo antes de salvar.", "erro", true);
        return;
    }

    setBotoesDesabilitados(["botao-salvar-edicao"], true, "Salvando...");
    try {
        const participantes = participantesEdicao.map((participante) => ({
            nome: participante.nome.trim(),
            email: participante.email.trim().toLowerCase(),
            prontuario: participante.prontuario.trim().toUpperCase(),
            curso: participante.curso.trim()
        }));
        const capacidade = capacidadeEdicaoAtual();
        validarParticipantesAntesDeEnviar(participantes, capacidade);
        const prazoAtualizado = formatarDataParaBR(el("data_prev_edicao").value.trim());

        const data = await buscarJson("/emprestimo/atualizar", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                tipo_armario: emprestimoEdicaoAtual.tipo,
                numero: emprestimoEdicaoAtual.numero,
                participantes,
                data_prevista: prazoAtualizado,
                cadeado_proprio: el("cadeado-proprio-edicao").checked
            })
        });
        exibirMensagem(data.mensagem || "Emprestimo atualizado com sucesso.", "sucesso", true);
        mostrarResumoOperacao("Emprestimo atualizado", [
            obterIdentificacao(emprestimoEdicaoAtual),
            `${participantes.length} participante(s)`,
            `Novo prazo ${prazoAtualizado || "-"}`,
        ]);
        await atualizarTudo(true);
        const consultaAtualizada = await buscarJson(`/consultar?${new URLSearchParams({
            tipo: "numero",
            valor: String(emprestimoEdicaoAtual.numero),
            tipo_armario: emprestimoEdicaoAtual.tipo
        }).toString()}`);
        if (consultaAtualizada.resultado) preencherEdicaoEmprestimo(consultaAtualizada.resultado, false);
    } catch (erro) {
        exibirMensagem(erro.message, "erro", true);
    } finally {
        setBotoesDesabilitados(["botao-salvar-edicao"], false, "Salvando...");
    }
}

function setBotoesDesabilitados(ids, desabilitado, texto) {
    ids.forEach((id) => {
        const botao = el(id);
        if (!botao) return;
        if (!botao.dataset.labelOriginal) botao.dataset.labelOriginal = botao.textContent;
        botao.disabled = desabilitado;
        botao.textContent = desabilitado ? texto : botao.dataset.labelOriginal;
    });
}

function obterParametrosHistorico() {
    const params = new URLSearchParams();
    [
        ["nome", "hist-nome"],
        ["prontuario", "hist-prontuario"],
        ["tipo_armario", "hist-tipo"],
        ["status", "hist-status"],
        ["data_inicio", "hist-data-inicio"],
        ["data_fim", "hist-data-fim"]
    ].forEach(([chave, id]) => {
        const valor = el(id).value.trim();
        if (valor) params.append(chave, valor);
    });
    params.set("pagina", String(historicoPagina));
    params.set("por_pagina", String(historicoPorPagina));
    params.set("ordenar_por", historicoOrdenacao);
    params.set("direcao", historicoDirecao);
    return params;
}

function descricaoOrdenacaoHistorico(campo) {
    const mapa = {
        armario: "armario",
        tipo: "tipo",
        localizacao: "localizacao",
        tamanho: "tamanho",
        participante_1: "participante 1",
        participante_2: "participante 2",
        participante_3: "participante 3",
        retirada: "retirada",
        prevista: "prevista",
        devolucao: "devolucao",
        status: "status",
    };
    return mapa[campo] || "retirada";
}

function iconeOrdenacaoHistorico(campo) {
    if (historicoOrdenacao !== campo) return "::";
    return historicoDirecao === "asc" ? "^" : "v";
}

function ordenarHistoricoPor(campo) {
    if (historicoOrdenacao === campo) {
        historicoDirecao = historicoDirecao === "asc" ? "desc" : "asc";
    } else {
        historicoOrdenacao = campo;
        historicoDirecao = campo === "armario" || campo === "tipo" || campo.startsWith("participante") ? "asc" : "desc";
    }
    historicoPagina = 1;
    carregarHistorico(true);
}

function irParaPaginaHistorico(pagina) {
    historicoPagina = Math.max(1, pagina);
    carregarHistorico(true);
}

function agruparPorTipo(lista) {
    return lista.reduce((acc, item) => {
        const tipo = item.tipo || "convencional";
        if (!acc[tipo]) acc[tipo] = [];
        acc[tipo].push(item);
        return acc;
    }, {});
}

async function tratarResposta(res) {
    let data = {};
    try {
        data = await res.json();
    } catch (erro) {
        throw new Error("Resposta invalida do servidor.");
    }
    if (!res.ok || data.ok === false) throw new Error(data.mensagem || "Nao foi possivel concluir a operacao.");
    return data;
}

async function buscarJson(caminho, opcoes) {
    const resposta = await fetch(`${API}${caminho}`, opcoes);
    return tratarResposta(resposta);
}

async function carregarSessao() {
    try {
        const data = await buscarJson("/sessao");
        funcionarioAtual = data.funcionario;
        el("sessao-funcionario").textContent = `Funcionario logado: ${data.funcionario.nome} (@${data.funcionario.usuario}) — ${data.funcionario.papel || "operador"}.`;
        if (data.funcionario.papel !== "administrador") {
            document.querySelectorAll(".admin-only").forEach((item) => item.classList.add("oculto"));
        }
    } catch (erro) {
        window.location.assign("/login");
        throw erro;
    }
}

async function sairDoSistema() {
    await fetch(`${API}/logout`, { method: "POST" });
    window.location.assign("/login");
}

async function carregarFuncionarios() {
    if (PAGINA_ATUAL !== "configuracoes" || funcionarioAtual?.papel !== "administrador") return;
    const data = await buscarJson("/funcionarios");
    el("lista-funcionarios").innerHTML = (data.funcionarios || []).map((item) =>
        `<div class="funcionario-item"><strong>${escaparHtml(item.nome)}</strong><span class="dica">Usuario: @${escaparHtml(item.usuario)} · ${escaparHtml(item.papel)}</span></div>`
    ).join("") || "<p>Nenhum funcionario cadastrado.</p>";
}

async function cadastrarFuncionario(event) {
    if (event) event.preventDefault();
    try {
        const data = await buscarJson("/funcionarios", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ nome: el("funcionario-nome").value, usuario: el("funcionario-usuario").value, senha: el("funcionario-senha").value, papel: el("funcionario-papel").value })
        });
        ["funcionario-nome", "funcionario-usuario", "funcionario-senha"].forEach((id) => el(id).value = "");
        exibirMensagem(data.mensagem, "sucesso", true);
        await carregarFuncionarios();
    } catch (erro) { exibirMensagem(erro.message, "erro", true); }
}

async function carregarAuditoria() {
    if (PAGINA_ATUAL !== "configuracoes" || funcionarioAtual?.papel !== "administrador") return;
    const data = await buscarJson("/auditoria");
    el("lista-auditoria").innerHTML = (data.eventos || []).map((item) =>
        `<div class="funcionario-item"><strong>${escaparHtml(item.acao)}</strong><span class="dica">${escaparHtml(item.criado_em)} · ${escaparHtml(item.funcionario_nome || "Sistema")}</span><span class="dica">${escaparHtml(item.recurso)} ${item.detalhes ? `· ${escaparHtml(item.detalhes)}` : ""}</span></div>`
    ).join("") || "<p>Nenhuma atividade registrada ainda.</p>";
}

function baixarBackup() {
    window.location.assign(`${API}/backup`);
}

async function restaurarBackup() {
    const arquivo = el("arquivo-backup").files?.[0];
    if (!arquivo) {
        exibirMensagem("Selecione um arquivo de backup .db.", "erro", true);
        return;
    }
    if (!arquivo.name.toLowerCase().endsWith(".db")) {
        exibirMensagem("Selecione um arquivo com extensao .db.", "erro", true);
        return;
    }
    const confirmado = window.confirm(`O backup "${arquivo.name}" vai substituir todos os dados atuais. Antes da troca, sera criada uma copia do banco atual na pasta backups. Deseja continuar?`);
    if (!confirmado) return;

    try {
        const resposta = await fetch(`${API}/backup/restaurar`, {
            method: "POST",
            headers: { "Content-Type": "application/octet-stream" },
            body: arquivo,
        });
        const data = await tratarResposta(resposta);
        el("arquivo-backup").value = "";
        exibirMensagem(data.mensagem, "sucesso", true);
        await carregarSessao();
        await carregarConfiguracoes();
        await carregarFuncionarios();
        await carregarAuditoria();
        await atualizarTudo(true);
    } catch (erro) {
        exibirMensagem(erro.message || "Nao foi possivel restaurar o backup.", "erro", true);
    }
}
async function anonimizarHistorico() {
    const dataLimite = el("data-anonimizacao").value;
    if (!dataLimite) {
        exibirMensagem("Escolha a data limite antes de anonimizar.", "erro", true);
        return;
    }
    if (!window.confirm("Esta acao remove dados pessoais do historico e nao pode ser desfeita. Continuar?")) return;
    try {
        const data = await buscarJson("/privacidade/anonimizar", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ data_limite: dataLimite }),
        });
        exibirMensagem(data.mensagem, "sucesso", true);
        await carregarAuditoria();
    } catch (erro) { exibirMensagem(erro.message, "erro", true); }
}

function aplicarConfiguracoesNaTela() {
    el("config-email-assunto").value = configuracoesSistema.email_assunto || CONFIGURACOES_PADRAO.email_assunto;
    el("config-email-corpo").value = configuracoesSistema.email_corpo || CONFIGURACOES_PADRAO.email_corpo;
    el("config-smtp-status").innerHTML = smtpConfigurado
        ? '<span class="mini-tag">SMTP configurado e pronto para enviar cobrancas.</span>'
        : '<span class="mini-tag">SMTP ainda nao configurado. Preencha o arquivo .env para liberar o envio real de email.</span>';
}

async function carregarConfiguracoes() {
    if (PAGINA_ATUAL === "configuracoes" && funcionarioAtual?.papel !== "administrador") return;
    try {
        const data = await buscarJson("/configuracoes");
        configuracoesSistema = { ...CONFIGURACOES_PADRAO, ...(data.configuracoes || {}) };
        smtpConfigurado = !!data.smtp_configurado;
    } catch (erro) {
        configuracoesSistema = { ...CONFIGURACOES_PADRAO };
        smtpConfigurado = false;
    }
    aplicarConfiguracoesNaTela();
}

async function salvarConfiguracoes() {
    try {
        const data = await buscarJson("/configuracoes", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                email_assunto: el("config-email-assunto").value.trim(),
                email_corpo: el("config-email-corpo").value.trim()
            })
        });
        configuracoesSistema = { ...CONFIGURACOES_PADRAO, ...(data.configuracoes || {}) };
        smtpConfigurado = !!data.smtp_configurado;
        aplicarConfiguracoesNaTela();
        exibirMensagem(data.mensagem || "Configuracoes salvas com sucesso.", "sucesso", true);
        mostrarResumoOperacao("Configuracoes atualizadas", [
            "Texto padrao de cobranca salvo",
            smtpConfigurado ? "SMTP pronto" : "SMTP pendente",
        ]);
    } catch (erro) {
        exibirMensagem(erro.message, "erro", true);
    }
}

function restaurarConfiguracoesPadrao() {
    configuracoesSistema = { ...CONFIGURACOES_PADRAO };
    aplicarConfiguracoesNaTela();
    exibirMensagem("Texto padrao restaurado na tela. Clique em salvar para aplicar.", "sucesso", true);
}

function renderizarParticipanteColuna(participante, indice) {
    if (!participante) {
        return `
            <div class="participante-coluna participante-coluna--vazia">
                <span class="participante-coluna__rotulo">Participante ${indice}</span>
                <strong>-</strong>
                <small>Sem participante nesta vaga.</small>
            </div>
        `;
    }

    return `
        <div class="participante-coluna">
            <span class="participante-coluna__rotulo">Participante ${indice}</span>
            <strong>${escaparHtml(participante.nome || "-")}</strong>
            <small>Email: ${escaparHtml(participante.email || "-")}</small>
            <small>Prontuario: ${escaparHtml(participante.prontuario || "-")}</small>
            <small>Curso: ${escaparHtml(participante.curso || "-")}</small>
        </div>
    `;
}

function renderizarAgendaGrupo(titulo, descricao, itens, classe) {
    return `
        <article class="agenda-card ${classe}">
            <h4>${titulo}</h4>
            <p>${descricao}</p>
            <span class="agenda-contador">${itens.length} registro(s)</span>
            <div class="agenda-lista">
                ${itens.length ? itens.map((item) => `
                    <div class="agenda-item">
                        <div class="agenda-item__topo">
                            <div class="agenda-item__titulo">${escaparHtml(obterIdentificacao(item))}</div>
                            <span class="mini-tag">${escaparHtml(item.data_prevista || "-")}</span>
                        </div>
                        <div class="agenda-item__meta">${escaparHtml(item.nome || "-")}</div>
                        <div class="agenda-item__meta">${escaparHtml(obterLocalizacao(item.tipo, item.localizacao))} | ${escaparHtml(rotuloTamanho(item.tamanho))}</div>
                    </div>
                `).join("") : '<div class="estado-vazio">Nenhuma devolucao prevista neste intervalo.</div>'}
            </div>
        </article>
    `;
}

function renderizarAgendaDevolucoes(agenda) {
    const grupos = agenda || {};
    return `
        <div class="agenda-blocos">
            ${renderizarAgendaGrupo("Vence hoje", "Prioridade mais alta para o turno atual.", grupos.vence_hoje || [], "agenda-card--hoje")}
            ${renderizarAgendaGrupo("Vence amanha", "Ja deixa a equipe preparada para o proximo dia.", grupos.vence_amanha || [], "agenda-card--amanha")}
            ${renderizarAgendaGrupo("Proximos 7 dias", "Planejamento curto para nao concentrar devolucoes no ultimo momento.", grupos.proximos_7_dias || [], "agenda-card--semana")}
        </div>
    `;
}

async function carregarResumo() {
    try {
        const data = await buscarJson("/resumo");
        el("resumo-livre").textContent = data.resumo.livre;
        el("resumo-ocupado").textContent = data.resumo.ocupado;
        el("resumo-atrasado").textContent = data.resumo.atrasados;
        el("resumo-convencional").textContent = data.resumo.convencional_total;
        el("resumo-grande").textContent = data.resumo.grandes_total;
        el("resumo-vence-hoje").textContent = data.resumo.vence_hoje;
        el("resumo-vence-amanha").textContent = data.resumo.vence_amanha;
        el("resumo-proximos-sete").textContent = data.resumo.proximos_7_dias;
        el("resumo-ocupacao").textContent = `${data.resumo.ocupacao_percentual}%`;
        el("agenda-devolucoes").innerHTML = renderizarAgendaDevolucoes(data.agenda);
        el("alerta-atrasos").textContent = data.resumo.atrasados > 0
            ? `${data.resumo.atrasados} armario(s) com devolucao atrasada.`
            : "Nenhum atraso no momento.";
    } catch (erro) {
        exibirMensagem(erro.message, "erro");
    }
}

async function listar() {
    const data = await buscarJson("/armarios");
    armariosCache = data.armarios;
    renderizarArmariosFiltrados();
}

function definirFiltroRapido(valor) {
    filtroRapido = valor;
    document.querySelectorAll(".chip").forEach((chip) => {
        chip.classList.toggle("ativo", chip.dataset.filtro === valor);
    });
    renderizarArmariosFiltrados();
}

function filtroRapidoCombina(item) {
    const vencimento = normalizarVencimento(item);
    if (filtroRapido === "todos") return true;
    if (filtroRapido === "livre") return item.status === "livre";
    if (filtroRapido === "ocupado") {
        return item.status === "manutencao" || (item.status === "ocupado" && vencimento === "no_prazo");
    }
    return vencimento === filtroRapido;
}

function quantidadeParticipantes(item) {
    const participantes = item.participantes || [];
    return participantes.length || (item.nome ? 1 : 0);
}

function renderizarIndicadorCadeado(item) {
    const possuiCadeado = !!item.cadeado_proprio;
    return `
        <label class="campo-cadeado campo-cadeado--leitura">
            <input type="checkbox" ${possuiCadeado ? "checked" : ""} disabled aria-label="Cadeado proprio">
            <span class="campo-cadeado__texto">
                <strong>Cadeado proprio</strong>
                <small>${possuiCadeado ? "Os participantes utilizam cadeado proprio." : "Nao ha cadeado proprio informado."}</small>
            </span>
        </label>
    `;
}

function resumoParticipantesCurto(item) {
    const participantes = item.participantes || [];
    if (!participantes.length) return "Disponivel para novo emprestimo";
    const nomes = participantes.map((participante) => participante.nome).filter(Boolean);
    if (!nomes.length) return `${quantidadeParticipantes(item)} participante(s) ativos`;
    if (nomes.length === 1) return nomes[0];
    return `${nomes[0]} + ${nomes.length - 1}`;
}

function renderizarDetalhesParticipantes(item) {
    const participantes = item.participantes || [];
    if (!participantes.length) {
        const emManutencao = item.status === "manutencao";
        return `
            <div class="armario-detalhes-grid">
                <div class="armario-detalhes-card">
                    <span>Status</span>
                    <strong>${emManutencao ? "Em manutencao" : "Disponivel"}</strong>
                </div>
                <div class="armario-detalhes-card">
                    <span>Capacidade</span>
                    <strong>${item.capacidade || 1} vaga(s)</strong>
                </div>
                ${emManutencao ? `<div class="armario-detalhes-card"><span>Reservas</span><strong>Bloqueadas durante a manutencao</strong></div>` : ""}
                <div class="armario-detalhes-card">
                    <span>Localizacao</span>
                    <strong>${escaparHtml(obterLocalizacao(item.tipo, item.localizacao))}</strong>
                </div>
                <div class="armario-detalhes-card">
                    <span>Tamanho</span>
                    <strong>${escaparHtml(rotuloTamanho(item.tamanho))}</strong>
                </div>
                <div class="armario-detalhes-card">${renderizarIndicadorCadeado(item)}</div>
            </div>
        `;
    }

    return `
        <div class="armario-detalhes-grid">
            ${participantes.map((participante, indice) => `
                <div class="armario-detalhes-card">
                    <span>Participante ${indice + 1}</span>
                    <strong>${escaparHtml(participante.nome || "-")}</strong>
                    <small>${escaparHtml(participante.email || "Email nao informado")}</small>
                    <small>Prontuario ${escaparHtml(participante.prontuario || "-")}</small>
                    <small>Curso ${escaparHtml(participante.curso || "-")}</small>
                </div>
            `).join("")}
            <div class="armario-detalhes-card">
                <span>Prazo</span>
                <strong>${escaparHtml(item.data_prevista || "-")}</strong>
                <small>Retirada ${escaparHtml(item.data_retirada || "-")}</small>
            </div>
            <div class="armario-detalhes-card">
                <span>Localizacao</span>
                <strong>${escaparHtml(obterLocalizacao(item.tipo, item.localizacao))}</strong>
                <small>${escaparHtml(rotuloTamanho(item.tamanho))}</small>
            </div>
            <div class="armario-detalhes-card">${renderizarIndicadorCadeado(item)}</div>
        </div>
    `;
}

function parseDataBr(valor) {
    if (!valor || !String(valor).includes("/")) return null;
    const [dia, mes, ano] = String(valor).split("/");
    const data = new Date(Number(ano), Number(mes) - 1, Number(dia));
    return Number.isNaN(data.getTime()) ? null : data;
}

function calcularDiasAtraso(item) {
    const dataPrevista = parseDataBr(item?.data_prevista);
    if (!dataPrevista) return 0;
    const hojeAtual = new Date();
    hojeAtual.setHours(0, 0, 0, 0);
    return Math.max(0, Math.floor((hojeAtual - dataPrevista) / 86400000));
}

function classificarFaixaAtraso(item) {
    const dias = calcularDiasAtraso(item);
    if (dias <= 1) return "atraso-recente";
    if (dias <= 3) return "atraso-moderado";
    return "atraso-critico";
}

function descricaoFaixaAtraso(item) {
    const dias = calcularDiasAtraso(item);
    if (dias <= 1) return "Atrasado hoje";
    if (dias <= 3) return `${dias} dias de atraso`;
    return `${dias} dias ou mais`;
}

function renderizarBotaoCobranca(item, rotulo = "Enviar cobranca automatica") {
    if (!item || normalizarVencimento(item) !== "atrasado") return "";
    const possuiEmails = emailsResponsaveis(item).length > 0;
    return `
        <button
            type="button"
            class="botao-secundario botao-cobranca"
            ${possuiEmails ? "" : "disabled"}
            onclick="cobrarAtrasado('${escaparHtml(item.tipo)}', ${Number(item.numero || 0)})"
        >
            ${possuiEmails ? rotulo : "Sem email cadastrado"}
        </button>
    `;
}

function renderizarResumoExpandidoArmario(item) {
    const vencimento = normalizarVencimento(item);
    const quantidade = quantidadeParticipantes(item);
    const prazo = item.status === "ocupado" ? (item.data_prevista || "-") : "Sem prazo";
    return `
        <div class="armario-detalhes-resumo">
            <span class="mini-tag">${quantidade}/${item.capacidade || 1} participante(s)</span>
            <span class="mini-tag">${rotuloTamanho(item.tamanho)}</span>
            <span class="mini-tag">${item.status === "manutencao" ? "Indisponivel para reservas" : escaparHtml(obterRotuloVencimento(vencimento))}</span>
            <span class="mini-tag">Prazo: ${escaparHtml(prazo)}</span>
        </div>
    `;
}

function renderizarConteudoModalArmario(item) {
    return `
        <div class="armario-modal__backdrop" onclick="fecharModalArmario()"></div>
        <div class="armario-modal__card ${item.status === "livre" ? "livre" : item.status === "manutencao" ? "manutencao" : normalizarVencimento(item).replaceAll("_", "-")}" role="dialog" aria-modal="true" aria-label="${escaparHtml(obterIdentificacao(item))}">
            <div class="armario-modal__topo">
                <div>
                    <div class="armario-numero">${obterIdentificacao(item)}</div>
                    <div class="armario-modal__meta">${escaparHtml(obterLocalizacao(item.tipo, item.localizacao))}</div>
                </div>
                <div class="armario-modal__acoes">
                    <span class="armario-status">${rotuloStatusArmario(item.status)}</span>
                    ${item.status === "ocupado" ? `<button type="button" class="botao-secundario botao-lapis" onclick="abrirEdicaoDoArmarioPorNumero(${Number(item.numero)})" aria-label="Editar emprestimo" title="Editar emprestimo">&#9998;</button>` : ""}
                    ${item.status === "livre" ? `<button type="button" class="botao-manutencao" onclick="alterarManutencaoArmario('${escaparHtml(item.tipo)}', ${Number(item.numero)}, true)">Colocar em manutencao</button>` : ""}
                    ${item.status === "manutencao" ? `<button type="button" class="botao-manutencao" onclick="alterarManutencaoArmario('${escaparHtml(item.tipo)}', ${Number(item.numero)}, false)">Liberar manutencao</button>` : ""}
                    <button type="button" class="botao-secundario armario-modal__fechar" onclick="fecharModalArmario()">Fechar</button>
                </div>
            </div>
            <section class="armario-modal__secao">
                <h3 class="armario-modal__secao-titulo">Situacao do armario</h3>
                ${renderizarResumoExpandidoArmario(item)}
            </section>
            <section class="armario-modal__secao">
                <h3 class="armario-modal__secao-titulo">${item.status === "ocupado" ? "Participantes e emprestimo" : "Detalhes do armario"}</h3>
                ${renderizarDetalhesParticipantes(item)}
            </section>
        </div>
    `;
}

async function alterarManutencaoArmario(tipo, numero, emManutencao) {
    const botao = document.querySelector(".botao-manutencao");
    if (botao) botao.disabled = true;
    try {
        const data = await buscarJson("/manutencao", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ tipo_armario: tipo, numero, em_manutencao: emManutencao })
        });
        exibirMensagem(data.mensagem || "Status do armario atualizado.", "sucesso", true);
        await atualizarTudo(true);
    } catch (erro) {
        exibirMensagem(erro.message, "erro", true);
        if (botao) botao.disabled = false;
    }
}

function fecharModalArmario() {
    armarioModalAtual = null;
    const modal = el("armario-modal");
    modal.classList.remove("ativo");
    modal.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
    window.setTimeout(() => {
        if (armarioModalAtual) return;
        modal.classList.add("oculto");
        modal.innerHTML = "";
    }, 220);
}

function abrirModalArmario(numero) {
    const item = armariosCache.find((armario) => Number(armario.numero) === Number(numero));
    if (!item) return;
    armarioModalAtual = Number(item.numero);
    const modal = el("armario-modal");
    modal.innerHTML = renderizarConteudoModalArmario(item);
    modal.classList.remove("oculto");
    modal.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
    window.requestAnimationFrame(() => modal.classList.add("ativo"));
}

function sincronizarModalArmarioAberto() {
    if (!armarioModalAtual) return;
    const item = armariosCache.find((armario) => Number(armario.numero) === Number(armarioModalAtual));
    if (!item) {
        fecharModalArmario();
        return;
    }
    const modal = el("armario-modal");
    modal.innerHTML = renderizarConteudoModalArmario(item);
    modal.classList.add("ativo");
}

function renderizarGrupoArmarios(tipo, lista) {
    if (!lista.length) return "";
    const localizacao = obterLocalizacao(tipo, lista[0]?.localizacao);
    return `
        <section class="grupo-armarios">
            <div class="grupo-cabecalho">
                <div class="grupo-titulo">
                    <strong>${rotuloTipo(tipo)}</strong>
                    <span>${localizacao}</span>
                </div>
                <span class="mini-tag">${lista.length} armario(s)</span>
            </div>
            <div class="grupo-lista">
                ${lista.map((item) => {
                    const vencimento = normalizarVencimento(item);
                    const classe = item.status === "livre" ? "livre" : item.status === "manutencao" ? "manutencao" : vencimento.replaceAll("_", "-");
                    return `
                        <article
                            class="armario-item ${classe}"
                            role="button"
                            tabindex="0"
                            onclick="abrirModalArmario(${Number(item.numero || 0)})"
                            onkeydown="if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); abrirModalArmario(${Number(item.numero || 0)}); }"
                        >
                            <div class="armario-resumo">
                                <div class="armario-topo">
                                    <div class="armario-numero">${obterIdentificacao(item)}</div>
                                    <span class="armario-status">${rotuloStatusArmario(item.status)}</span>
                                </div>
                            </div>
                        </article>
                    `;
                }).join("")}
            </div>
        </section>
    `;
}

function renderizarArmariosFiltrados() {
    const destino = el("lista");
    const filtro = el("filtro-armario").value.trim().toLowerCase();
    const armariosFiltrados = armariosCache.filter((item) => {
        const vencimento = normalizarVencimento(item);
        const texto = [
            String(item.numero),
            item.tipo || "",
            rotuloTipo(item.tipo),
            item.status || "",
            item.nome || "",
            item.email || "",
            item.prontuario || "",
            item.curso || "",
            (item.participantes || []).map((participante) => [participante.nome, participante.email, participante.prontuario, participante.curso].join(" ")).join(" "),
            item.localizacao || "",
            item.tamanho || "",
            vencimento
        ].join(" ").toLowerCase();
        return texto.includes(filtro) && filtroRapidoCombina(item);
    });

    if (!armariosFiltrados.length) {
        destino.innerHTML = "<p>Nenhum armario corresponde aos filtros atuais.</p>";
        return;
    }

    destino.innerHTML = renderizarGrupoArmarios("convencional", armariosFiltrados);
    sincronizarModalArmarioAberto();
}

async function alternarListaArmarios() {
    const wrapper = el("lista-wrapper");
    const botao = el("botao-lista");
    if (listaArmariosVisivel) {
        wrapper.classList.add("oculto");
        botao.textContent = "Mostrar painel";
        listaArmariosVisivel = false;
        exibirMensagem("Painel de armarios ocultado.");
        return;
    }
    try {
        await listar();
        wrapper.classList.remove("oculto");
        botao.textContent = "Esconder painel";
        listaArmariosVisivel = true;
        exibirMensagem("Painel de armarios exibido.");
    } catch (erro) {
        exibirMensagem(erro.message, "erro");
    }
}

async function atualizarListaSeVisivel() {
    if (listaArmariosVisivel) await listar();
}

function validarParticipantesAntesDeEnviar(participantes, capacidade) {
    if (participantes.length !== capacidade) {
        throw new Error(`Este armario exige ${capacidade} participante(s) cadastrados.`);
    }

    participantes.forEach((participante, indice) => {
        if (!participante.nome || !participante.email || !participante.prontuario || !participante.curso) {
            throw new Error(`Preencha nome, email, prontuario e curso do participante ${indice + 1}.`);
        }
        if (!emailValido(participante.email)) {
            throw new Error(`Informe um email valido para o participante ${indice + 1}.`);
        }
    });
}

async function emprestar() {
    setBotoesDesabilitados(["botao-emprestar"], true, "Enviando...");
    try {
        const participantes = participantesEmprestimo.map((participante) => ({
            nome: participante.nome.trim(),
            email: participante.email.trim().toLowerCase(),
            prontuario: participante.prontuario.trim().toUpperCase(),
            curso: participante.curso.trim()
        }));
        const capacidade = capacidadeEmprestimoAtual();
        validarParticipantesAntesDeEnviar(participantes, capacidade);
        const identificacao = `${rotuloTipo(el("tipo-armario").value)} ${el("num").value.trim() || "-"}`;
        const prazoEmprestimo = formatarDataParaBR(el("data_prev").value.trim()) || "-";

        const data = await buscarJson("/emprestar", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                tipo_armario: el("tipo-armario").value.trim(),
                numero: el("num").value.trim(),
                participantes,
                data_retirada: formatarDataParaBR(formatarDataDeInputHoje()),
                data_prevista: prazoEmprestimo,
                cadeado_proprio: el("cadeado-proprio").checked
            })
        });
        limparFormularioEmprestimo();
        exibirMensagem(data.mensagem || "Emprestimo realizado com sucesso.", "sucesso", true);
        mostrarResumoOperacao("Emprestimo registrado", [
            identificacao,
            `${participantes.length} participante(s)`,
            `Prazo ${prazoEmprestimo}`,
        ]);
        await atualizarTudo(true);
    } catch (erro) {
        exibirMensagem(erro.message, "erro", true);
    } finally {
        setBotoesDesabilitados(["botao-emprestar"], false, "Enviando...");
    }
}

async function devolver() {
    setBotoesDesabilitados(["botao-devolver"], true, "Processando...");
    try {
        const modo = el("modo-devolucao").value;
        let tipoArmario = "";
        let numeroArmario = "";
        let identificacao = "";

        if (modo === "prontuario") {
            const prontuario = el("prontuario-dev").value.trim().toUpperCase();
            if (!prontuario) throw new Error("Informe o prontuario para localizar a devolucao.");
            const consulta = await buscarJson(`/consultar?${new URLSearchParams({
                tipo: "prontuario",
                valor: prontuario,
                tipo_armario: el("tipo-dev").value
            }).toString()}`);
            if (!consulta.resultado || consulta.resultado.status !== "ocupado") {
                throw new Error("Nenhum emprestimo ativo foi encontrado para esse prontuario.");
            }
            tipoArmario = consulta.resultado.tipo;
            numeroArmario = String(consulta.resultado.numero);
            identificacao = obterIdentificacao(consulta.resultado);
            if (!window.confirm(`Confirmar a devolucao completa de ${identificacao} localizado pelo prontuario ${prontuario}?`)) {
                return;
            }
        } else {
            tipoArmario = el("tipo-dev").value.trim();
            numeroArmario = el("num_dev").value.trim();
            identificacao = `${rotuloTipo(tipoArmario)} ${numeroArmario || "-"}`;
            if (!window.confirm(`Confirmar a devolucao completa de ${identificacao}?`)) {
                return;
            }
        }

        const data = await buscarJson("/devolver", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                tipo_armario: tipoArmario,
                numero: numeroArmario,
                data: formatarDataParaBR(formatarDataDeInputHoje())
            })
        });
        limparFormularioDevolucao();
        exibirMensagem(data.mensagem || "Devolucao realizada com sucesso.", "sucesso", true);
        mostrarResumoOperacao("Devolucao concluida", [
            identificacao,
            `Devolvido em ${formatarDataParaBR(formatarDataDeInputHoje())}`,
        ]);
        await atualizarTudo(true);
    } catch (erro) {
        exibirMensagem(erro.message, "erro", true);
    } finally {
        setBotoesDesabilitados(["botao-devolver"], false, "Processando...");
    }
}

function atualizarModoDevolucao() {
    const modo = el("modo-devolucao").value;
    const camposArmario = el("campos-devolucao-armario");
    const camposProntuario = el("campos-devolucao-prontuario");
    camposArmario.classList.toggle("oculto", modo !== "armario");
    camposProntuario.classList.toggle("oculto", modo !== "prontuario");
}

function atualizarTipoConsulta() {
    const tipo = el("tipo-consulta").value;
    const seletor = el("tipo-consulta-armario");
    const campo = el("valor-consulta");
    seletor.disabled = tipo !== "numero";
    seletor.style.opacity = tipo === "numero" ? "1" : "0.65";
    campo.type = tipo === "numero" ? "number" : "text";
    campo.min = tipo === "numero" ? "1" : "";
    campo.placeholder = tipo === "numero"
        ? "Digite o numero do armario"
        : "Digite o prontuario";
    aplicarLimitesCampos();
    agendarConsultaAutomatica();
}

function limparResultadoConsulta(mensagem = "Digite um numero de armario ou um prontuario para consultar.") {
    resultadoConsultaAtual = null;
    el("resultado-consulta").innerHTML = `<div class="consulta-card"><p>${mensagem}</p></div>`;
}

function podeConsultarAutomaticamente() {
    const tipo = el("tipo-consulta").value;
    const valor = el("valor-consulta").value.trim();
    if (!valor) return false;
    if (tipo === "numero") return /^\d+$/.test(valor);
    return valor.length >= 4;
}

function agendarConsultaAutomatica() {
    clearTimeout(debounceConsulta);
    if (!podeConsultarAutomaticamente()) {
        if (!el("valor-consulta").value.trim()) limparResultadoConsulta();
        return;
    }
    debounceConsulta = setTimeout(() => consultar(true), 320);
}

function renderizarResultadoConsulta(item) {
    const participantes = item.participantes || [];
    return `
        <div class="consulta-card">
            <p><strong>Armario:</strong> ${obterIdentificacao(item)}</p>
            <p><strong>Tipo:</strong> ${rotuloTipo(item.tipo)}</p>
            <p><strong>Localizacao:</strong> ${obterLocalizacao(item.tipo, item.localizacao)}</p>
            <p><strong>Tamanho:</strong> ${rotuloTamanho(item.tamanho)}</p>
            <p><strong>Status:</strong> ${rotuloStatusArmario(item.status)}</p>
            ${item.status === "ocupado" ? `
                <p><strong>Participantes:</strong> ${participantes.length || 1}/${item.capacidade || 1}</p>
                <div class="agenda-blocos">
                    ${participantes.map((participante, indice) => renderizarParticipanteColuna(participante, indice + 1)).join("")}
                </div>
                <p><strong>Retirada:</strong> ${item.data_retirada || "-"}</p>
                <p><strong>Prazo:</strong> ${item.data_prevista || "-"}</p>
                <div class="consulta-card__acoes">
                    <button type="button" onclick="abrirEdicaoDaConsulta()">Editar este emprestimo</button>
                    ${renderizarBotaoCobranca(item, "Cobrar responsaveis")}
                </div>
            ` : ""}
        </div>
    `;
}

function aplicarLimitesCampos() {
    const pares = [
        ["tipo-armario", "num"],
        ["tipo-dev", "num_dev"],
        ["tipo-edicao", "num-edicao"],
        ["tipo-consulta-armario", "valor-consulta"]
    ];
    pares.forEach(([tipoId, numeroId]) => {
        const campo = el(numeroId);
        if (!campo) return;
        if (campo.type !== "number" && numeroId !== "valor-consulta") return;
        if (numeroId === "valor-consulta" && el("tipo-consulta").value !== "numero") return;
        campo.min = "1";
        campo.max = String(limiteNumero(el(tipoId).value));
    });
}

async function consultar(silencioso = false) {
    if (!silencioso) setBotoesDesabilitados(["botao-consultar"], true, "Buscando...");
    resultadoConsultaAtual = null;
    try {
        const valor = el("valor-consulta").value.trim();
        if (!valor) {
            limparResultadoConsulta();
            if (!silencioso) exibirMensagem("Informe um valor para consultar.", "erro", true);
            return;
        }

        const params = new URLSearchParams({
            tipo: el("tipo-consulta").value,
            valor,
            tipo_armario: el("tipo-consulta-armario").value
        });
        const data = await buscarJson(`/consultar?${params.toString()}`);
        if (!data.resultado) {
            resultadoConsultaAtual = null;
            el("resultado-consulta").innerHTML = '<div class="consulta-card"><p>Nenhuma ocupacao ativa encontrada para este criterio.</p></div>';
            if (!silencioso) exibirMensagem(data.mensagem || "Consulta concluida.");
            return;
        }
        const item = data.resultado;
        resultadoConsultaAtual = item;
        el("resultado-consulta").innerHTML = renderizarResultadoConsulta(item);
        if (!silencioso) exibirMensagem("Consulta concluida.");
    } catch (erro) {
        resultadoConsultaAtual = null;
        if (!silencioso) exibirMensagem(erro.message, "erro", true);
    } finally {
        if (!silencioso) setBotoesDesabilitados(["botao-consultar"], false, "Buscando...");
    }
}

function montarBlocosPorTipo(lista, vazio) {
    if (!lista.length) return `<div class="estado-vazio">${vazio}</div>`;
    return `
        <div class="lista-bloco">
            <h4>${rotuloTipo("convencional")}</h4>
            ${lista.map((item) => `
                <p>${obterIdentificacao(item)} | ${obterLocalizacao(item.tipo, item.localizacao)} | Tamanho: ${rotuloTamanho(item.tamanho)}</p>
            `).join("")}
        </div>
    `;
}

function renderizarArmariosLivres(lista) {
    if (!lista.length) {
        return '<div class="estado-vazio">Nenhum armario livre no momento.</div>';
    }

    const porLocalizacao = lista.reduce((acc, item) => {
        const chave = obterLocalizacao(item.tipo, item.localizacao);
        acc[chave] = acc[chave] || [];
        acc[chave].push(item);
        return acc;
    }, {});

    const gruposHtml = Object.entries(porLocalizacao).map(([localizacao, itens]) => `
        <article class="livres-bloco">
            <div class="livres-bloco__cabecalho">
                <div>
                    <h4>${rotuloTipo("convencional")}</h4>
                    <p>${localizacao}</p>
                </div>
                <span class="mini-tag">${itens.length} livre(s)</span>
            </div>
            <div class="livres-grid">
                ${itens.map((item) => `
                    <div class="livre-chip">
                        <strong>${item.codigo || obterIdentificacao(item)}</strong>
                        <span>Numero ${item.numero}</span>
                        ${item.tamanho === "grande" ? '<span class="livre-chip__tag">Grande</span>' : ""}
                    </div>
                `).join("")}
            </div>
        </article>
    `).join("");

    return `
        <div class="livres-painel">
            <div class="livres-resumo">
                <div class="livres-resumo-card">
                    <span>Total disponivel</span>
                    <strong>${lista.length}</strong>
                </div>
                <div class="livres-resumo-card">
                    <span>Armarios</span>
                    <strong>${lista.length}</strong>
                </div>
            </div>
            <div class="livres-grupos">${gruposHtml}</div>
        </div>
    `;
}

function emailsResponsaveis(item) {
    const emails = (item.participantes || [])
        .map((participante) => String(participante.email || "").trim())
        .filter(Boolean);
    return [...new Set(emails)];
}

function renderizarCardAtrasado(item) {
    const emails = emailsResponsaveis(item);
    return `
        <article class="atraso-card ${classificarFaixaAtraso(item)}">
            <div class="atraso-card__topo">
                <div>
                    <strong>${escaparHtml(obterIdentificacao(item))}</strong>
                    <span>${escaparHtml(descricaoFaixaAtraso(item))}</span>
                </div>
                <span class="mini-tag">${escaparHtml(item.data_prevista || "-")}</span>
            </div>
            <div class="atraso-card__meta">
                <span>${escaparHtml((item.participantes || []).map((participante) => participante.nome).filter(Boolean).join(", ") || item.nome || "-")}</span>
                <span>${escaparHtml(obterLocalizacao(item.tipo, item.localizacao))}</span>
            </div>
            <div class="atraso-card__emails">
                ${emails.length
                    ? emails.map((email) => `<span class="mini-tag">${escaparHtml(email)}</span>`).join("")
                    : '<span class="mini-tag">Sem email cadastrado</span>'}
            </div>
            <div class="consulta-card__acoes">
                ${renderizarBotaoCobranca(item)}
            </div>
        </article>
    `;
}

function renderizarListaAtrasados(lista) {
    if (!lista.length) {
        return '<div class="estado-vazio">Tudo em dia.</div>';
    }

    const grupos = {
        "Atraso recente": lista.filter((item) => classificarFaixaAtraso(item) === "atraso-recente"),
        "1 a 3 dias": lista.filter((item) => classificarFaixaAtraso(item) === "atraso-moderado"),
        "4 dias ou mais": lista.filter((item) => classificarFaixaAtraso(item) === "atraso-critico"),
    };

    return Object.entries(grupos)
        .filter(([, itens]) => itens.length)
        .map(([titulo, itens]) => `
            <div class="lista-bloco atraso-faixa">
                <div class="card-cabecalho">
                    <div>
                        <h4>${titulo}</h4>
                        <p>${itens.length} armario(s) nesta faixa de urgencia.</p>
                    </div>
                    <span class="mini-tag">${itens.length} item(ns)</span>
                </div>
                <div class="atraso-faixa__lista">
                    ${itens.map((item) => renderizarCardAtrasado(item)).join("")}
                </div>
            </div>
        `)
        .join("");
}

async function cobrarAtrasado(tipo, numero) {
    if (!smtpConfigurado) {
        exibirMensagem("Configure o SMTP na area de Configuracoes antes de enviar cobrancas.", "erro", true);
        return;
    }

    if (!window.confirm(`Enviar cobranca automatica para os responsaveis do ${rotuloTipo(tipo)} ${numero}?`)) {
        return;
    }

    try {
        const data = await buscarJson("/cobrar-email", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                tipo_armario: tipo,
                numero,
                assunto: configuracoesSistema.email_assunto,
                mensagem: configuracoesSistema.email_corpo
            })
        });
        exibirMensagem(data.mensagem || "Cobranca enviada com sucesso.", "sucesso", true);
        mostrarResumoOperacao("Cobranca automatica enviada", [
            `${rotuloTipo(tipo)} ${numero}`,
            "Emails disparados para os responsaveis cadastrados",
        ]);
    } catch (erro) {
        if ((erro.message || "").includes("Rota nao encontrada")) {
            exibirMensagem(
                "A rota de cobranca nao esta ativa neste servidor. Reinicie o app.py para carregar o envio real de email.",
                "erro",
                true
            );
            return;
        }
        exibirMensagem(erro.message, "erro", true);
    }
}

async function listarLivres(silencioso = false) {
    try {
        const tipo = el("livres-tipo").value.trim();
        const sufixo = tipo ? `?tipo_armario=${encodeURIComponent(tipo)}` : "";
        const data = await buscarJson(`/armarios/livres${sufixo}`);
        el("lista-livres").innerHTML = renderizarArmariosLivres(data.armarios);
        if (!silencioso) exibirMensagem("Lista de armarios livres atualizada.");
    } catch (erro) {
        exibirMensagem(erro.message, "erro", true);
    }
}

async function listarAtrasados(silencioso = false) {
    try {
        const data = await buscarJson("/atrasados");
        el("lista-atrasados").innerHTML = renderizarListaAtrasados(data.atrasados || []);
        if (!silencioso) exibirMensagem("Lista de atrasados atualizada.");
    } catch (erro) {
        exibirMensagem(erro.message, "erro", true);
    }
}

function alternarFiltrosHistorico() {
    const painel = el("historico-filtros-wrap");
    const mostrar = painel.classList.contains("oculto");
    painel.classList.toggle("oculto", !mostrar);
    el("botao-filtros-historico").textContent = mostrar ? "Ocultar filtros" : "Mostrar filtros";
}

async function carregarHistorico(silencioso = false) {
    try {
        const params = obterParametrosHistorico();
        const sufixo = params.toString() ? `?${params.toString()}` : "";
        const data = await buscarJson(`/historico${sufixo}`);
        historicoPagina = data.paginacao?.pagina || 1;
        historicoPorPagina = data.paginacao?.por_pagina || historicoPorPagina;
        historicoOrdenacao = data.ordenacao?.campo || historicoOrdenacao;
        historicoDirecao = data.ordenacao?.direcao || historicoDirecao;
        el("hist-por-pagina").value = String(historicoPorPagina);
        el("historico-resumo-paginacao").textContent =
            `${data.paginacao.total_itens} registro(s) | pagina ${data.paginacao.pagina} de ${data.paginacao.total_paginas}`;
        el("historico-resumo-status").textContent =
            `${data.resumo?.ativos || 0} ativos | ${data.resumo?.devolvidos || 0} devolvidos | ${data.resumo?.atrasados || 0} atrasados`;
        el("historico-resumo-ordenacao").textContent =
            `Ordenado por ${descricaoOrdenacaoHistorico(historicoOrdenacao)} (${historicoDirecao === "asc" ? "crescente" : "decrescente"})`;

        el("historico").innerHTML = data.historico.length ? `
            <div class="tabela-wrap">
                <table class="tabela">
                    <thead>
                        <tr>
                            <th><button type="button" class="ordenacao-th" onclick="ordenarHistoricoPor('armario')">Armario <span class="ordenacao-th__icone">${iconeOrdenacaoHistorico("armario")}</span></button></th>
                            <th><button type="button" class="ordenacao-th" onclick="ordenarHistoricoPor('tipo')">Tipo <span class="ordenacao-th__icone">${iconeOrdenacaoHistorico("tipo")}</span></button></th>
                            <th><button type="button" class="ordenacao-th" onclick="ordenarHistoricoPor('localizacao')">Localizacao <span class="ordenacao-th__icone">${iconeOrdenacaoHistorico("localizacao")}</span></button></th>
                            <th><button type="button" class="ordenacao-th" onclick="ordenarHistoricoPor('tamanho')">Tamanho <span class="ordenacao-th__icone">${iconeOrdenacaoHistorico("tamanho")}</span></button></th>
                            <th><button type="button" class="ordenacao-th" onclick="ordenarHistoricoPor('participante_1')">Participante 1 <span class="ordenacao-th__icone">${iconeOrdenacaoHistorico("participante_1")}</span></button></th>
                            <th><button type="button" class="ordenacao-th" onclick="ordenarHistoricoPor('participante_2')">Participante 2 <span class="ordenacao-th__icone">${iconeOrdenacaoHistorico("participante_2")}</span></button></th>
                            <th><button type="button" class="ordenacao-th" onclick="ordenarHistoricoPor('participante_3')">Participante 3 <span class="ordenacao-th__icone">${iconeOrdenacaoHistorico("participante_3")}</span></button></th>
                            <th><button type="button" class="ordenacao-th" onclick="ordenarHistoricoPor('retirada')">Retirada <span class="ordenacao-th__icone">${iconeOrdenacaoHistorico("retirada")}</span></button></th>
                            <th><button type="button" class="ordenacao-th" onclick="ordenarHistoricoPor('prevista')">Prevista <span class="ordenacao-th__icone">${iconeOrdenacaoHistorico("prevista")}</span></button></th>
                            <th><button type="button" class="ordenacao-th" onclick="ordenarHistoricoPor('devolucao')">Devolucao <span class="ordenacao-th__icone">${iconeOrdenacaoHistorico("devolucao")}</span></button></th>
                            <th>Funcionario do emprestimo</th>
                            <th>Funcionario da devolucao</th>
                            <th><button type="button" class="ordenacao-th" onclick="ordenarHistoricoPor('status')">Status <span class="ordenacao-th__icone">${iconeOrdenacaoHistorico("status")}</span></button></th>
                        </tr>
                    </thead>
                    <tbody>
                        ${data.historico.map((item) => {
                            const participantes = item.participantes || [];
                            return `
                                <tr class="${item.status}">
                                    <td>${escaparHtml(item.identificacao)}</td>
                                    <td>${escaparHtml(item.tipo_rotulo)}</td>
                                    <td>${escaparHtml(item.localizacao)}</td>
                                    <td>${escaparHtml(rotuloTamanho(item.tamanho))}</td>
                                    <td class="participante-celula">${renderizarParticipanteColuna(participantes[0], 1)}</td>
                                    <td class="participante-celula">${renderizarParticipanteColuna(participantes[1], 2)}</td>
                                    <td class="participante-celula">${renderizarParticipanteColuna(participantes[2], 3)}</td>
                                    <td>${escaparHtml(item.data_retirada)}</td>
                                    <td>${escaparHtml(item.data_prevista)}</td>
                                    <td>${escaparHtml(item.data_devolucao || "-")}</td>
                                    <td>${escaparHtml(item.funcionario_emprestimo || "Nao informado")}</td>
                                    <td>${escaparHtml(item.funcionario_devolucao || "-")}</td>
                                    <td><span class="status-tag ${item.status}">${escaparHtml(item.status)}</span></td>
                                </tr>
                            `;
                        }).join("")}
                    </tbody>
                </table>
            </div>
        ` : "<p>Nenhum registro encontrado para os filtros informados.</p>";
        el("historico-paginacao").innerHTML = data.paginacao.total_itens > 0 ? `
            <button type="button" class="botao-secundario" onclick="irParaPaginaHistorico(${Math.max(1, data.paginacao.pagina - 1)})" ${data.paginacao.pagina <= 1 ? "disabled" : ""}>Pagina anterior</button>
            <strong>${data.paginacao.pagina} / ${data.paginacao.total_paginas}</strong>
            <button type="button" class="botao-secundario" onclick="irParaPaginaHistorico(${Math.min(data.paginacao.total_paginas, data.paginacao.pagina + 1)})" ${data.paginacao.pagina >= data.paginacao.total_paginas ? "disabled" : ""}>Proxima pagina</button>
        ` : "";
        if (!silencioso) exibirMensagem("Historico atualizado.");
    } catch (erro) {
        exibirMensagem(erro.message, "erro", true);
    }
}

function exportarHistoricoCsv() {
    const params = obterParametrosHistorico();
    const sufixo = params.toString() ? `?${params.toString()}` : "";
    window.open(`${API}/historico/csv${sufixo}`, "_blank");
    exibirMensagem("Exportacao CSV iniciada.", "sucesso", true);
}

function reiniciarHistorico() {
    historicoPagina = 1;
    carregarHistorico();
}

function obterOpcoesImpressaoSelecionadas() {
    return Array.from(document.querySelectorAll('input[name="opcao-impressao"]:checked'))
        .map((item) => item.value);
}

function alternarPainelImpressao(forcarVisivel) {
    const painel = el("painel-impressao");
    const mostrar = typeof forcarVisivel === "boolean"
        ? forcarVisivel
        : painel.classList.contains("oculto");
    painel.classList.toggle("oculto", !mostrar);
}

function montarResumoImpressao() {
    return `
        <section class="print-section">
            <h2>Resumo</h2>
            <div class="print-kpis">
                <div class="print-kpi"><span>Livres</span><strong>${el("resumo-livre").textContent}</strong></div>
                <div class="print-kpi"><span>Ocupados</span><strong>${el("resumo-ocupado").textContent}</strong></div>
                <div class="print-kpi"><span>Atrasados</span><strong>${el("resumo-atrasado").textContent}</strong></div>
                <div class="print-kpi"><span>Armarios</span><strong>${el("resumo-convencional").textContent}</strong></div>
                <div class="print-kpi"><span>Grandes</span><strong>${el("resumo-grande").textContent}</strong></div>
                <div class="print-kpi"><span>Vence hoje</span><strong>${el("resumo-vence-hoje").textContent}</strong></div>
                <div class="print-kpi"><span>Vence amanha</span><strong>${el("resumo-vence-amanha").textContent}</strong></div>
                <div class="print-kpi"><span>Prox. 7 dias</span><strong>${el("resumo-proximos-sete").textContent}</strong></div>
                <div class="print-kpi"><span>Ocupacao</span><strong>${el("resumo-ocupacao").textContent}</strong></div>
            </div>
        </section>
    `;
}

function montarBlocoImpressao(titulo, conteudoHtml, observacao = "") {
    return `
        <section class="print-section">
            <h2>${titulo}</h2>
            ${observacao ? `<p class="print-note">${observacao}</p>` : ""}
            ${conteudoHtml || '<div class="estado-vazio">Nenhum dado disponivel para impressao.</div>'}
        </section>
    `;
}

function resumoFiltrosHistorico() {
    const filtros = [
        el("hist-nome").value.trim() ? `Nome: ${el("hist-nome").value.trim()}` : "",
        el("hist-prontuario").value.trim() ? `Prontuario: ${el("hist-prontuario").value.trim()}` : "",
        el("hist-tipo").value ? `Tipo: ${el("hist-tipo").selectedOptions[0].textContent}` : "",
        el("hist-status").value ? `Status: ${el("hist-status").selectedOptions[0].textContent}` : "",
        el("hist-data-inicio").value ? `Inicio: ${formatarDataParaBR(el("hist-data-inicio").value)}` : "",
        el("hist-data-fim").value ? `Fim: ${formatarDataParaBR(el("hist-data-fim").value)}` : ""
    ].filter(Boolean);
    return filtros.length ? filtros.join(" | ") : "Sem filtros adicionais.";
}

function imprimirHistorico() {
    const opcoes = obterOpcoesImpressaoSelecionadas();
    if (!opcoes.length) {
        exibirMensagem("Selecione pelo menos uma opcao para imprimir.", "erro", true);
        return;
    }

    const secoes = opcoes.map((opcao) => {
        if (opcao === "historico") {
            return montarBlocoImpressao(
                "Historico de emprestimos",
                el("historico").innerHTML,
                resumoFiltrosHistorico()
            );
        }
        if (opcao === "resumo") {
            return montarResumoImpressao();
        }
        if (opcao === "livres") {
            return montarBlocoImpressao("Armarios livres", el("lista-livres").innerHTML);
        }
        if (opcao === "atrasados") {
            return montarBlocoImpressao("Atrasados", el("lista-atrasados").innerHTML);
        }
        return "";
    }).join("");

    const janela = window.open("", "_blank", "width=1100,height=800");
    if (!janela) {
        exibirMensagem("Nao foi possivel abrir a janela de impressao.", "erro", true);
        return;
    }

    const agora = new Date().toLocaleString("pt-BR");
    janela.document.open();
    janela.document.write(`
        <!DOCTYPE html>
        <html lang="pt-BR">
        <head>
            <meta charset="UTF-8">
            <title>Relatorio de Armarios</title>
            <style>
                body {
                    margin: 0;
                    padding: 32px;
                    font-family: "Trebuchet MS", "Segoe UI", sans-serif;
                    color: #1f2f3c;
                    background: #fff;
                }
                h1, h2 { margin: 0; color: #17324d; }
                h1 { font-size: 28px; }
                h2 { font-size: 20px; margin-bottom: 14px; }
                .print-header { margin-bottom: 24px; }
                .print-header p { margin: 8px 0 0; color: #5b6b79; }
                .print-section { margin-top: 28px; }
                .print-note { margin: 0 0 12px; color: #6c7c88; font-size: 13px; }
                .print-kpis {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
                    gap: 12px;
                }
                .print-kpi, .lista-bloco, .livres-bloco, .estado-vazio {
                    padding: 14px;
                    border-radius: 16px;
                    border: 1px solid #ddd2c4;
                    background: #faf6f0;
                }
                .print-kpi span { display: block; color: #6c7c88; font-size: 12px; }
                .print-kpi strong { display: block; margin-top: 4px; font-size: 24px; color: #17324d; }
                .livres-painel, .livres-grupos, .lista-texto { display: grid; gap: 12px; }
                .livres-resumo {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
                    gap: 10px;
                    margin-bottom: 12px;
                }
                .livres-resumo-card, .livre-chip {
                    padding: 12px;
                    border-radius: 14px;
                    border: 1px solid #d9e8d9;
                    background: #f4fbf4;
                }
                .livres-resumo-card span, .livre-chip span, .grupo-titulo span { color: #6c7c88; font-size: 12px; }
                .livres-resumo-card strong, .livre-chip strong { color: #17324d; }
                .livres-grid {
                    display: grid;
                    grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
                    gap: 8px;
                }
                .mini-tag, .status-tag {
                    display: inline-block;
                    padding: 5px 9px;
                    border-radius: 999px;
                    background: #eef4ff;
                    color: #17324d;
                    font-size: 11px;
                    font-weight: bold;
                }
                .tabela {
                    width: 100%;
                    border-collapse: collapse;
                    font-size: 13px;
                }
                .tabela th, .tabela td {
                    border: 1px solid #ddd2c4;
                    padding: 10px 8px;
                    text-align: left;
                    vertical-align: top;
                }
                .tabela thead th {
                    background: #f6eee6;
                }
                .ordenacao-th {
                    display: inline-flex;
                    align-items: center;
                    gap: 6px;
                    padding: 0;
                    border: none;
                    background: transparent;
                    color: inherit;
                    box-shadow: none;
                    font-size: 13px;
                }
                .ordenacao-th__icone {
                    font-size: 11px;
                    opacity: 0.7;
                }
                .participante-coluna {
                    display: grid;
                    gap: 4px;
                    min-width: 180px;
                    padding: 8px 10px;
                    border-radius: 12px;
                    border: 1px solid #ddd2c4;
                    background: #faf6f0;
                }
                .participante-coluna__rotulo {
                    color: #6c7c88;
                    font-size: 11px;
                    font-weight: bold;
                    letter-spacing: 0.04em;
                    text-transform: uppercase;
                }
                .participante-coluna strong {
                    color: #17324d;
                    font-size: 13px;
                }
                .participante-coluna small {
                    color: #6c7c88;
                    font-size: 11px;
                }
                .participante-coluna--vazia {
                    border-style: dashed;
                    background: #fffdf9;
                }
                @media print {
                    body { padding: 18px; }
                }
            </style>
        </head>
        <body>
            <div class="print-header">
                <h1>Relatorio de Armarios</h1>
                <p>Gerado em ${agora}</p>
            </div>
            ${secoes}
        </body>
        </html>
    `);
    janela.document.close();
    janela.focus();
    setTimeout(() => {
        janela.print();
        janela.close();
    }, 200);
    alternarPainelImpressao(false);
    exibirMensagem("Janela de impressao preparada.", "sucesso", true);
}

function agendarHistoricoAutomatico() {
    clearTimeout(debounceHistorico);
    historicoPagina = 1;
    debounceHistorico = setTimeout(() => carregarHistorico(true), 450);
}

async function atualizarTudo(silencioso = false) {
    try {
        await carregarResumo();
        await atualizarListaSeVisivel();
        await listarLivres(true);
        await listarAtrasados(true);
        await carregarHistorico(true);
        if (!silencioso) exibirMensagem("Painel atualizado.", "sucesso", true);
    } catch (erro) {
        exibirMensagem(erro.message || "Nao foi possivel atualizar o painel.", "erro", true);
    }
}

["hist-nome", "hist-prontuario"].forEach((id) => {
    el(id).addEventListener("input", agendarHistoricoAutomatico);
});

["hist-tipo", "hist-status", "hist-data-inicio", "hist-data-fim"].forEach((id) => {
    el(id).addEventListener("change", () => {
        historicoPagina = 1;
        carregarHistorico(true);
    });
});

["tipo-armario", "tipo-dev", "tipo-edicao", "tipo-consulta-armario"].forEach((id) => {
    el(id).addEventListener("change", aplicarLimitesCampos);
});

document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && armarioModalAtual) {
        fecharModalArmario();
    }
});

el("hist-por-pagina").addEventListener("change", () => {
    historicoPorPagina = Number(el("hist-por-pagina").value || 10);
    historicoPagina = 1;
    carregarHistorico(true);
});

el("tipo-armario").addEventListener("change", renderizarParticipantesEmprestimo);
el("num").addEventListener("input", () => {
    aplicarLimitesCampos();
    renderizarParticipantesEmprestimo();
});
el("valor-consulta").addEventListener("input", agendarConsultaAutomatica);
el("tipo-consulta-armario").addEventListener("change", agendarConsultaAutomatica);
el("modo-devolucao").addEventListener("change", atualizarModoDevolucao);

el("data_prev").value = formatarDataDeInputHoje();
participantesEmprestimo = [criarParticipanteVazio()];
renderizarParticipantesEmprestimo();
limparEdicaoEmprestimo();
limparResultadoConsulta();
atualizarModoDevolucao();
atualizarTipoConsulta();
aplicarLimitesCampos();
try {
    aplicarTemaSeguro(localStorage.getItem("tema_armarios") || "claro");
} catch (erro) {
    aplicarTemaSeguro("claro");
}
aplicarLinksPagina();
aplicarPaginaAtual();
(async () => {
    await carregarSessao();
    await carregarConfiguracoes();
    await carregarFuncionarios();
    await carregarAuditoria();
    await atualizarTudo(true);
    aplicarEdicaoPendente();
})();
