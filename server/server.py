"""Servidor MCP do Coletum (só leitura), transporte stdio.

Lê a API de leitura do Coletum (Webservice V2) e entrega à IA resumos compactos, contagens e
exportações gravadas em disco. Nunca escreve na API. Veja o README.md do repositório para instalar e conectar.
"""
from __future__ import annotations

import base64
import json
import logging
import math
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, ImageContent, ResourceLink, TextContent, ToolAnnotations
from pydantic import Field

sys.path.insert(0, str(Path(__file__).resolve().parent))
from achatar import Achatador, fuso, slug  # noqa: E402
from api import (guardar_token, INTERVALO_PADRAO_S, MAX_CHAMADAS_HORA_PADRAO, PESO_COTA_V2, ColetumAPI, Contador,  # noqa: E402
                 ErroColetum, config, cota_de, descrever_filtros, montar_filtros, pasta_padrao)
# Todos os módulos do conector carregam na subida: o servidor fica inteiro na versão com que
# subiu. Import tardio misturava versões quando o código mudava com o servidor no ar.
import contrato  # noqa: E402
import fotos_teste  # noqa: E402
import modelos  # noqa: E402
import planilha  # noqa: E402

logging.getLogger("httpx").setLevel(logging.WARNING)

PASTA_SAIDA_PADRAO = pasta_padrao("saidas")
PAGINA_EXPORTACAO = 500
LEITURA_PADRAO, LEITURA_MAX = 20, 100

mcp = FastMCP(
    "coletum",
    instructions=(
        "Lê os dados de formulários do Coletum (só leitura). Cada chamada à API v2 consome "
        f"{str(PESO_COTA_V2).replace('.', ',')} da cota mensal da conta hoje (peso de transição, enquanto a API v1 "
        "existir; pode mudar). Cada página conta; erro não conta. Toda ferramenta informa chamadas_api e cota_consumida "
        "(calculada com o peso atual da v2). O conector espera "
        f"{str(INTERVALO_PADRAO_S).replace('.', ',')} s entre duas chamadas e recusa passar de {MAX_CHAMADAS_HORA_PADRAO} "
        "chamadas por hora. "
        "Fluxo recomendado: listar_formularios, estrutura_formulario, contar_preenchimentos com os "
        "filtros de período, origem ou autor, e só então buscar_preenchimentos (para ler uma página) "
        "ou exportar_preenchimentos (para gravar planilha em disco). PDF de preenchimentos: gerar_pdf_preenchimento; "
        "o PDF padrão é o da exportação do Coletum (modelo coletum_exportacao). Pedidos como \"põe meu logo\", \"tira "
        "o campo X\", \"uma foto por linha\", fonte, cor de destaque ou página deitada vão em ajustes e valem no próprio "
        "padrão do Coletum; \"em colunas\" ou \"compacto\" = modelo coletum_colunas; \"relatório fotográfico\" ou \"só as "
        "fotos\" = modelo coletum_fotografico. Ajuste que nenhum dos três faz é recusado com a lista do que não "
        "existe, sem gerar outro visual. Os ids e criado_em vêm de buscar_preenchimentos (um ou vários). "
        "Para PDF no modelo que o cliente já usa: analisar_pdf_modelo, gerar_pdf_modelo com template Typst, "
        "salvar_modelo e depois só o nome; listar_modelos mostra os salvos. Leia ler_preferencias no começo de "
        "tarefas de documento. Não puxe tudo: filtre e pagine. Os preenchimentos vêm do mais recente para o "
        "mais antigo (data de criação): os N mais recentes são a página 1 com tamanho N (1 chamada); os mais "
        "antigos, contar_preenchimentos e ler a última página. Toda ferramenta que grava arquivo começa a resposta "
        "pelo caminho completo de cada arquivo (o mesmo texto vem em mostrar_ao_usuario). Sempre mostre ao usuário "
        "o caminho completo, como está, em bloco de código, para ele copiar, sem esperar que ele peça; se ele pedir "
        "para abrir, use mostrar_arquivo (abre a pasta do sistema com o arquivo selecionado). Nunca diga só que "
        "gravou na pasta do projeto. Se uma ferramenta disser que falta o token ou que ele foi recusado, peça ao "
        "usuário que cole o token do Webservice V2 na conversa e chame configurar_token; nunca repita o token."
    ),
)

_api: ColetumAPI | None = None
_estruturas: dict[int, dict] = {}


def api() -> ColetumAPI:
    global _api
    if _api is None:
        _api = ColetumAPI()
    return _api


def resolver_pasta(pasta: str | None) -> Path:
    p = Path(pasta or config("COLETUM_PASTA_SAIDA") or PASTA_SAIDA_PADRAO).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p


def estrutura(fid: int, cont: Contador, forcar: bool = False) -> dict:
    """Estrutura do formulário, guardada em memória enquanto o servidor roda (muda pouco)."""
    if forcar or fid not in _estruturas:
        _estruturas[fid] = api().get(f"/forms/{fid}", {}, cont)
    return _estruturas[fid]


def erro(msg: str, cont: Contador) -> dict:
    return {"ok": False, "erro": msg, "chamadas_api": cont.chamadas, "cota_consumida": cont.cota,
            "requisicoes_feitas": cont.requisicoes}


def fim(res: dict, cont: Contador) -> dict:
    res = {"ok": True, **res}
    res["chamadas_api"] = cont.chamadas
    res["cota_consumida"] = cont.cota
    res["requisicoes_feitas"] = cont.requisicoes
    return res


# --------------------------------------------------------------------------------------------
# Links para o usuário abrir o que foi gerado: caminho absoluto, link file:// e resource_link
LINKS_MAX = 20
TIPOS_ARQUIVO = {
    ".pdf": "application/pdf", ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv", ".txt": "text/plain", ".html": "text/html", ".zip": "application/zip",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".json": "application/json",
}
TIPO_PASTA = "inode/directory"
INSTRUCAO_CAMINHO = ("Mostre ao usuário o caminho completo acima, como está, em bloco de código, para ele copiar. "
                     "Se ele pedir para abrir, use mostrar_arquivo.")
AVISO_LINKS = (" Ao terminar, sempre mostre ao usuário o caminho completo de cada arquivo (vem no começo da resposta "
               "e em mostrar_ao_usuario), em bloco de código, para ele copiar; se ele pedir para abrir, use "
               "mostrar_arquivo. Nunca diga só 'na pasta do projeto'.")
_gerados: set[Path] = set()  # o que as ferramentas gravaram nesta execução: mostrar_arquivo só abre isso


def _gera_arquivo(fn):
    """Marca a ferramenta que grava arquivo para o usuário: a descrição ganha o pedido de mostrar o caminho."""
    fn.__doc__ = (fn.__doc__ or "").rstrip() + "\n   " + AVISO_LINKS
    return fn


def _link(caminho) -> dict:
    """Um arquivo ou pasta gerado: nome, caminho absoluto, link file:// (codificado) e tipo."""
    p = Path(caminho).expanduser().resolve()
    uri = p.as_uri()
    d = {"nome": p.name, "caminho": str(p), "link": uri, "markdown": f"[{p.name}]({uri})"}
    if p.is_dir():
        d["tipo"] = TIPO_PASTA
    else:
        d["tipo"] = TIPOS_ARQUIVO.get(p.suffix.lower(), "application/octet-stream")
        if p.is_file():
            d["bytes"] = p.stat().st_size
    return d


def _linhas_caminho(links: list[dict], omitidos: int) -> str:
    """As linhas de caminho do começo da resposta: uma por arquivo ou pasta, prontas para copiar."""
    linhas = [f"{'Pasta gerada' if l['tipo'] == TIPO_PASTA else 'Arquivo gerado'}: {l['caminho']}" for l in links]
    if omitidos:
        linhas.append(f"(mais {omitidos} não listados aqui)")
    return "\n".join(linhas)


