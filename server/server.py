"""Servidor MCP do Coletum (só leitura), transporte stdio.

Lê a API de leitura do Coletum (Webservice V2) e entrega à IA resumos compactos, contagens e
exportações gravadas em disco. Nunca escreve na API. Veja o README.md do repositório para instalar e conectar.
"""
from __future__ import annotations

import base64
import json
import logging
import math
import re
import subprocess
import sys
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, ImageContent, ResourceLink, TextContent, ToolAnnotations
from pydantic import Field

sys.path.insert(0, str(Path(__file__).resolve().parent))
from achatar import Achatador, fuso, slug  # noqa: E402
from api import (guardar_token, MAX_CHAMADAS_HORA_PADRAO, PESO_COTA_V2, ColetumAPI, Contador,  # noqa: E402
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
        "Lê os dados de formulários do Coletum (só leitura). Cada chamada à API v2 gasta "
        f"{str(PESO_COTA_V2).replace('.', ',')} da cota mensal (peso de transição, pode mudar); as respostas trazem "
        f"chamadas_api e cota_consumida. Limite: {MAX_CHAMADAS_HORA_PADRAO} chamadas por hora. "
        "Fluxo: listar_formularios, estrutura_formulario, contar_preenchimentos com os filtros, e só então "
        "buscar_preenchimentos (ler uma página) ou exportar_preenchimentos (planilha em disco). Não puxe tudo: "
        "filtre e pagine. Os preenchimentos vêm do mais recente para o mais antigo: os N mais recentes são a "
        "página 1 com tamanho N. "
        "PDF: gerar_pdf_preenchimento; o padrão é o PDF da exportação do Coletum. Logo, campos, fotos por linha, "
        "fonte, cor e página deitada vão em ajustes; \"em colunas\" = modelo coletum_colunas; \"relatório "
        "fotográfico\" = modelo coletum_fotografico. No modelo do próprio cliente: analisar_pdf_modelo, "
        "gerar_pdf_modelo, salvar_modelo. Leia ler_preferencias no começo de tarefas de documento. "
        "Arquivo gravado: mostre ao usuário o caminho completo, como veio, em bloco de código, sem esperar que ele "
        "peça (nunca só \"na pasta do projeto\"); para abrir, mostrar_arquivo. Falta de token ou token recusado: "
        "peça ao usuário o token do Webservice V2 e chame configurar_token; nunca repita o token."
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
AVISO_LINKS = " Mostre ao usuário o caminho completo de cada arquivo, em bloco de código."
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
IdForm = Annotated[int, Field(description="Id do formulário (de listar_formularios).")]
CriadoDepois = Annotated[str | None, Field(description="Criados depois desta data (exclusivo): AAAA-MM-DD ou ISO.")]
CriadoAntes = Annotated[str | None, Field(description="Criados antes desta data (exclusivo).")]
EditadoDepois = Annotated[str | None, Field(description="Editados depois desta data (só os editados, não os novos).")]
EditadoAntes = Annotated[str | None, Field(description="Editados antes desta data.")]
Origem = Annotated[str | None, Field(description="mobile (aplicativo), web_private (sistema) ou web_public (link público).")]
CriadoPor = Annotated[int | None, Field(description="Id do autor (autor_id de buscar_preenchimentos).")]
EditadoPor = Annotated[int | None, Field(description="Id de quem editou por último.")]
PastaSaida = Annotated[str | None, Field(description="Pasta onde gravar. Padrão: Documentos/Coletum/saidas.")]


# --------------------------------------------------------------------------------------------
@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True))
def configurar_token(
    token: Annotated[str, Field(description="Token do Webservice V2 colado pelo usuário.")],
) -> dict:
    """Testa o token do Coletum (1 chamada) e o guarda no cofre do sistema. Use só quando uma ferramenta disser
    que falta o token ou que ele foi recusado."""
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


