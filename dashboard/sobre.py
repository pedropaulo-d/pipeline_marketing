"""Pagina "Sobre os dados" do painel.

Por que ela sai de `app.py`
---------------------------
As outras paginas respondem perguntas sobre o desempenho da midia. Esta
responde perguntas sobre o **artefato**: de onde ele veio, o que ele cobre, o
que a camada garante e o que ela deliberadamente nao mostra. E documentacao
renderizada, nao analise — nao le filtro, nao escolhe metrica, nao ordena nada.

Ela e a unica pagina que nao usa `session_state` **nem** widget com `key`, e a
unica cujo conteudo nao muda com a metrica selecionada. Por isso e a que sai do
orquestrador sem arrastar a maquinaria de cartoes, blocos e seletores que as
demais compartilham.

Dependencias
------------
Somente modulos do proprio pacote (`dados`, `metricas`, `formatacao`,
`componentes`) e Streamlit. **Nao importa `app`** — a dependencia e de mao
unica: o orquestrador conhece a pagina, a pagina nao conhece o orquestrador.
"""

import streamlit as st

from dashboard import componentes as ui
from dashboard import dados
from dashboard import metricas as m
from dashboard.formatacao import formatar_periodo


TEXTO_FRONTEIRA: str = (
    "Este dashboard consome exclusivamente a superfície de exposição do "
    "pipeline. Identificadores reais de clientes, contas, campanhas e "
    "anúncios não são disponibilizados nesta camada."
)


def pagina_sobre(dataset, linhas: list[dict]) -> None:
    """Desenha a pagina "Sobre os dados".

    Args:
        dataset: Dataset carregado.
        linhas: Linhas ja filtradas (usadas apenas para o recorte atual).
    """
    resumo = dados.resumo(dataset)
    manifesto = dataset.manifesto

    periodo = (
        formatar_periodo(resumo["data_min"], resumo["data_max"])
        if resumo["data_min"] else m.INDISPONIVEL
    )

    ui.secao("Dataset carregado", dataset.fonte.caminho_relativo)
    ui.linha_kpis([
        {"rotulo": "Período", "valor": periodo,
         "tooltip": f"{resumo['dias']} dias com dado"},
        {"rotulo": "Plataformas",
         "valor": str(len(resumo["plataformas"])),
         "tag": ", ".join(resumo["plataformas"])},
        {"rotulo": "Linhas", "valor": m.formatar(resumo["linhas"], m.INTEIRO),
         "tag": "grão: anúncio × dia"},
    ], compacto=True, chave="grade_resumo")
    ui.linha_kpis([
        {"rotulo": "Contas", "valor": m.formatar(resumo["contas"], m.INTEIRO)},
        {"rotulo": "Campanhas",
         "valor": m.formatar(resumo["campanhas"], m.INTEIRO)},
        {"rotulo": "Ad sets",
         "valor": m.formatar(resumo["adsets"], m.INTEIRO)},
        {"rotulo": "Anúncios",
         "valor": m.formatar(resumo["anuncios"], m.INTEIRO)},
        {"rotulo": "No recorte atual",
         "valor": m.formatar(len(linhas), m.INTEIRO),
         "tag": "após os filtros"},
    ], compacto=True, chave="grade_resumo_entidades")

    ui.secao("Segurança e privacidade", "")
    st.markdown(
        f"{TEXTO_FRONTEIRA}\n\n"
        "- Os identificadores exibidos (`Cliente-`, `Campanha-`, `AdSet-`, "
        "`Anuncio-`) são pseudônimos gerados **fora** desta camada.\n"
        "- Métricas e datas são reais e intactas: a pseudonimização troca "
        "identidade, nunca número.\n"
        "- O painel não acessa o Data Warehouse nem as APIs de anúncios; a "
        "única entrada é um arquivo que satisfaz o contrato de exposição.\n"
        "- Coluna terminada em `_nk`, `_sk`, `_external_id` ou `_nome` faz o "
        "arquivo inteiro ser recusado."
    )

    ui.secao(
        "Métricas por origem",
        '"— Não disponível" = a origem não fornece a métrica neste nível. '
        "Zero nunca é usado como sinônimo de indisponibilidade.",
    )
    ui.tabela([
        {
            "Métrica": definicao.rotulo,
            "Coluna": definicao.chave,
            # Rotulo curto: a coluna e estreita e o texto longo era cortado
            # pela tabela. O significado esta no apoio da secao.
            "Meta Ads": "✓ Disponível"
            if m.suportada(definicao.chave, "Meta Ads")
            else "— Não disponível",
            "Google Ads": "✓ Disponível"
            if m.suportada(definicao.chave, "Google Ads")
            else "— Não disponível",
            "Somável entre plataformas": (
                "✓ Sim" if definicao.comparavel_entre_plataformas else "— Não"
            ),
        }
        for definicao in m.CATALOGO.values()
    ])

    with st.expander("Indicadores derivados e manifesto do artefato"):
        ui.tabela([
            {"Indicador": definicao.rotulo, "Fórmula": definicao.descricao}
            for definicao in m.DERIVADAS.values()
        ])
        if manifesto:
            itens = {
                "Versão do contrato": manifesto.get("versao_contrato"),
                "Gerado em": manifesto.get("gerado_em"),
                "Linhas declaradas": manifesto.get("linhas"),
                "Intervalo declarado": (
                    f"{manifesto.get('data_min')} a {manifesto.get('data_max')}"
                ),
                "sha256 do CSV": manifesto.get("sha256"),
                "Origem declarada": manifesto.get(
                    "origem", manifesto.get("gerador")
                ),
            }
            if manifesto.get("fingerprint_chave"):
                # Impressao digital da chave de pseudonimizacao: nao permite
                # recuperar o segredo e responde se dois artefatos usam a
                # mesma chave — portanto se os pseudonimos sao comparaveis.
                itens["Fingerprint da chave"] = manifesto["fingerprint_chave"]
            if manifesto.get("natureza"):
                itens["Natureza"] = manifesto["natureza"]
            ui.tabela([
                {"Campo": chave, "Valor": str(valor)}
                for chave, valor in itens.items() if valor is not None
            ])

        if dataset.colunas_ignoradas:
            ui.nota(
                "Colunas fora do contrato foram ignoradas de proposito: "
                + ", ".join(dataset.colunas_ignoradas)
                + "."
            )