def _resposta(dados: dict, arquivos=(), imagens: list[bytes] | None = None) -> CallToolResult:
    """Resposta da ferramenta. Com ok e arquivos, o 1º bloco de texto é curto: o caminho completo de cada arquivo
    (até LINKS_MAX, na ordem dada) e a instrução de mostrá-lo; o JSON (estruturado e em texto) ganha links e
    mostrar_ao_usuario (os caminhos em bloco de código). Depois vêm um resource_link por arquivo e, se houver,
    imagens para a IA ver. Sem arquivos, só o JSON."""
    links: list[dict] = []
    cabeca = None
    if dados.get("ok"):
        vistos: list[str] = []
        for a in arquivos:
            if a and str(a) not in vistos and Path(a).expanduser().exists():
                vistos.append(str(a))
        for a in vistos:
            p = Path(a).expanduser().resolve()
            _gerados.update({p} if p.is_dir() else {p, p.parent})
        links = [_link(a) for a in vistos[:LINKS_MAX]]
        if links:
            omitidos = len(vistos) - LINKS_MAX if len(vistos) > LINKS_MAX else 0
            caminhos = _linhas_caminho(links, omitidos)
            cabeca = f"{caminhos}\n\n{INSTRUCAO_CAMINHO}"
            dados["links"] = links
            dados["mostrar_ao_usuario"] = "```\n" + "\n".join(l["caminho"] for l in links) + "\n```"
            if omitidos:
                dados["links_omitidos"] = omitidos
    conteudo: list = [TextContent(type="text", text=cabeca)] if cabeca else []
    conteudo.append(TextContent(type="text", text=json.dumps(dados, ensure_ascii=False, indent=1)))
    conteudo += [ResourceLink(type="resource_link", uri=l["link"], name=l["nome"], mimeType=l["tipo"],
                              description=f"Caminho: {l['caminho']}", size=l.get("bytes")) for l in links]
    conteudo += [ImageContent(type="image", data=base64.b64encode(b).decode(), mimeType="image/png")
                 for b in imagens or []]
    return CallToolResult(content=conteudo, structuredContent=dados)


def _id_form(id_formulario) -> int:
    try:
        n = int(id_formulario)
        if n > 0:
            return n
    except (TypeError, ValueError):
        pass
    raise ErroColetum(f"id_formulario inválido: '{id_formulario}'. Use o id numérico de listar_formularios.")


# Tipos anotados dos filtros, repetidos nas ferramentas de preenchimentos
IdForm = Annotated[int, Field(description="Id numérico do formulário (vem de listar_formularios).")]
CriadoDepois = Annotated[str | None, Field(description="Só preenchimentos criados depois desta data (exclusivo). AAAA-MM-DD ou data e hora ISO.")]
CriadoAntes = Annotated[str | None, Field(description="Só preenchimentos criados antes desta data (exclusivo). AAAA-MM-DD ou data e hora ISO.")]
EditadoDepois = Annotated[str | None, Field(description="Só preenchimentos editados depois desta data. Atenção: traz apenas os editados, não os novos.")]
EditadoAntes = Annotated[str | None, Field(description="Só preenchimentos editados antes desta data.")]
Origem = Annotated[str | None, Field(description="Origem da criação: mobile (aplicativo), web_private (sistema, logado) ou web_public (link público).")]
CriadoPor = Annotated[int | None, Field(description="Id do usuário que criou (aparece como autor_id em buscar_preenchimentos).")]
EditadoPor = Annotated[int | None, Field(description="Id do usuário que fez a última edição.")]
PastaSaida = Annotated[str | None, Field(description="Pasta onde gravar. Padrão: COLETUM_PASTA_SAIDA ou Documentos/Coletum/saidas.")]


# --------------------------------------------------------------------------------------------
@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True))
def configurar_token(
    token: Annotated[str, Field(description="Token do Webservice V2 que o usuário colou na conversa.")],
) -> dict:
    """Testa o token da API do Coletum (1 chamada) e o guarda no cofre do sistema para as próximas conversas.

    Use só quando uma ferramenta disser que falta o token ou que ele foi recusado. Não repita o token na resposta.
    """
    global _api
    cont = Contador()
    t = (token or "").strip()
    if not t:
        return erro("Token vazio.", cont)
    try:
        novo = ColetumAPI(token=t)
        novo.get("/forms", {"page": 1, "page_size": 1}, cont)
    except ErroColetum as e:
        return erro(f"Token não aceito: {e}", cont)
    onde = guardar_token(t)
    _api = novo
    return fim({"mensagem": f"Token conferido e guardado ({onde}). Pode seguir com o pedido.",
                "guardado_em": onde}, cont)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
def listar_formularios(
    nome: Annotated[str | None, Field(description="Parte do nome do formulário (busca parcial, sem diferenciar maiúsculas).")] = None,
    status: Annotated[Literal["enabled", "disabled"] | None, Field(description="enabled (habilitados) ou disabled (desabilitados). Vazio traz todos.")] = None,
    pagina: Annotated[int, Field(ge=1, description="Página, começando em 1.")] = 1,
    tamanho_pagina: Annotated[int, Field(ge=1, le=500, description="Formulários por página (máximo 500).")] = 100,
) -> dict:
    """Lista os formulários da conta: id, nome, status, categoria e versão.

    Custo: 1 chamada por página, cerca de 200 bytes por formulário. Use tamanho_pagina alto (até 500)
    para ver tudo em 1 chamada. É o ponto de partida: o id daqui entra em todas as outras ferramentas.
    """
    cont = Contador()
    try:
        r = api().get("/forms", {"name": nome, "status": status, "page": pagina, "page_size": tamanho_pagina}, cont)
    except ErroColetum as e:
        return erro(str(e), cont)
    pag = r.get("pagination") or {}
    forms = [{"id": f.get("id"), "nome": f.get("name"), "status": f.get("status"),
              "categoria": f.get("category"), "versao": f.get("version")} for f in r.get("data") or []]
    return fim({"formularios": forms, "pagina": pag.get("page"), "total": pag.get("total_items"),
                "total_paginas": pag.get("total_pages"), "tem_proxima": bool(pag.get("has_next"))}, cont)


# --------------------------------------------------------------------------------------------
def _campos(comps: list, max_opcoes: int) -> list:
    saida = []
    for c in comps:
        minimo, vis = c.get("minimum") or {}, c.get("visibility") or {}
        item = {"chave": c.get("id"), "rotulo": c.get("label"), "tipo": c.get("type"),
                "multiplo": c.get("maximum") != 1}
        if c.get("help_block"):
            item["ajuda"] = c["help_block"]
        if minimo.get("type") == "FIXED":
            item["obrigatorio"] = bool(minimo.get("value"))
        elif minimo:
            item["obrigatorio"] = {"condicional": minimo}
        if vis and vis.get("type") != "FIXED":
            item["visivel_se"] = vis
        elif vis and vis.get("value") is False:
            item["visivel_se"] = "oculto"
        if "options" in c:
            ops = c.get("options") or []
            item["opcoes"] = ops[:max_opcoes]
            if len(ops) > max_opcoes:
                item["opcoes_total"] = len(ops)
        if c.get("type") == "group":
            item["grupo_repetivel"] = c.get("maximum") != 1
            item["campos"] = _campos(c.get("components") or [], max_opcoes)
        saida.append(item)
    return saida


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
def estrutura_formulario(
    id_formulario: IdForm,
    max_opcoes: Annotated[int, Field(ge=0, le=5000, description="Quantas opções mostrar por campo de escolha (há campos com milhares).")] = 30,
    forcar_atualizacao: Annotated[bool, Field(description="Buscar de novo na API mesmo se já estiver guardada nesta sessão.")] = False,
) -> dict:
    """Estrutura de um formulário: campos em ordem, com chave técnica, rótulo, tipo, se é múltiplo,
    se é obrigatório, opções dos campos de escolha, regras de exibição e grupos (repetíveis ou não).

    Use antes de montar planilha ou PDF: dá os rótulos legíveis, a ordem e os blocos.
    Custo: 1 chamada na primeira vez; depois fica guardada em memória e custa 0 enquanto o servidor roda.
    """
    cont = Contador()
    try:
        e = estrutura(_id_form(id_formulario), cont, forcar_atualizacao)
    except ErroColetum as ex:
        return erro(str(ex), cont)
    return fim({"id": e.get("id"), "nome": e.get("name"), "versao": e.get("version"),
                "categoria": e.get("category"), "descricao": e.get("description"),
                "campos": _campos(e.get("components") or [], max_opcoes),
                "guardada_em_memoria": cont.chamadas == 0}, cont)


