import { API } from "./config.js";

async function tratarResposta(resposta) {
    let data = {};
    try {
        data = await resposta.json();
    } catch (erro) {
        throw new Error("Resposta invalida do servidor.");
    }

    if (!resposta.ok || data.ok === false) {
        throw new Error(data.mensagem || "Nao foi possivel concluir a operacao.");
    }

    return data;
}

export async function buscarJson(caminho, opcoes = {}) {
    let resposta;
    try {
        resposta = await fetch(`${API}${caminho}`, opcoes);
    } catch (erro) {
        throw new Error("Nao foi possivel conectar ao servidor.");
    }

    return tratarResposta(resposta);
}

export async function enviarCobrancaEmail({ tipoArmario, numero, prontuario }) {
    return buscarJson("/cobrar-email", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            tipo_armario: String(tipoArmario || "").trim(),
            numero: String(numero || "").trim(),
            prontuario: String(prontuario || "").trim(),
        }),
    });
}