def _normalizar(s: str | None) -> str:
    """Sem acento, minúsculas, pontuação vira espaço: 'FWD - Parte II' vira 'fwd parte ii'."""
    s = "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c)).lower()
    return " ".join(re.sub(r"[\W_]+", " ", s).split())


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
def listar_formularios(
    nome: Annotated[str | None, Field(description="Busca aproximada: todas as palavras, em qualquer ordem, sem diferenciar acento, maiúsculas nem pontuação.")] = None,
    status: Annotated[Literal["enabled", "disabled"] | None, Field(description="Vazio traz todos.")] = None,
    pagina: Annotated[int, Field(ge=1)] = 1,
    tamanho_pagina: Annotated[int, Field(ge=1, le=500)] = 100,
) -> dict:
    """Lista os formulários da conta (id, nome, status, categoria, versão); o id entra nas outras ferramentas.
    1 chamada por página; tamanho_pagina 500 traz tudo em 1."""
    cont = Contador()

    def item(f: dict) -> dict:
        return {"id": f.get("id"), "nome": f.get("name"), "status": f.get("status"),
                "categoria": f.get("category"), "versao": f.get("version")}

    palavras = _normalizar(nome).split()
    try:
        if palavras:
            # busca aproximada local: traz até 500 formulários em 1 chamada e filtra aqui
            r = api().get("/forms", {"status": status, "page": 1, "page_size": 500}, cont)
            if ((r.get("pagination") or {}).get("total_pages") or 1) <= 1:
                achados = [item(f) for f in r.get("data") or []
                           if all(p in _normalizar(f.get("name")) for p in palavras)]
                total, ini = len(achados), (pagina - 1) * tamanho_pagina
                paginas = -(-total // tamanho_pagina)
                return fim({"formularios": achados[ini:ini + tamanho_pagina], "pagina": pagina, "total": total,
                            "total_paginas": paginas, "tem_proxima": pagina < paginas}, cont)
            # ponytail: conta com mais de 500 formulários cai na busca do servidor (parte do nome, exata)
        r = api().get("/forms", {"name": nome, "status": status, "page": pagina, "page_size": tamanho_pagina}, cont)
    except ErroColetum as e:
        return erro(str(e), cont)
    pag = r.get("pagination") or {}
    forms = [item(f) for f in r.get("data") or []]
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
    max_opcoes: Annotated[int, Field(ge=0, le=5000, description="Opções mostradas por campo de escolha.")] = 30,
    forcar_atualizacao: Annotated[bool, Field(description="Buscar de novo mesmo se já estiver em memória.")] = False,
) -> dict:
    """Campos do formulário em ordem: chave, rótulo, tipo, múltiplo, obrigatório, opções, regras de exibição e
    grupos. Dá os rótulos para os ajustes de planilha e PDF. 1 chamada na 1ª vez; depois fica em memória."""
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
    tamanho_pagina: Annotated[int, Field(ge=1, le=500, description="Página usada no cálculo de chamadas para ler tudo.")] = LEITURA_PADRAO,
) -> dict:
    """Conta os preenchimentos que batem com os filtros, sem trazê-los (1 chamada). Use antes de buscar ou
    exportar: diz quantas chamadas e quanta cota custaria ler ou exportar tudo."""
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
    pagina: Annotated[int, Field(ge=1)] = 1,
    tamanho_pagina: Annotated[int, Field(ge=1, description=f"Máximo {LEITURA_MAX}.")] = LEITURA_PADRAO,
) -> dict:
    """Traz UMA página de preenchimentos em resumo: id, criado_em, autor, origem, coordenada, campos simples pelo
    rótulo, contagem de itens de grupo e de anexos (itens e links de anexos: exportar_preenchimentos).
    1 chamada por página; próxima com pagina+1 enquanto tem_proxima. Os mais antigos: contar_preenchimentos e a
    última página. Para muitos preenchimentos, prefira exportar_preenchimentos."""
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
    'Só se o cliente pedir algo fora do padrão. campos{mostrar[] (só estes, nesta ordem), ocultar[]} pelo rótulo, '
    'chave ou cabeçalho; aba_unica "linhas" (uma linha por resposta) ou "colunas" (uma linha por preenchimento); '
    'metadados "fim"|"inicio"|"fora"; rotulos{atual: novo}; csv{separador, decimal}; extras[] (precisao, altitude, '
    'origem). Ex.: {"campos": {"mostrar": ["Data", "Local"]}}.')


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True))
@_gera_arquivo
def exportar_preenchimentos(
    id_formulario: IdForm,
    formato: Annotated[Literal["csv", "xlsx"], Field(description="xlsx (um arquivo) ou csv (uma pasta, um arquivo por tabela).")] = "xlsx",
    criado_depois_de: CriadoDepois = None, criado_antes_de: CriadoAntes = None,
    editado_depois_de: EditadoDepois = None, editado_antes_de: EditadoAntes = None,
    origem: Origem = None, criado_por: CriadoPor = None, editado_por: EditadoPor = None,
    max_paginas: Annotated[int, Field(ge=1, le=100, description="Limite de páginas (chamadas).")] = 5,
    tamanho_pagina: Annotated[int, Field(ge=1, le=500, description="Reduza só para formulário muito pesado.")] = PAGINA_EXPORTACAO,
    pasta_saida: PastaSaida = None,
    ajustes: Annotated[dict | None, Field(description=AJUSTES_PLANILHA)] = None,
    gerado_por: Annotated[str | None, Field(description='Nome em "Exportação realizada por" no LEIA-ME.')] = None,
) -> CallToolResult:
    """Grava os preenchimentos filtrados em planilha no disco, no padrão da exportação do Coletum (LEIA-ME, aba do
    formulário e uma aba por grupo repetível ou campo com várias respostas). Pedido fora do padrão vai em ajustes;
    ajuste inválido é recusado antes de ler. 1 chamada por página de 500; para em max_paginas e avisa o que ficou
    de fora. Devolve caminho e contagens, nunca o conteúdo."""

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
    preenchimentos: Annotated[list[dict] | None, Field(description='Cada um com id e criado_em de buscar_preenchimentos. Ex.: [{"id": "1024.3", "criado_em": "2026-09-01 08:15:00"}].')] = None,
    ids_preenchimentos: Annotated[list[str] | None, Field(description="Alternativa: só os ids, com um período que os contenha.")] = None,
    criado_depois_de: CriadoDepois = None, criado_antes_de: CriadoAntes = None,
    origem: Origem = None, criado_por: CriadoPor = None,
    max_preenchimentos: Annotated[int, Field(ge=1, le=PDF_MAX, description="Só com filtros (sem ids): quantos entram, os mais recentes.")] = 20,
    modo: Annotated[Literal["um_pdf", "um_por_preenchimento"] | None, Field(description="um_pdf (padrão, todos num arquivo) ou um arquivo para cada.")] = None,
    modelo: Annotated[Literal["coletum_exportacao", "coletum_colunas", "coletum_fotografico"] | None, Field(description='coletum_exportacao (padrão); coletum_colunas ("em colunas", "compacto"); coletum_fotografico ("relatório fotográfico", "só as fotos").')] = None,
    ajustes: Annotated[dict | None, Field(description='Pedidos da conversa, no próprio modelo: empresa{nome,logo (caminho)}, campos{ocultar[],ordem[],mostrar_vazios} pela chave ou rótulo, fotos{por_linha 1 a 4}, fonte{tamanho 6 a 16}, cores{destaque #RRGGBB}, pagina{orientacao retrato|paisagem}. Ex.: {"empresa": {"logo": "/caminho/logo.png"}, "campos": {"ocultar": ["Observações"]}}. Outra chave (título, rodapé, metadados, 2 campos por linha, limite de fotos) é recusada.')] = None,
    template: Annotated[str | None, Field(description="Opcional: caminho de um JSON de ajustes salvo; os ajustes da chamada valem por cima.")] = None,
    pasta_saida: PastaSaida = None,
) -> CallToolResult:
    """Gera PDF de preenchimentos num modelo do Coletum; o padrão é o PDF da exportação. Ajuste que os modelos não
    fazem é recusado com a lista do que não existe, sem gerar outro visual: ofereça o modelo do cliente
    (analisar_pdf_modelo, gerar_pdf_modelo).
    Escolha: (1) preenchimentos com id e criado_em; (2) ids_preenchimentos com um período; (3) só filtros: entram
    os mais recentes ("PDF dos 5 últimos" = sem filtro, max_preenchimentos=5). Fotos vêm direto do armazenamento
    (não gastam cota; até 200). 1 chamada por janela de busca ou página de filtro. Devolve caminhos e contagens."""

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
            rota["avisos"] + avisos_ap, manter_trabalho=False)
    except (ErroColetum, modelos.ErroModelo) as ex:
        pasta = getattr(ex, "pasta_do_trabalho", None)
        if not (pasta and Path(pasta).is_dir()):
            return _erro_modelo(str(ex), cont)
        return _resposta({**erro(f"{ex}\nA pasta do trabalho ficou em {pasta} (dados.json, fotos e modelo.typ), "
                                 "para conferir.", cont), "pasta_do_trabalho": pasta})
    f = out["fotos"]
    out["layout"] = rota["modelo"]
    if ap or emp.get("nome") or emp.get("logo"):
        out["ajustes_aplicados"] = {**({"empresa": {k: v for k, v in emp.items() if k in ("nome", "logo") and v}}
                                       if emp.get("nome") or emp.get("logo") else {}), **ap}
    out["download_de_fotos"] = {"tentativas": f["tentativas"], "baixadas": f["baixadas"],
                                "mb_baixados": f["mb_baixados"], "do_cache": f["do_cache"],
                                "motivos_de_falha": f["motivos_de_falha"]}
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
    caminho: Annotated[str, Field(description="Caminho local do PDF, PNG ou JPG.")],
    paginas: Annotated[list[int] | None, Field(description="Começando em 1. Padrão: as 3 primeiras.")] = None,
    resolucao: Annotated[int, Field(ge=36, le=150, description="DPI das imagens; suba para letra miúda.")] = 70,
    pasta_saida: PastaSaida = None,
) -> CallToolResult:
    """Analisa o PDF (ou foto) que o cliente usa, para replicar o layout num template Typst. Devolve JSON compacto
    (página, margens, linhas de texto com posição, fonte e cor, cores dominantes, imagens embutidas salvas em disco
    como candidatas a logo) e as páginas como imagem. Não chama a API."""

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
    modelo: Annotated[str | None, Field(description="Modelo salvo ou embutido (listar_modelos) ou caminho .typ. Isto OU template_typst.")] = None,
    template_typst: Annotated[str | None, Field(description="Texto Typst em teste; lê os dados com #import \"/coletum.typ\": * (contrato na skill pdf-no-modelo).")] = None,
    mapeamento: Annotated[dict | None, Field(description='Rótulo do modelo do cliente para o campo: {"Obra": "RODOVIA", "Km": "CADASTRO/KM", "Responsável": "meta:criado_por"}. No template: valor_mapeado(p, "Obra").')] = None,
    arquivos: Annotated[list[str] | None, Field(description="Arquivos locais que o template usa, em /arquivos/<nome>.")] = None,
    preenchimentos: Annotated[list[dict] | None, Field(description='Cada um com id e criado_em de buscar_preenchimentos.')] = None,
    ids_preenchimentos: Annotated[list[str] | None, Field(description="Alternativa: só os ids, com um período que os contenha.")] = None,
    criado_depois_de: CriadoDepois = None, criado_antes_de: CriadoAntes = None,
    origem: Origem = None, criado_por: CriadoPor = None,
    max_preenchimentos: Annotated[int, Field(ge=1, le=PDF_MAX, description="Só com filtros (sem ids): quantos entram, os mais recentes.")] = 20,
    modo: Annotated[Literal["um_pdf", "um_por_preenchimento"], Field(description="um_pdf (todos num arquivo) ou um arquivo para cada.")] = "um_pdf",
    empresa: Annotated[str | None, Field(description="Em documento.empresa.")] = None,
    logo: Annotated[str | None, Field(description="Caminho do logo, em /arquivos/logo.<ext> e documento.logo.")] = None,
    variaveis: Annotated[dict | None, Field(description='Textos livres em documento.variaveis.')] = None,
    aparencia: Annotated[dict | None, Field(description='Mesmas chaves de ajustes de gerar_pdf_preenchimento, sem empresa; vai em documento.aparencia e vale por cima da do modelo salvo.')] = None,
    max_fotos: Annotated[int, Field(ge=0, le=2000, description="Teto de fotos baixadas.")] = 200,
    comparar_com: Annotated[str | None, Field(description="Caminho do PDF do cliente: devolve também a imagem lado a lado.")] = None,
    pagina_comparada: Annotated[int, Field(ge=1)] = 1,
    pasta_saida: PastaSaida = None,
) -> CallToolResult:
    """Gera PDF de preenchimentos num template Typst: modelo do cliente (salvo ou .typ) ou texto em teste. Para os
    modelos do Coletum, use gerar_pdf_preenchimento. Compila numa pasta isolada (sem ler fora dela nem baixar
    pacotes); erro de compilação volta com mensagem, linha e coluna. Escolha dos preenchimentos e custo iguais aos
    de gerar_pdf_preenchimento. Modelo aprovado: salvar_modelo e depois só o nome."""

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
                     avisos: list | None = None, manter_trabalho: bool = True) -> tuple[dict, list, list]:
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
                             comparar_com, pagina_comparada, aparencia or None, manter_trabalho)
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
    nome: Annotated[str, Field(description="Minúsculas, números, _ ou - (ex.: vistoria_obra).")],
    template_typst: Annotated[str, Field(description="Texto Typst aprovado.")],
    descricao: Annotated[str | None, Field(description="Para que serve, em uma frase.")] = None,
    formularios: Annotated[list[int] | None, Field(description="Ids dos formulários do modelo.")] = None,
    mapeamento: Annotated[dict | None, Field(description="Mapeamento confirmado (formato de gerar_pdf_modelo).")] = None,
    arquivos: Annotated[list[str] | None, Field(description="Arquivos que o template usa (vão para arquivos/).")] = None,
    fontes: Annotated[list[str] | None, Field(description="Fontes .ttf/.otf (vão para fontes/).")] = None,
    logo: Annotated[str | None, Field(description="Logo (vai para arquivos/logo.<ext>).")] = None,
    variaveis: Annotated[dict | None, Field(description='Textos fixos do cliente, padrão de documento.variaveis.')] = None,
    aparencia: Annotated[dict | None, Field(description="Aparência padrão (formato de gerar_pdf_modelo).")] = None,
    substituir: Annotated[bool, Field(description="Troca um modelo existente; confirme com o cliente.")] = False,
) -> dict:
    """Salva um modelo de PDF na máquina do cliente, para gerar depois só pelo nome. Não sobrescreve sem
    substituir; os embutidos não podem ser trocados. Não chama a API."""

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
    mostrar_template: Annotated[str | None, Field(description="Nome de um modelo para trazer o texto do template e o modelo.json.")] = None,
) -> dict:
    """Lista os modelos de PDF (os salvos pelo cliente e os embutidos do Coletum) e se há preferências salvas.
    Não chama a API."""

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
    """Lê as preferências salvas do cliente (quem lê, para quê, identidade visual, o que nunca aparece, formato),
    para não perguntar de novo. Não chama a API."""

    return fim(modelos.ler_preferencias(config), Contador())


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False))
def salvar_preferencias(
    texto: Annotated[str, Field(description="Markdown curto.")],
    modo: Annotated[Literal["substituir", "acrescentar"], Field(description="substituir reescreve; acrescentar põe no fim.")] = "substituir",
) -> dict:
    """Salva as preferências do cliente para as próximas conversas. Não chama a API."""

    try:
        return fim(modelos.salvar_preferencias(config, texto, modo), Contador())
    except modelos.ErroModelo as ex:
        return erro(str(ex), Contador())


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False))
def mostrar_arquivo(
    caminho: Annotated[str, Field(description="Caminho completo que a ferramenta devolveu.")],
) -> dict:
    """Abre a pasta do sistema com o arquivo selecionado, quando o usuário pedir. Só abre o que o conector gerou."""
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