# --------------------------------------------------------------------------------------------
@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
def contar_preenchimentos(
    id_formulario: IdForm,
    criado_depois_de: CriadoDepois = None, criado_antes_de: CriadoAntes = None,
    editado_depois_de: EditadoDepois = None, editado_antes_de: EditadoAntes = None,
    origem: Origem = None, criado_por: CriadoPor = None, editado_por: EditadoPor = None,
    tamanho_pagina: Annotated[int, Field(ge=1, le=500, description="Tamanho de página para calcular quantas chamadas custaria trazer tudo.")] = LEITURA_PADRAO,
) -> dict:
    """Conta quantos preenchimentos batem com os filtros, sem trazê-los.

    Custo: sempre 1 chamada (pede 1 preenchimento só para ler o total). Use SEMPRE antes de buscar
    ou exportar: devolve o total e quantas chamadas (e quanta cota, com o peso atual da v2) custaria ler tudo na conversa (páginas de
    tamanho_pagina) ou exportar para arquivo (páginas de 500). Filtro inválido é recusado antes de chamar a API.
    """
    cont = Contador()
    try:
        fid = _id_form(id_formulario)
        filtros = montar_filtros(criado_depois_de, criado_antes_de, editado_depois_de, editado_antes_de,
                                 origem, criado_por, editado_por)
        r = api().get(f"/forms/{fid}/answers", {**filtros, "page": 1, "page_size": 1}, cont)
    except ErroColetum as e:
        return erro(str(e), cont)
    total = (r.get("pagination") or {}).get("total_items") or 0
    chamadas_ler = math.ceil(total / tamanho_pagina)
    chamadas_exportar = math.ceil(total / PAGINA_EXPORTACAO)
    return fim({"id_formulario": fid, "filtros": descrever_filtros(filtros), "total": total,
                "tamanho_pagina": tamanho_pagina,
                "chamadas_para_ler_tudo": chamadas_ler,
                "cota_para_ler_tudo": cota_de(chamadas_ler),
                "chamadas_para_exportar_tudo": chamadas_exportar,
                "cota_para_exportar_tudo": cota_de(chamadas_exportar)}, cont)


# --------------------------------------------------------------------------------------------
@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
def buscar_preenchimentos(
    id_formulario: IdForm,
    criado_depois_de: CriadoDepois = None, criado_antes_de: CriadoAntes = None,
    editado_depois_de: EditadoDepois = None, editado_antes_de: EditadoAntes = None,
    origem: Origem = None, criado_por: CriadoPor = None, editado_por: EditadoPor = None,
    pagina: Annotated[int, Field(ge=1, description="Página, começando em 1.")] = 1,
    tamanho_pagina: Annotated[int, Field(ge=1, description=f"Preenchimentos por página. Padrão {LEITURA_PADRAO}, máximo {LEITURA_MAX}.")] = LEITURA_PADRAO,
) -> dict:
    """Traz UMA página de preenchimentos em resumo compacto, para a IA ler.

    Cada preenchimento vem com id, data, autor, origem, coordenada do aparelho, os campos simples
    preenchidos (pelo rótulo), quantos itens tem cada grupo repetível e quantos anexos. Os links dos
    anexos e os itens dos grupos ficam de fora: para isso, use exportar_preenchimentos.
    Os preenchimentos vêm do mais recente para o mais antigo (data de criação). Os N mais recentes:
    pagina=1 e tamanho_pagina=N (1 chamada). Os mais antigos: use contar_preenchimentos e leia a última página.
    Custo: 1 chamada por página (a estrutura do formulário custa mais 1 na primeira vez). Para ler a
    próxima página, chame de novo com pagina+1 enquanto tem_proxima for verdadeiro. Para muitos
    preenchimentos, prefira exportar_preenchimentos.
    """
    cont = Contador()
    aviso = None
    if tamanho_pagina > LEITURA_MAX:
        aviso = f"tamanho_pagina reduzido de {tamanho_pagina} para {LEITURA_MAX} (máximo para leitura na conversa)."
        tamanho_pagina = LEITURA_MAX
    try:
        fid = _id_form(id_formulario)
        filtros = montar_filtros(criado_depois_de, criado_antes_de, editado_depois_de, editado_antes_de,
                                 origem, criado_por, editado_por)
        e = estrutura(fid, cont)
        r = api().get(f"/forms/{fid}/answers", {**filtros, "page": pagina, "page_size": tamanho_pagina}, cont)
    except ErroColetum as ex:
        return erro(str(ex), cont)
    ach = Achatador(e)
    pag = r.get("pagination") or {}
    res = {"id_formulario": fid, "filtros": descrever_filtros(filtros), "pagina": pag.get("page"),
           "tamanho_pagina": pag.get("page_size"), "total": pag.get("total_items"),
           "total_paginas": pag.get("total_pages"), "tem_proxima": bool(pag.get("has_next")),
           "preenchimentos": [ach.resumo(p) for p in r.get("data") or []]}
    if aviso:
        res["aviso"] = aviso
    return fim(res, cont)


# --------------------------------------------------------------------------------------------
def _paginar(fid: int, filtros: dict, max_paginas: int, tamanho: int, cont: Contador, ach: Achatador) -> dict:
    pagina, total, lidos, tem_proxima = 1, None, 0, True
    while tem_proxima and pagina <= max_paginas:
        r = api().get(f"/forms/{fid}/answers", {**filtros, "page": pagina, "page_size": tamanho}, cont)
        pag = r.get("pagination") or {}
        total = pag.get("total_items", total)
        for p in r.get("data") or []:
            ach.adicionar(p)
            lidos += 1
        tem_proxima = bool(pag.get("has_next"))
        pagina += 1
    return {"total": total or 0, "lidos": lidos, "paginas_lidas": pagina - 1, "completo": not tem_proxima}


class _Lista(list):
    """Recebe os preenchimentos crus de _paginar (mesma interface do Achatador)."""
    adicionar = list.append


