"""Contrato estatico da linha do dataset que circula pelo dashboard.

O que este modulo e
-------------------
Uma descricao do que `dados._converter` ja produz hoje. **Nao muda nada em
tempo de execucao**: `LinhaDataset` e um `TypedDict`, entao o objeto continua
sendo um `dict` comum — mesma indexacao, mesma igualdade, mesma serializacao,
mesmo custo. O tipo existe para que a forma da linha esteja escrita em um
lugar so, em vez de ter que ser reconstruida lendo quatro modulos.

Por que ele cabe aqui e nao na raiz
-----------------------------------
A imagem do painel copia apenas `dashboard/` e o compose monta apenas
`./dashboard` — modulos da raiz do projeto sao comprovadamente inalcancaveis
la dentro. Qualquer contrato compartilhado do dashboard mora dentro do proprio
pacote, e este modulo depende exclusivamente da biblioteca padrao para ficar
na camada mais baixa do grafo de imports.

O contrato e fechado, e isso e a informacao principal
-----------------------------------------------------
As 24 chaves estao **sempre presentes**. Nenhuma e opcional, nenhuma e
adicionada depois e nenhuma e removida: `dados._converter` monta a linha
inteira de uma vez, e nenhum consumidor em producao escreve nela. Por isso o
`TypedDict` e total, sem `NotRequired` — usar `total=False` sugeriria uma
variabilidade que o codigo nao tem.

Ausente e presente-com-None sao coisas diferentes
-------------------------------------------------
A distincao importa e esta preservada:

- as dez metricas **nunca** sao `None`. Celula vazia vira `Decimal(0)`, porque
  na superficie de exposicao ausencia de valor e zero medido;
- os quatro campos de Resultado do Meta **sempre existem como chave** e
  carregam `None` quando a superficie nao os traz (contrato v2) ou quando a
  fonte legitimamente nao declarou Resultado. `result_count` em `None` nao e
  zero — a distincao entre ausencia total e quantidade zero declarada e o que
  sustenta a semantica de FORMA A no agregado.

Precisao
--------
Metricas sao `Decimal`, nunca `float`. `conversions` e fracionaria no Google e
truncar ja custou ~1% das conversoes no ETL legado. `int` aparece apenas nas
versoes SCD2, que sao contagens de versao, nao medidas.
"""

from datetime import date
from decimal import Decimal
from typing import TypedDict


class LinhaDataset(TypedDict):
    """Uma observacao no grao do fato: 1 anuncio x 1 dia.

    Produzida por `dados._converter` e consumida somente para leitura por
    `filtros`, `metricas` e `graficos`. Os tipos abaixo descrevem o runtime
    atual — nenhum valor foi convertido para que a anotacao ficasse mais
    uniforme.

    Attributes:
        data: Dia de referencia da observacao.
        plataforma: `Meta Ads` ou `Google Ads`. Unico campo textual livre do
            artefato, validado por formato na entrada.
        conta_id: Pseudonimo `Cliente-XXXXXXXX`.
        conta_versao: Versao SCD2 vigente da conta na data.
        campanha_id: Pseudonimo `Campanha-XXXXXXXX`.
        campanha_versao: Versao SCD2 vigente da campanha na data.
        adset_id: Pseudonimo `AdSet-XXXXXXXX`.
        adset_versao: Versao SCD2 vigente do ad set na data.
        anuncio_id: Pseudonimo `Anuncio-XXXXXXXX`.
        anuncio_versao: Versao SCD2 vigente do anuncio na data.
        spend: Investimento.
        impressions: Impressoes.
        link_clicks: Cliques. Definicao diferente por plataforma.
        conversions: Conversoes. Fracionaria no Google.
        conversion_value: Valor de conversao.
        video_views: Visualizacoes de video. Definicao diferente por
            plataforma; sem interpretacao comum quando somada entre elas.
        reach: Alcance. Metrica NAO ADITIVA — exata apenas na observacao
            original. Somar linhas conta a mesma pessoa varias vezes.
        profile_views: Visitas ao perfil. Zerada no Google por ausencia de
            suporte na GAQL, nao por ausencia de desempenho.
        purchases: Compras, na representacao canonica unica.
        purchase_value: Valor das compras.
        result_type: Indicador do Resultado oficial do Meta, ou ``None``
            quando a fonte nao declarou tipo algum.
        result_count: Quantidade do Resultado. ``None`` significa ausencia de
            contrato e **nao** e o mesmo que ``Decimal(0)``, que e quantidade
            zero declarada pela fonte.
        result_attribution_window: Janela de atribuicao. ``None`` legitimo
            quando o indicador nao tem janela aplicavel.
        cost_per_result: Custo por resultado reportado pela fonte. ``None``
            quando nao existe denominador.
    """

    data: date
    plataforma: str

    conta_id: str
    conta_versao: int
    campanha_id: str
    campanha_versao: int
    adset_id: str
    adset_versao: int
    anuncio_id: str
    anuncio_versao: int

    spend: Decimal
    impressions: Decimal
    link_clicks: Decimal
    conversions: Decimal
    conversion_value: Decimal
    video_views: Decimal
    reach: Decimal
    profile_views: Decimal
    purchases: Decimal
    purchase_value: Decimal

    result_type: str | None
    result_count: Decimal | None
    result_attribution_window: str | None
    cost_per_result: Decimal | None
