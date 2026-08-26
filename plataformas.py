"""Registro unico das plataformas de anuncios suportadas pelo pipeline.

Antes deste modulo, "plataforma" estava declarada em seis lugares — chave de
CLI, grupo de credenciais, fonte da bronze, caminho do arquivo bruto, campo de
data e despacho do extrator — que precisavam ser mantidos em sincronia a mao.
O acoplamento mais perigoso era silencioso: o extrator declarava o caminho do
arquivo bruto e o loader declarava o mesmo caminho de novo, sem nenhuma ligacao
entre os dois. Renomear de um lado produzia "arquivo bruto ausente, fonte
ignorada" — um ``warning``, nao um erro — e o pipeline terminava com sucesso
tendo carregado nada.

Agora existe uma entrada por plataforma e todo o resto deriva dela. Acrescentar
uma plataforma nova e acrescentar um item em :data:`PLATAFORMAS`.

Uso:
    from plataformas import PLATAFORMAS, por_fonte

    PLATAFORMAS["meta"].arquivo_bruto
    por_fonte("meta_ads").campo_data
"""

import importlib
from dataclasses import dataclass
from pathlib import Path

BASE_DIR: Path = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Plataforma:
    """Descreve tudo que o pipeline precisa saber sobre uma plataforma.

    Attributes:
        chave: Identificador na CLI (``--platforms``).
        nome: Rotulo humano, usado em log e como grupo de credenciais em
            :func:`config.validate_env`.
        fonte_bronze: Valor da coluna ``source`` em ``bronze.raw_ads``.
        arquivo_bruto: Arquivo JSON que o extrator escreve e o loader le.
            Declarado aqui uma unica vez, o que elimina o acoplamento
            silencioso entre as duas pontas.
        campo_data: Chave do payload que carrega o dia de referencia. As duas
            APIs nomeiam esse campo de formas diferentes.
        modulo_extrator: Caminho do modulo cujo ``run(start_date, end_date)``
            executa a extracao. E uma string, e nao a funcao, para preservar o
            import tardio do SDK (ver :meth:`extrair`).
        variaveis_obrigatorias: Variaveis de ambiente exigidas para extrair
            desta plataforma.
    """

    chave: str
    nome: str
    fonte_bronze: str
    arquivo_bruto: Path
    campo_data: str
    modulo_extrator: str
    variaveis_obrigatorias: tuple[str, ...]

    @property
    def arquivo_manifesto(self) -> Path:
        """Caminho do manifesto que acompanha o arquivo bruto.

        Derivado do `arquivo_bruto` com `with_name`, e nao com `with_suffix`:
        `Path('temp_meta_raw.json').with_suffix('.manifest.json')` produziria
        um nome plausivel aqui, mas e a mesma armadilha que ja gerou
        `.env.env.bak` neste repositorio.

        Returns:
            Caminho do manifesto (ex: ``temp_meta_raw.manifesto.json``).
        """
        return self.arquivo_bruto.with_name(
            f"{self.arquivo_bruto.stem}.manifesto.json"
        )

    def extrair(
        self,
        start_date: str,
        end_date: str,
        run_id: str | None = None,
        **opcoes: bool,
    ) -> int:
        """Executa a extracao desta plataforma no periodo informado.

        O modulo do extrator e importado aqui dentro, e nao no topo do arquivo,
        de proposito: importar o modulo carrega o SDK da plataforma, que e
        pesado. Uma execucao com ``--platforms meta`` nao deve pagar o custo de
        carregar o SDK do Google.

        ``opcoes`` e um canal para desvios especificos de uma plataforma, e nao
        parte do contrato comum: quem chama so passa opcao que o extrator
        daquela plataforma declara. Uma opcao dirigida a plataforma errada
        levanta ``TypeError`` na chamada, em vez de ser ignorada em silencio.

        Args:
            start_date: Data inicial no formato ``YYYY-MM-DD``.
            end_date: Data final no formato ``YYYY-MM-DD``.
            run_id: Identificador da execucao, gravado no manifesto para que o
                loader consiga provar que o arquivo bruto veio dela.
            **opcoes: Desvios especificos desta plataforma, repassados ao
                ``run`` do extrator.

        Returns:
            Quantidade de registros extraidos.
        """
        modulo = importlib.import_module(self.modulo_extrator)
        return modulo.run(start_date, end_date, run_id, **opcoes)


PLATAFORMAS: dict[str, Plataforma] = {
    "meta": Plataforma(
        chave="meta",
        nome="Meta Ads",
        fonte_bronze="meta_ads",
        arquivo_bruto=BASE_DIR / "temp_meta_raw.json",
        campo_data="date_start",
        modulo_extrator="extractors.meta_ads",
        variaveis_obrigatorias=(
            "META_APP_ID",
            "META_APP_SECRET",
            "META_ACCESS_TOKEN",
            "META_BUSINESS_ID",
        ),
    ),
    "google": Plataforma(
        chave="google",
        nome="Google Ads",
        fonte_bronze="google_ads",
        arquivo_bruto=BASE_DIR / "temp_google_raw.json",
        campo_data="date",
        modulo_extrator="extractors.google_ads",
        variaveis_obrigatorias=(
            "GOOGLE_DEVELOPER_TOKEN",
            "GOOGLE_CLIENT_ID",
            "GOOGLE_CLIENT_SECRET",
            "GOOGLE_REFRESH_TOKEN",
            "GOOGLE_LOGIN_CUSTOMER_ID",
        ),
    ),
}

# Indice auxiliar: a bronze identifica a plataforma pela fonte, nao pela chave
# de CLI. Derivado do registro, nunca escrito a mao.
_POR_FONTE: dict[str, Plataforma] = {p.fonte_bronze: p for p in PLATAFORMAS.values()}


def chaves() -> list[str]:
    """Retorna as chaves de CLI aceitas em ``--platforms``.

    Returns:
        Lista de chaves na ordem de declaracao do registro.
    """
    return list(PLATAFORMAS)


def fontes() -> list[str]:
    """Retorna os identificadores de fonte usados na camada bronze.

    Returns:
        Lista de fontes na ordem de declaracao do registro.
    """
    return list(_POR_FONTE)


def por_chave(chave: str) -> Plataforma:
    """Recupera uma plataforma pela chave de CLI.

    Args:
        chave: Chave declarada no registro (ex: ``"meta"``).

    Returns:
        A plataforma correspondente.

    Raises:
        KeyError: Se a chave nao existir no registro.
    """
    if chave not in PLATAFORMAS:
        raise KeyError(
            f"Plataforma desconhecida: '{chave}'. "
            f"Valores aceitos: {', '.join(chaves())}."
        )
    return PLATAFORMAS[chave]


def por_fonte(fonte: str) -> Plataforma:
    """Recupera uma plataforma pelo identificador de fonte da bronze.

    Args:
        fonte: Valor da coluna ``source`` (ex: ``"meta_ads"``).

    Returns:
        A plataforma correspondente.

    Raises:
        KeyError: Se a fonte nao existir no registro.
    """
    if fonte not in _POR_FONTE:
        raise KeyError(
            f"Fonte desconhecida: '{fonte}'. "
            f"Valores aceitos: {', '.join(fontes())}."
        )
    return _POR_FONTE[fonte]