AJUSTES_PLANILHA = (
    'Só quando o cliente pedir algo diferente do padrão do Coletum; vazio = igual à exportação do sistema. Chaves: '
    'campos{mostrar[] (só estes, nesta ordem), ocultar[]} com o rótulo, a chave ou o cabeçalho; '
    'aba_unica ("linhas": uma linha por resposta, repetindo os campos simples; "colunas": uma linha por preenchimento, '
    'cada resposta numa coluna numerada), sem abas filhas nem códigos de relacionamento; '
    'metadados ("fim" padrão, "inicio" ou "fora"); rotulos{cabeçalho ou rótulo atual: nome novo}; '
    'csv{separador ";" ou ",", decimal "," ou "."}; extras[] ("precisao", "altitude", "origem"). '
    'Ex.: {"aba_unica": "linhas", "campos": {"ocultar": ["Observações"]}}.')


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True))
@_gera_arquivo
def exportar_preenchimentos(
    id_formulario: IdForm,
    formato: Annotated[Literal["csv", "xlsx"], Field(description="xlsx (um arquivo: LEIA-ME, aba do formulário e uma aba por grupo repetível ou campo com várias respostas) ou csv (uma pasta: um arquivo por tabela e LEIA-ME.txt).")] = "xlsx",
    criado_depois_de: CriadoDepois = None, criado_antes_de: CriadoAntes = None,
    editado_depois_de: EditadoDepois = None, editado_antes_de: EditadoAntes = None,
    origem: Origem = None, criado_por: CriadoPor = None, editado_por: EditadoPor = None,
    max_paginas: Annotated[int, Field(ge=1, le=100, description="Limite de páginas (chamadas) a gastar com os preenchimentos. Padrão 5.")] = 5,
    tamanho_pagina: Annotated[int, Field(ge=1, le=500, description="Preenchimentos por página. Padrão 500 (o máximo, o que gasta menos chamadas). Reduza só para formulários muito pesados.")] = PAGINA_EXPORTACAO,
    pasta_saida: PastaSaida = None,
    ajustes: Annotated[dict | None, Field(description=AJUSTES_PLANILHA)] = None,
    gerado_por: Annotated[str | None, Field(description='Nome em "Exportação realizada por" no LEIA-ME. Padrão: "Coletum via MCP".')] = None,
) -> CallToolResult:
    """Exporta os preenchimentos filtrados para planilha no disco, no mesmo padrão da exportação do Coletum.

    Sem ajustes, o arquivo é o que o cliente já conhece: aba LEIA-ME, aba do formulário (1 linha por
    preenchimento, código, campos, contagem dos grupos e das fotos, metadados no fim) e uma aba por grupo
    repetível ou campo com várias respostas, ligadas pelos códigos (1.2, 1.2.0, 1.2.0.1) e por links internos.
    O CSV é o mesmo conjunto em arquivos: ponto e vírgula, vírgula decimal, UTF-8 com BOM.
    Com ajustes: escolher campos, aba única (modo linhas ou colunas), metadados no começo ou fora, rótulos,
    CSV com vírgula e ponto, extras. Ajuste inválido é recusado antes de ler os preenchimentos.
    Custo: 1 chamada por página de 500, mais 1 pela estrutura na primeira vez. Para em max_paginas e
    avisa se ficou preenchimento de fora. Devolve só o caminho, o link, as contagens e o consumo da cota, nunca o
    conteúdo (CSV: o link da pasta e o de cada arquivo). Rode contar_preenchimentos antes para saber quantas
    chamadas vai gastar.
    """

    cont = Contador()
    try:
        fid = _id_form(id_formulario)
        filtros = montar_filtros(criado_depois_de, criado_antes_de, editado_depois_de, editado_antes_de,
                                 origem, criado_por, editado_por)
        e = estrutura(fid, cont)
        try:
            esq = planilha.montar_esquema(e, formato, ajustes, fuso())
        except planilha.ErroAjuste as ex:
            return _resposta(erro(str(ex), cont))
        lidos = _Lista()
        info_pag = _paginar(fid, filtros, max_paginas, tamanho_pagina, cont, lidos)
    except ErroColetum as ex:
        return _resposta(erro(str(ex), cont))
    incompleto = None if info_pag["completo"] else (
        f"Limite de páginas atingido: {info_pag['lidos']} de {info_pag['total']} preenchimentos.")
    ctx = planilha.Contexto(datetime.now(fuso()), (gerado_por or "").strip() or planilha.GERADO_POR_PADRAO,
                            planilha.linhas_de_filtro(filtros), incompleto)
    caminho, contagens = planilha.exportar(e, lidos, formato, resolver_pasta(pasta_saida), ctx, esquema=esq)
    res = {"id_formulario": fid, "formato": formato, "caminho": str(caminho),
           "filtros": descrever_filtros(filtros), "total_na_api": info_pag["total"],
           "exportados": info_pag["lidos"], "paginas_lidas": info_pag["paginas_lidas"],
           "completo": info_pag["completo"], "linhas_por_tabela": contagens,
           "padrao": "Coletum" if not ajustes else "Coletum com ajustes"}
    aviso_formato = planilha.aviso_aba_unica(esq)
    if aviso_formato:
        res["aviso_aba_unica"] = aviso_formato
    if not info_pag["completo"]:
        faltam = info_pag["total"] - info_pag["lidos"]
        res["aviso"] = (f"Parou no limite de {max_paginas} página(s): ficaram {faltam} preenchimento(s) de fora. "
                        f"Aumente max_paginas (custaria mais {math.ceil(faltam / tamanho_pagina)} chamada(s)) "
                        "ou estreite os filtros.")
    arquivos = [caminho, *sorted(caminho.iterdir())] if caminho.is_dir() else [caminho]
    return _resposta(fim(res, cont), arquivos)


# --------------------------------------------------------------------------------------------
PDF_MAX = 100
MODELO_PADRAO_PDF = "coletum_exportacao"  # o PDF padrão é igual ao da exportação do Coletum


def _instante(criado_em: str) -> datetime:
    s = str(criado_em).strip()
    for tentativa in (s.replace(" ", "T", 1).replace("Z", "+00:00"), s):
        try:
            dt = datetime.fromisoformat(tentativa)
        except ValueError:
            try:
                dt = datetime.strptime(tentativa, "%Y-%m-%dT%H:%M:%S%z")
            except ValueError:
                continue
        return dt if dt.tzinfo else dt.replace(tzinfo=fuso())
    raise ErroColetum(f"criado_em inválido: '{criado_em}'. Use o criado_em que buscar_preenchimentos "
                      "devolve (ex.: 2026-09-01 08:15:00).")


def _janelas(itens: list) -> list[tuple[datetime, datetime, set]]:
    """Janelas de 10 minutos para cada lado do criado_em, juntando as que se sobrepõem.
    A API não busca preenchimento pelo id: cada janela é 1 consulta."""
    pares = sorted((_instante(i["criado_em"]), str(i["id"]).strip()) for i in itens)
    folga = timedelta(minutes=10)
    janelas: list = []
    for t, pid in pares:
        if janelas and t - folga <= janelas[-1][1]:
            janelas[-1][1] = t + folga
            janelas[-1][2].add(pid)
        else:
            janelas.append([t - folga, t + folga, {pid}])
    return [tuple(j) for j in janelas]


def _escolher_preenchimentos(fid: int, preenchimentos, ids_preenchimentos, criado_depois_de, criado_antes_de,
                             origem, criado_por, max_preenchimentos: int, cont: Contador,
                             avisos: list) -> tuple[list, dict, int | None]:
    """Seleção de preenchimentos comum a gerar_pdf_preenchimento e gerar_pdf_modelo: (1) id com criado_em, (2) ids com
    período, (3) só filtros. Devolve (escolhidos na ordem pedida, filtros usados, total com os filtros ou None)."""
    filtros: dict = {}
    e_filtros = montar_filtros(criado_depois_de, criado_antes_de, None, None, origem, criado_por, None)
    escolhidos: list = []
    total = None
    if preenchimentos:
        itens = []
        for i in preenchimentos:
            if not isinstance(i, dict) or not i.get("id") or not i.get("criado_em"):
                raise ErroColetum("Cada item de preenchimentos precisa de id e criado_em (os dois vêm de "
                                  "buscar_preenchimentos). A API não busca preenchimento pelo id.")
            itens.append(i)
        if len(itens) > PDF_MAX:
            raise ErroColetum(f"No máximo {PDF_MAX} preenchimentos por chamada.")
        achados: dict = {}
        for ini, fim_, ids in _janelas(itens):
            filtros = montar_filtros(ini.isoformat(), fim_.isoformat(), None, None, origem, criado_por, None)
            for pagina in (1, 2, 3):
                r = api().get(f"/forms/{fid}/answers", {**filtros, "page": pagina, "page_size": 500}, cont)
                for p in r.get("data") or []:
                    if str(p.get("id")) in ids:
                        achados[str(p.get("id"))] = p
                if ids <= set(achados) or not (r.get("pagination") or {}).get("has_next"):
                    break
        ordem = [str(i["id"]).strip() for i in itens]
        faltam = [x for x in ordem if x not in achados]
        if faltam:
            raise ErroColetum(f"Não encontrei os preenchimentos {', '.join(faltam)} em volta do criado_em "
                              "informado. Confira id e criado_em em buscar_preenchimentos.")
        escolhidos = [achados[x] for x in dict.fromkeys(ordem)]
        filtros = {"ids": ", ".join(dict.fromkeys(ordem))}
    elif ids_preenchimentos:
        if not (criado_depois_de or criado_antes_de):
            raise ErroColetum("Com ids_preenchimentos, informe um período (criado_depois_de e/ou "
                              "criado_antes_de) que os contenha, ou use preenchimentos com id e criado_em.")
        alvo = [str(x).strip() for x in ids_preenchimentos]
        filtros = e_filtros
        achados = {}
        for pagina in range(1, 6):
            r = api().get(f"/forms/{fid}/answers", {**filtros, "page": pagina, "page_size": 500}, cont)
            total = (r.get("pagination") or {}).get("total_items")
            for p in r.get("data") or []:
                if str(p.get("id")) in alvo:
                    achados[str(p.get("id"))] = p
            if set(alvo) <= set(achados) or not (r.get("pagination") or {}).get("has_next"):
                break
        faltam = [x for x in alvo if x not in achados]
        if faltam:
            raise ErroColetum(f"Não encontrei os preenchimentos {', '.join(faltam)} no período "
                              f"({descrever_filtros(filtros)}).")
        escolhidos = [achados[x] for x in dict.fromkeys(alvo)]
    else:
        filtros = e_filtros
        r = api().get(f"/forms/{fid}/answers", {**filtros, "page": 1, "page_size": min(max_preenchimentos, 500)}, cont)
        total = (r.get("pagination") or {}).get("total_items") or 0
        escolhidos = r.get("data") or []
        if not escolhidos:
            raise ErroColetum(f"Nenhum preenchimento com esses filtros ({descrever_filtros(filtros)}).")
        if total > len(escolhidos):
            avisos.append(f"Os filtros trazem {total} preenchimentos; entraram {len(escolhidos)} (os primeiros "
                          "que a API devolveu). Estreite os filtros, aumente max_preenchimentos ou escolha por id.")
    return escolhidos, filtros, total


MODELOS_COLETUM = ("coletum_exportacao", "coletum_colunas", "coletum_fotografico")
# Ajustes que os modelos do Coletum fazem. Qualquer outro é recusado, sem gerar outro visual.
AJUSTES_COLETUM = {"empresa.nome", "empresa.logo", "campos.ocultar", "campos.ordem", "campos.mostrar_vazios",
                   "campos.layout", "fotos.por_linha", "fonte.tamanho", "cores.destaque", "cores.primaria",
                   "pagina.orientacao"}
# Chaves que, com estes valores, pedem o que os modelos do Coletum já fazem.
AJUSTES_NEUTROS = {"campos.campos_por_linha": (1,), "fotos.incluir": (True,), "fotos.baixar": (True,),
                   "pagina.tamanho": ("A4", "a4"), "campos.mostrar": ([],), "varios.modo": ("um_pdf", "um_por_preenchimento")}
LAYOUT_PARA_MODELO = {"lista": "coletum_exportacao", "colunas": "coletum_colunas"}


def _folhas(d: dict, prefixo: str = ""):
    """Chaves pedidas, achatadas ('campos.ocultar'); _comentário e valor nulo não contam."""
    for k, v in (d or {}).items():
        if str(k).startswith("_") or v is None:
            continue
        if isinstance(v, dict):
            yield from _folhas(v, f"{prefixo}{k}.")
        else:
            yield f"{prefixo}{k}", v


def _mesclar_simples(base: dict, extra: dict) -> dict:
    saida = dict(base)
    for k, v in (extra or {}).items():
        saida[k] = _mesclar_simples(saida[k], v) if isinstance(v, dict) and isinstance(saida.get(k), dict) else v
    return saida


def _rota_pdf(ajustes: dict | None, template: str | None, modelo: str | None) -> dict:
    """Escolhe o modelo do Coletum (Typst) e separa os ajustes que nenhum deles faz.
    Devolve {modelo, pedido, fora, avisos}; com `fora` não vazio, a ferramenta recusa o pedido."""
    pedido: dict = {}
    if template and str(template).strip():
        p = Path(str(template)).expanduser()
        if not p.is_file():
            raise ErroColetum(f"Configuração não encontrada: {p}")
        try:
            pedido = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ErroColetum(f"Configuração com JSON inválido ({p.name}, linha {e.lineno}): {e.msg}") from None
    pedido = _mesclar_simples(pedido, ajustes or {})
    fora, avisos = [], []
    if not modelo and pedido.get("modelo") in MODELOS_COLETUM:  # a IA pôs o modelo dentro de ajustes
        modelo = pedido.pop("modelo")
    layout = None
    for chave, v in _folhas(pedido):
        if chave == "campos.layout":
            layout = str(v).strip().lower()
            if layout not in LAYOUT_PARA_MODELO:
                fora.append(f"campos.layout={v}")
        elif chave in AJUSTES_NEUTROS:
            if v not in AJUSTES_NEUTROS[chave]:
                fora.append(f"{chave}={json.dumps(v, ensure_ascii=False)}")
        elif chave not in AJUSTES_COLETUM:
            fora.append(chave)
    escolhido = modelo or LAYOUT_PARA_MODELO.get(layout or "", MODELO_PADRAO_PDF)
    if modelo and layout in LAYOUT_PARA_MODELO and LAYOUT_PARA_MODELO[layout] != modelo:
        avisos.append(f"campos.layout {layout} ignorado: o modelo pedido é {modelo}.")
    return {"modelo": escolhido, "pedido": pedido, "fora": fora, "avisos": avisos}


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True))
@_gera_arquivo
def gerar_pdf_preenchimento(
    id_formulario: IdForm,
    preenchimentos: Annotated[list[dict] | None, Field(description='Preenchimentos escolhidos, cada um com id e criado_em como buscar_preenchimentos devolve. Ex.: [{"id": "1024.3", "criado_em": "2026-09-01 08:15:00"}].')] = None,
    ids_preenchimentos: Annotated[list[str] | None, Field(description="Alternativa: só os ids, junto com um período (criado_depois_de/criado_antes_de) que os contenha.")] = None,
    criado_depois_de: CriadoDepois = None, criado_antes_de: CriadoAntes = None,
    origem: Origem = None, criado_por: CriadoPor = None,
    max_preenchimentos: Annotated[int, Field(ge=1, le=PDF_MAX, description=f"Só com filtros (sem ids): quantos preenchimentos entram no máximo. Padrão 20, máximo {PDF_MAX}.")] = 20,
    modo: Annotated[Literal["um_pdf", "um_por_preenchimento"] | None, Field(description="um_pdf (padrão): um arquivo com todos, cada preenchimento em página nova. um_por_preenchimento: um arquivo para cada.")] = None,
    modelo: Annotated[Literal["coletum_exportacao", "coletum_colunas", "coletum_fotografico"] | None, Field(description='Modelo do Coletum. coletum_exportacao (padrão): igual ao PDF da exportação. coletum_colunas: "em colunas", "compacto", pergunta à esquerda e resposta à direita. coletum_fotografico: "relatório fotográfico", "só as fotos", fotos grandes com legenda e os demais campos em letra pequena.')] = None,
    ajustes: Annotated[dict | None, Field(description='Ajustes pedidos na conversa, aplicados no próprio modelo do Coletum: empresa{nome,logo} (nome da conta na linha de 14 pt e logo no topo à direita), campos{ocultar[],ordem[],mostrar_vazios} (pela chave ou pelo rótulo, em qualquer nível), fotos{por_linha 1 a 4}, fonte{tamanho 6 a 16}, cores{destaque #RRGGBB: títulos de grupo e barras}, pagina{orientacao retrato|paisagem}; campos.layout colunas = modelo coletum_colunas. Ex.: {"empresa": {"nome": "Empresa Exemplo", "logo": "/caminho/logo.png"}, "campos": {"ocultar": ["Observações"]}, "fotos": {"por_linha": 1}}. Qualquer outra chave (titulo, subtitulo, rodape, metadados[], cores.clara, campos.mostrar[], campos.campos_por_linha 2, grupos_repetiveis.modo, fotos.max, fotos.incluir falso, varios.indice, pagina.margem_mm) os modelos do Coletum não fazem: a ferramenta recusa o pedido, sem chamar a API, e diz quais ajustes não existem.')] = None,
    template: Annotated[str | None, Field(description="Opcional: caminho de um JSON com ajustes, salvo pelo Claude para reaproveitar entre conversas. Os ajustes da chamada valem por cima dele; a mesma regra vale para as chaves dele.")] = None,
    pasta_saida: PastaSaida = None,
) -> CallToolResult:
    """Gera PDF de preenchimentos. O PDF padrão é o da exportação do Coletum (modelo coletum_exportacao, o mesmo
    de gerar_pdf_modelo); a resposta traz modelo e layout. Os ajustes pedidos na conversa ("põe meu logo", "tira
    o campo X", "uma foto por linha", fonte, cor de destaque, página deitada) valem NO PRÓPRIO modelo do Coletum:
    o visual continua o da exportação. modelo=coletum_colunas para "em colunas" ou "compacto" (pergunta |
    resposta); modelo=coletum_fotografico para "relatório fotográfico" ou "só as fotos". Se o pedido tem
    um ajuste que nenhum dos três faz (ver ajustes), a ferramenta recusa e diz quais ajustes não existem,
    sem gerar outro visual: avise o cliente e ofereça o modelo dele (analisar_pdf_modelo e gerar_pdf_modelo).

    Escolha: (1) preenchimentos com id e criado_em (de buscar_preenchimentos); (2) ids_preenchimentos com
    um período; (3) só filtros, até max_preenchimentos. Na escolha (3) entram os mais recentes, porque a API
    devolve do mais recente para o mais antigo: "PDF dos 5 últimos" = sem filtro e max_preenchimentos=5
    (1 chamada); para mostrar a lista antes, buscar_preenchimentos com pagina=1 e tamanho_pagina=5 e passe
    id e criado_em. Por padrão sai um PDF com todos, cada preenchimento em página nova;
    modo=um_por_preenchimento gera um arquivo para cada. As fotos são baixadas pelo link direto do
    armazenamento, sem passar pela conversa; se o link não responde, entra um quadro "foto indisponível".
    Custo: 1 chamada por janela de busca (ids com datas próximas dividem a mesma janela) ou 1 por
    página de filtro, mais 1 pela estrutura na primeira vez. Baixar fotos não gasta cota, mas gera tráfego para o
    Coletum (até 200 fotos por chamada).
    Devolve só caminhos, links, páginas e contagens, nunca o conteúdo (vários arquivos: o link de cada um e o
    da pasta).
    """

    cont = Contador()
    try:
        rota = _rota_pdf(ajustes, template, modelo)
    except ErroColetum as ex:
        return _resposta(erro(str(ex), cont))
    if rota["fora"]:
        return _resposta(erro(
            "Estes ajustes não existem nos modelos do Coletum e não geram outro visual: "
            + ", ".join(rota["fora"]) + ". O que os modelos fazem: empresa{nome,logo}, campos{ocultar,ordem,"
            "mostrar_vazios}, fotos{por_linha 1 a 4}, fonte{tamanho 6 a 16}, cores{destaque}, pagina{orientacao}, "
            "e o modelo coletum_colunas ou coletum_fotografico. Para um visual próprio, use o modelo do cliente "
            "(analisar_pdf_modelo e gerar_pdf_modelo).", cont))
    # Modelo do Coletum: mesmo caminho de gerar_pdf_modelo, com os ajustes como aparência.
    pedido = rota["pedido"]
    emp = pedido.get("empresa") if isinstance(pedido.get("empresa"), dict) else {}
    ap, avisos_ap = contrato.normalizar_aparencia(pedido)
    try:
        fid = _id_form(id_formulario)
        out, caminhos, _ = _gerar_no_modelo(
            fid, cont, rota["modelo"], None, None, None, preenchimentos, ids_preenchimentos,
            criado_depois_de, criado_antes_de, origem, criado_por, max_preenchimentos, modo or "um_pdf",
            emp.get("nome") or None, emp.get("logo") or None, None, 200, None, 1, pasta_saida, ap,
            rota["avisos"] + avisos_ap)
    except (ErroColetum, modelos.ErroModelo) as ex:
        return _erro_modelo(str(ex), cont)
    f = out["fotos"]
    out["layout"] = rota["modelo"]
    if ap or emp.get("nome") or emp.get("logo"):
        out["ajustes_aplicados"] = {**({"empresa": {k: v for k, v in emp.items() if k in ("nome", "logo") and v}}
                                       if emp.get("nome") or emp.get("logo") else {}), **ap}
    out["download_de_fotos"] = {"tentativas": f["tentativas"], "baixadas": f["baixadas"],
                                "mb_baixados": f["mb_baixados"], "motivos_de_falha": f["motivos_de_falha"]}
    return _resposta(fim(out, cont), caminhos)


def _arquivos_e_pasta(arquivos: list[dict]) -> list:
    """Caminhos dos arquivos gerados; com mais de um, a pasta deles vem primeiro."""
    caminhos = [Path(a["caminho"]) for a in arquivos]
    return ([caminhos[0].parent] if len(caminhos) > 1 else []) + caminhos


# --------------------------------------------------------------------------------------------
# PDF no modelo do cliente: análise do modelo, template Typst, modelos salvos e preferências
# --------------------------------------------------------------------------------------------

def _erro_modelo(msg: str, cont: Contador | None = None) -> CallToolResult:
    return _resposta(erro(msg, cont or Contador()))


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False))
def analisar_pdf_modelo(
    caminho: Annotated[str, Field(description="Caminho local do PDF (ou foto PNG/JPG) que o cliente já usa e quer replicar.")],
    paginas: Annotated[list[int] | None, Field(description="Páginas a analisar, começando em 1. Padrão: as primeiras, até 3 por chamada.")] = None,
    resolucao: Annotated[int, Field(ge=36, le=150, description="Pontos por polegada das imagens das páginas. Padrão 70 (leve); suba para ler letra miúda.")] = 70,
    pasta_saida: PastaSaida = None,
) -> CallToolResult:
    """Analisa o PDF modelo do cliente para replicar o layout num template Typst.

    Devolve JSON compacto (tamanho da página em mm, margens estimadas, linhas de texto com posição, fonte,
    tamanho, estilo e cor, cores dominantes do texto, das áreas preenchidas e das linhas, imagens embutidas com
    posição e tamanho) E as páginas renderizadas como imagem, para você ver o layout. As imagens embutidas são
    salvas em disco (candidatas a logo, com o caminho) para usar em gerar_pdf_modelo e salvar_modelo (arquivos).
    Foto do papel: só a imagem, sem texto extraído. Só lê o arquivo indicado. Não chama a API.
    """

    try:
        carimbo = datetime.now().strftime("%Y%m%d_%H%M%S")
        alvo = Path(caminho).expanduser()
        pasta = resolver_pasta(pasta_saida) / f"analise_{slug(alvo.stem, 30)}_{carimbo}"
        resumo, pngs = modelos.analisar(alvo, paginas, float(resolucao), pasta)
    except modelos.ErroModelo as ex:
        return _erro_modelo(str(ex))
    return _resposta(fim(resumo, Contador()), imagens=pngs)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True))
@_gera_arquivo
def gerar_pdf_modelo(
    id_formulario: IdForm,
    modelo: Annotated[str | None, Field(description="Nome de um modelo salvo ou embutido (listar_modelos), ou caminho de um arquivo .typ. Use isto OU template_typst.")] = None,
    template_typst: Annotated[str | None, Field(description="Texto do template Typst, para testar antes de salvar. Lê os dados com #import \"/coletum.typ\": * (contrato em CONTRATO_DADOS.md da skill pdf-no-modelo).")] = None,
    mapeamento: Annotated[dict | None, Field(description='Rótulo do modelo do cliente para o campo do formulário: {"Obra": "RODOVIA", "Km": "CADASTRO/KM", "Responsável": "meta:criado_por"}. Aceita chave ou rótulo, GRUPO[2]/CAMPO e meta:(id, criado_por, criado_em, horario_dispositivo, plataforma, coordenada). Vale por cima do mapeamento do modelo salvo. No template: valor_mapeado(p, "Obra").')] = None,
    arquivos: Annotated[list[str] | None, Field(description="Arquivos locais extras que o template usa (logo, imagem de fundo), copiados para /arquivos/<nome> no trabalho. Ex.: a imagem que analisar_pdf_modelo salvou.")] = None,
    preenchimentos: Annotated[list[dict] | None, Field(description='Preenchimentos escolhidos, cada um com id e criado_em como buscar_preenchimentos devolve.')] = None,
    ids_preenchimentos: Annotated[list[str] | None, Field(description="Alternativa: só os ids, junto com um período (criado_depois_de/criado_antes_de) que os contenha.")] = None,
    criado_depois_de: CriadoDepois = None, criado_antes_de: CriadoAntes = None,
    origem: Origem = None, criado_por: CriadoPor = None,
    max_preenchimentos: Annotated[int, Field(ge=1, le=PDF_MAX, description=f"Só com filtros (sem ids): quantos entram no máximo. Padrão 20, máximo {PDF_MAX}.")] = 20,
    modo: Annotated[Literal["um_pdf", "um_por_preenchimento"], Field(description="um_pdf (padrão): um arquivo com todos. um_por_preenchimento: um arquivo para cada.")] = "um_pdf",
    empresa: Annotated[str | None, Field(description="Nome da empresa ou da conta, em documento.empresa (o modelo coletum_exportacao põe no cabeçalho).")] = None,
    logo: Annotated[str | None, Field(description="Caminho de um logo (PNG, JPG, SVG), copiado como /arquivos/logo.<ext> e informado em documento.logo.")] = None,
    variaveis: Annotated[dict | None, Field(description='Textos livres para o template, em documento.variaveis (ex.: {"numero_relatorio": "12/2026"}).')] = None,
    aparencia: Annotated[dict | None, Field(description='Aparência pedida na conversa, em documento.aparencia (os modelos do Coletum aplicam; template próprio lê se quiser): campos{ocultar[],ordem[],mostrar_vazios} (o conector aplica nos campos, pela chave ou pelo rótulo, em qualquer nível), fotos{por_linha 1 a 4}, fonte{tamanho 6 a 16}, cores{destaque #RRGGBB}, pagina{orientacao retrato|paisagem}. Vale por cima da aparência do modelo salvo. Ex.: {"campos": {"ocultar": ["Observações"]}, "fotos": {"por_linha": 1}}.')] = None,
    max_fotos: Annotated[int, Field(ge=0, le=2000, description="Teto de fotos baixadas nesta chamada. Padrão 200.")] = 200,
    comparar_com: Annotated[str | None, Field(description="Caminho do PDF modelo do cliente: devolve também a imagem lado a lado (modelo à esquerda, amostra à direita) da página indicada.")] = None,
    pagina_comparada: Annotated[int, Field(ge=1, description="Página do lado a lado. Padrão 1.")] = 1,
    pasta_saida: PastaSaida = None,
) -> CallToolResult:
    """Gera PDF de um ou vários preenchimentos a partir de um template Typst (modelo salvo, arquivo .typ ou texto).

    Os modelos do Coletum (coletum_exportacao, o PDF padrão; coletum_colunas; coletum_fotografico) saem mais simples
    por gerar_pdf_preenchimento. Aqui entram o modelo do cliente e o template em teste; aparencia leva os mesmos
    ajustes (campos, fotos por linha, fonte, cor de destaque, orientação) para os modelos que a leem.

    Monta a pasta do trabalho (dados.json no contrato versão 1, fotos já baixadas, arquivos e fontes do modelo,
    coletum.typ) e compila com o Typst, com a raiz nessa pasta: o template não lê nada fora dela e não baixa
    pacotes. Erro de compilação volta com a mensagem do Typst, linha e coluna, para corrigir o template e gerar
    de novo. Escolha dos preenchimentos igual à de gerar_pdf_preenchimento (só com filtros, entram os mais
    recentes: "os 5 últimos" = max_preenchimentos=5). Com comparar_com, devolve a imagem
    lado a lado para comparar com o modelo do cliente. Salve o modelo aprovado com salvar_modelo e depois gere
    só pelo nome. Custo: 1 chamada por janela de busca ou página de filtro, mais 1 pela estrutura na 1ª vez;
    fotos não gastam cota. Links: o de cada PDF (com mais de um, também o da pasta) e o do lado a lado.
    """

    cont = Contador()
    try:
        fid = _id_form(id_formulario)
        ap, avisos_ap = contrato.normalizar_aparencia(aparencia)
        out, caminhos, pngs = _gerar_no_modelo(
            fid, cont, modelo, template_typst, mapeamento, arquivos, preenchimentos, ids_preenchimentos,
            criado_depois_de, criado_antes_de, origem, criado_por, max_preenchimentos, modo, empresa, logo,
            variaveis, max_fotos, comparar_com, pagina_comparada, pasta_saida, ap, avisos_ap)
    except (ErroColetum, modelos.ErroModelo) as ex:
        return _erro_modelo(str(ex), cont)
    return _resposta(fim(out, cont), caminhos, pngs)


def _gerar_no_modelo(fid: int, cont: Contador, modelo, template_typst, mapeamento, arquivos, preenchimentos,
                     ids_preenchimentos, criado_depois_de, criado_antes_de, origem, criado_por, max_preenchimentos,
                     modo, empresa, logo, variaveis, max_fotos, comparar_com, pagina_comparada,
                     pasta_saida, aparencia: dict | None = None,
                     avisos: list | None = None) -> tuple[dict, list, list]:
    """Corpo de gerar_pdf_modelo, reusado por gerar_pdf_preenchimento nos modelos do Coletum (coletum_exportacao,
    coletum_colunas, coletum_fotografico). aparencia já normalizada (contrato.normalizar_aparencia); vale por cima
    da aparência do modelo salvo. Devolve (resposta sem o consumo da cota, caminhos para os links, imagens). Levanta
    ErroColetum ou ErroModelo."""
    avisos = list(avisos or [])
    if bool(modelo) == bool(template_typst):
        raise ErroColetum("Informe modelo (nome salvo ou caminho .typ) OU template_typst (texto), um dos dois.")
    mapa: dict = {}
    if modelo:
        typ, pasta_modelo, meta = modelos.achar_modelo(modelo, config)
        texto = typ.read_text(encoding="utf-8")
        nome_modelo = pasta_modelo.name if typ.name == "modelo.typ" else typ.stem
        mapa.update(meta.get("mapeamento") or {})
        variaveis = {**(meta.get("variaveis") or {}), **(variaveis or {})}
        aparencia = contrato.mesclar_aparencia(meta.get("aparencia"), aparencia)
        forms = [int(x) for x in meta.get("formularios") or []]
        if forms and fid not in forms:
            avisos.append(f"O modelo '{nome_modelo}' foi feito para o(s) formulário(s) {forms}; campos do "
                          "mapeamento podem não existir neste.")
    else:
        modelos.verificar_template(template_typst)
        texto, pasta_modelo, nome_modelo = template_typst, None, "rascunho"
    mapa.update(mapeamento or {})
    escolhidos, filtros, total = _escolher_preenchimentos(
        fid, preenchimentos, ids_preenchimentos, criado_depois_de, criado_antes_de, origem, criado_por,
        max_preenchimentos, cont, avisos)
    e = estrutura(fid, cont)
    res, png = modelos.gerar(e, escolhidos, fid, texto, pasta_modelo, nome_modelo, mapa or None, arquivos,
                             empresa, logo, variaveis, modo, resolver_pasta(pasta_saida), max_fotos,
                             comparar_com, pagina_comparada, aparencia or None)
    out = {"id_formulario": fid, "filtros": descrever_filtros(filtros) if "ids" not in filtros else f"ids {filtros['ids']}",
           "preenchimentos_no_pdf": len(escolhidos), **res}
    if total is not None:
        out["total_com_os_filtros"] = total
    if res["fotos"]["motivos_de_falha"]:
        avisos.append("Algumas fotos ficaram indisponíveis (veja fotos.motivos_de_falha); o template recebe arquivo "
                      "nulo e a situação. No ambiente de desenvolvimento os links dão 403.")
    if res.get("fotos_simuladas"):
        avisos.append(fotos_teste.aviso(res["fotos_simuladas"]))
    if res.get("aparencia_sem_campo"):
        avisos.append("Nomes de campo pedidos na aparência (ocultar ou ordem) que não existem neste formulário: "
                      + "; ".join(res["aparencia_sem_campo"]) + ". Confira os rótulos em estrutura_formulario.")
    if (res.get("mapeamento") or {}).get("sem_campo"):
        avisos.append("Rótulos do modelo sem campo neste formulário (saem como vazios): "
                      + "; ".join(res["mapeamento"]["sem_campo"]))
    if avisos:
        out["avisos"] = avisos
    return out, [*_arquivos_e_pasta(res["arquivos"]), res.get("lado_a_lado")], [png] if png else []


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False))
def salvar_modelo(
    nome: Annotated[str, Field(description="Nome curto do modelo, minúsculas, números, _ ou - (ex.: vistoria_obra). É o que o cliente vai dizer: 'gera no modelo da obra'.")],
    template_typst: Annotated[str, Field(description="Texto do template Typst aprovado (o mesmo que gerou a amostra).")],
    descricao: Annotated[str | None, Field(description="Para que serve, em uma frase (quem lê, que documento é).")] = None,
    formularios: Annotated[list[int] | None, Field(description="Id(s) do(s) formulário(s) a que o modelo se aplica.")] = None,
    mapeamento: Annotated[dict | None, Field(description="Mapeamento confirmado: rótulo do modelo do cliente para o campo do formulário (mesmo formato de gerar_pdf_modelo).")] = None,
    arquivos: Annotated[list[str] | None, Field(description="Arquivos locais que o template usa (logo, imagens), guardados em arquivos/ do modelo.")] = None,
    fontes: Annotated[list[str] | None, Field(description="Arquivos de fonte (.ttf, .otf) que o template usa, guardados em fontes/ do modelo.")] = None,
    logo: Annotated[str | None, Field(description="Logo do cliente (PNG, JPG, SVG), guardado como arquivos/logo.<ext>: o template usa \"/arquivos/logo.png\" (ou dados.documento.logo).")] = None,
    variaveis: Annotated[dict | None, Field(description='Textos fixos do cliente que não vêm do formulário (ex.: {"obra": "...", "contratante": "..."}), usados como padrão em documento.variaveis; a chamada de gerar_pdf_modelo pode trocar.')] = None,
    aparencia: Annotated[dict | None, Field(description="Aparência padrão do modelo (mesmo formato de aparencia em gerar_pdf_modelo); a chamada pode trocar.")] = None,
    substituir: Annotated[bool, Field(description="Trocar um modelo que já existe com esse nome. Confirme com o cliente antes.")] = False,
) -> dict:
    """Salva um modelo de PDF na máquina do cliente, para reusar só pelo nome em gerar_pdf_modelo.

    Grava <pasta de modelos>/<nome>/ com modelo.typ, modelo.json (descrição, formulários, mapeamento, datas),
    arquivos/ e fontes/. Não sobrescreve sem substituir=true. Modelos embutidos não podem ser trocados. Não chama a API.
    """

    try:
        ap, avisos_ap = contrato.normalizar_aparencia(aparencia) if aparencia is not None else (None, [])
        r = modelos.salvar(config, nome, template_typst, descricao, formularios, mapeamento, arquivos, fontes,
                           substituir, logo, variaveis, ap)
    except modelos.ErroModelo as ex:
        return erro(str(ex), Contador())
    if avisos_ap:
        r["avisos"] = avisos_ap
    return fim(r, Contador())


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
def listar_modelos(
    mostrar_template: Annotated[str | None, Field(description="Nome de um modelo para trazer também o texto do template e o modelo.json (ex.: coletum_exportacao, para partir dele).")] = None,
) -> dict:
    """Lista os modelos de PDF disponíveis: os salvos na pasta de modelos do cliente e os embutidos (somente
    leitura: coletum_exportacao, que replica o PDF da exportação do Coletum, e os alternativos coletum_colunas e
    coletum_fotografico, com aparencia_aceita). Diz também se há preferências salvas. Com mostrar_template, traz o texto de um modelo para ajustar e salvar com outro nome. Não chama a API."""

    res = modelos.listar(config)
    if mostrar_template:
        try:
            typ, pasta, meta = modelos.achar_modelo(mostrar_template, config)
        except modelos.ErroModelo as ex:
            return erro(str(ex), Contador())
        res["template"] = {"nome": pasta.name, "texto": typ.read_text(encoding="utf-8"), "modelo_json": meta,
                           "arquivos": sorted(f.name for f in (pasta / "arquivos").glob("*")) if (pasta / "arquivos").is_dir() else []}
    return fim(res, Contador())


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
def ler_preferencias() -> dict:
    """Lê as preferências do cliente salvas (quem lê os documentos, para quê, frequência, identidade visual, o que
    nunca aparece, formato preferido). Leia no começo de qualquer tarefa de documento para não
    perguntar de novo. Não chama a API."""

    return fim(modelos.ler_preferencias(config), Contador())


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False))
def salvar_preferencias(
    texto: Annotated[str, Field(description="Preferências em markdown curto (seções e itens). Veja as perguntas essenciais da skill pdf-no-modelo.")],
    modo: Annotated[Literal["substituir", "acrescentar"], Field(description="substituir (padrão) reescreve o arquivo; acrescentar põe no fim.")] = "substituir",
) -> dict:
    """Salva as preferências do cliente em preferencias.md, na pasta de modelos, para as próximas conversas.
    Não chama a API."""

    try:
        return fim(modelos.salvar_preferencias(config, texto, modo), Contador())
    except modelos.ErroModelo as ex:
        return erro(str(ex), Contador())


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False))
def mostrar_arquivo(
    caminho: Annotated[str, Field(description="Caminho completo de um arquivo ou pasta que o conector gerou (o que veio no começo da resposta da ferramenta).")],
) -> dict:
    """Abre a pasta do sistema com o arquivo selecionado (Finder no Mac, Explorer no Windows; no Linux abre a pasta),
    para o usuário achar o que o conector gerou. Use quando ele pedir para abrir o arquivo ou a pasta. Só abre o que
    está na pasta de saída do conector ou o que alguma ferramenta gerou nesta conversa. Não chama a API."""
    cont = Contador()
    p = Path(caminho).expanduser()
    if not p.is_absolute():
        return erro(f"Use o caminho completo, como veio na resposta da ferramenta (recebido: '{caminho}').", cont)
    if not p.exists():
        return erro(f"Não existe: {p}. Confira o caminho que a ferramenta devolveu.", cont)
    p = p.resolve()
    saida = Path(config("COLETUM_PASTA_SAIDA") or PASTA_SAIDA_PADRAO).expanduser().resolve()
    if not any(p == r or p.is_relative_to(r) for r in {saida, *_gerados}):
        return erro(f"Só abro o que o conector gerou (pasta de saída {saida} ou arquivos desta conversa): {p}", cont)
    if sys.platform == "darwin":
        comando = ["open", "-R", str(p)]
    elif sys.platform == "win32":
        comando = ["explorer", f"/select,{p}"]
    else:
        comando = ["xdg-open", str(p if p.is_dir() else p.parent)]
    res = {"caminho": str(p), "comando": comando}
    if config("COLETUM_ABRIR_TESTE"):  # teste: registra o comando sem abrir janela
        return fim({**res, "simulado": True}, cont)
    try:
        r = subprocess.run(comando, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as ex:
        return erro(f"Não consegui abrir a pasta ({ex}). Mostre o caminho ao usuário: {p}", cont)
    if r.returncode != 0 and sys.platform != "win32":  # o explorer devolve 1 mesmo quando abre
        return erro(f"Não consegui abrir a pasta ({(r.stderr or '').strip() or r.returncode}). "
                    f"Mostre o caminho ao usuário: {p}", cont)
    return fim(res, cont)


# --------------------------------------------------------------------------------------------
# Skills como prompts: cada skills/<nome>/SKILL.md vira um prompt, para qualquer cliente MCP ter o passo a
# passo, não só o Claude Code com o plugin. Fonte única: o SKILL.md, lido do disco a cada pedido.
PASTA_SKILLS = Path(__file__).resolve().parent.parent / "skills"
NOMES_PROMPTS = {
    "pdf": "coletum-pdf",
    "planilha": "coletum-planilha",
    "pdf-no-modelo": "coletum-pdf-no-modelo",
    "migrar-v1": "coletum-migrar-v1",
}
_log = logging.getLogger("coletum")


def _separar_cabecalho(texto: str) -> tuple[dict, str]:
    """Separa o cabeçalho da skill (linhas `chave: valor` entre `---`) do corpo."""
    if texto.startswith("---"):
        partes = texto.split("---", 2)
        if len(partes) == 3:
            meta = {}
            for linha in partes[1].splitlines():
                chave, sep, valor = linha.partition(":")
                if sep and chave.strip():
                    meta[chave.strip()] = valor.strip()
            return meta, partes[2].lstrip("\n")
    return {}, texto


def _prompt_da_skill(arquivo: Path):
    def prompt(
        pedido: Annotated[str | None, Field(description="Opcional: o pedido do cliente, acrescentado no fim da skill.")] = None,
    ) -> str:
        if not arquivo.is_file():
            raise ValueError(f"A skill {arquivo.parent.name} não está mais nesta instalação ({arquivo}).")
        _, corpo = _separar_cabecalho(arquivo.read_text(encoding="utf-8"))
        corpo = corpo.rstrip()
        if pedido and pedido.strip():
            corpo += f"\n\nPedido do cliente: {pedido.strip()}"
        return corpo

    return prompt


def registrar_skills(pasta: Path = PASTA_SKILLS) -> list[str]:
    """Registra um prompt por `<pasta>/<nome>/SKILL.md`. Sem a pasta, o servidor sobe sem prompts."""
    if not pasta.is_dir():
        _log.warning("Pasta de skills não encontrada (%s): o servidor sobe sem prompts.", pasta)
        return []
    nomes = []
    for arquivo in sorted(pasta.glob("*/SKILL.md")):
        meta, _ = _separar_cabecalho(arquivo.read_text(encoding="utf-8"))
        nome = NOMES_PROMPTS.get(arquivo.parent.name) or meta.get("name") or f"coletum-{arquivo.parent.name}"
        descricao = meta.get("description") or f"Skill {arquivo.parent.name} do conector Coletum."
        mcp.prompt(name=nome, description=descricao)(_prompt_da_skill(arquivo))
        nomes.append(nome)
    if not nomes:
        _log.warning("Nenhuma SKILL.md em %s: o servidor sobe sem prompts.", pasta)
    return nomes


registrar_skills()


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
