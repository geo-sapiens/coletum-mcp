"""Achata preenchimentos do Coletum em tabelas internas, para a planilha, o PDF e o plano
de anexos. A planilha que o cliente recebe (exportar_preenchimentos) segue a exportação do Coletum e vem do
planilha.py.

- preenchimentos: 1 linha por preenchimento (metadados + campos simples + grupos de instância única)
- grupo_<nome>: 1 linha por item de grupo repetível (id_item, id_preenchimento, id_item_pai)
- valores_<campo>: 1 linha por valor de campo multivalorado simples
- arquivos_<campo>: 1 linha por arquivo (foto, galeria, arquivo, assinatura), com o link e a posição no campo
O id do item é o código da planilha no padrão do Coletum: o do pai mais ".n", com n a partir de 0
(1024.3.0 é o 1º item). A posição do arquivo no campo também começa em 0, como o código dele na aba da mídia.
Coordenada vira duas colunas, lat e long (a API manda long primeiro), com até 5 casas decimais como a tela
do Coletum (coord5). Datas vão para o fuso local, sem fuso, com o original numa coluna à parte.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

TIPOS_ARQUIVO = {"gallery", "photo", "picture", "image", "file", "signature", "attachment"}
TIPOS_COORDENADA = {"coordinate", "geolocation"}


def fuso() -> ZoneInfo:
    return ZoneInfo(os.environ.get("COLETUM_FUSO", "America/Sao_Paulo"))


def slug(texto: str, limite: int = 40) -> str:
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "_", t).strip("_").lower()
    return (t[:limite].strip("_")) or "sem_nome"


def data_local(valor: str | None) -> tuple[str | None, str | None]:
    """Converte '2026-09-01T08:15:00-0300' para '2026-09-01 08:15:00' no fuso local."""
    if not valor:
        return None, None
    try:
        dt = datetime.fromisoformat(valor)
    except ValueError:
        try:
            dt = datetime.strptime(valor, "%Y-%m-%dT%H:%M:%S%z")
        except ValueError:
            return valor, valor
    if dt.tzinfo is not None:
        dt = dt.astimezone(fuso()).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%d %H:%M:%S"), valor


CASAS_COORDENADA = 5   # como a tela do Coletum (~1 m)
_PASSO_COORD = Decimal(1).scaleb(-CASAS_COORDENADA)


def _coord_decimal(v) -> Decimal | None:
    if v is None or v == "" or isinstance(v, bool):
        return None
    try:
        d = Decimal(str(v).strip()).quantize(_PASSO_COORD, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() else None


def coord5(v) -> float | None:
    """Coordenada (lat ou long) com no máximo 5 casas decimais, como a tela do Coletum. Arredonda o decimal que
    a API mandou, meio para longe do zero: -26.908026424833 vira -26.90803. Toda coordenada que o conector
    escreve ou mostra passa por aqui (lat_long, planilha, PDF, contrato)."""
    d = _coord_decimal(v)
    return None if d is None else float(d) + 0.0   # + 0.0 tira o -0.0


def coord5_texto(v, decimal: str = ".") -> str | None:
    """A mesma coordenada em texto, sem zeros à direita: -33.8 fica -33.8, 151 fica 151."""
    d = _coord_decimal(v)
    if d is None:
        return None
    s = format(d, "f")
    s = s.rstrip("0").rstrip(".") if "." in s else s
    s = "0" if s in ("-0", "") else s
    return s.replace(".", decimal)


def coord_bruta(valor):
    """Cópia do valor da API ({"coordinates": [long, lat], ...}) com as duas coordenadas em até 5 casas."""
    if isinstance(valor, dict) and isinstance(valor.get("coordinates"), (list, tuple)):
        c = [coord5(x) if i < 2 and coord5(x) is not None else x for i, x in enumerate(valor["coordinates"])]
        return {**valor, "coordinates": c}
    if isinstance(valor, list):
        return [coord_bruta(x) for x in valor]
    return valor


def lat_long(valor) -> tuple[float | None, float | None]:
    if isinstance(valor, dict):
        c = valor.get("coordinates")
        if isinstance(c, (list, tuple)) and len(c) >= 2:
            return coord5(c[1]), coord5(c[0])
    return None, None


def eh_arquivo(comp: dict) -> bool:
    return comp.get("type") in TIPOS_ARQUIVO


def eh_multiplo(comp: dict) -> bool:
    return comp.get("maximum") != 1


def _texto(valor):
    valor = coord_bruta(valor)
    if isinstance(valor, (dict, list)):
        return json.dumps(valor, ensure_ascii=False)
    return valor


class Tabela:
    def __init__(self, nome: str, descricao: str) -> None:
        self.nome = nome
        self.descricao = descricao
        self.colunas: dict[str, str] = {}   # chave técnica -> rótulo
        self.tipos: dict[str, str] = {}
        self.links: set[str] = set()        # colunas com link (viram hiperlink no Excel)
        self.linhas: list[dict] = []
        self.chave_campo = ""               # campo de origem (tabelas de grupo, valores, arquivos)
        self.rotulo_campo = ""

    def col(self, chave: str, rotulo: str, tipo: str = "") -> str:
        if chave not in self.colunas:
            self.colunas[chave] = rotulo
            self.tipos[chave] = tipo
        return chave

    def cabecalhos(self) -> list[str]:
        vistos: dict[str, int] = {}
        for r in self.colunas.values():
            vistos[r] = vistos.get(r, 0) + 1
        return [r if vistos[r] == 1 else f"{r} [{k}]" for k, r in self.colunas.items()]


META = [
    ("id", "id do preenchimento", "id"),
    ("criado_em", "criado em (fuso local)", "data"),
    ("criado_em_original", "criado em (original da API)", "texto"),
    ("criado_por_id", "criado por (id)", "inteiro"),
    ("criado_por_nome", "criado por", "texto"),
    ("origem_criacao", "origem da criação", "texto"),
    ("dispositivo", "dispositivo", "texto"),
    ("lat", "lat (onde o aparelho estava)", "coordenada"),
    ("long", "long (onde o aparelho estava)", "coordenada"),
    ("precisao_m", "precisão da coordenada (m)", "numero"),
    ("altitude_m", "altitude (m)", "numero"),
    ("editado_em", "editado em (fuso local)", "data"),
    ("editado_em_original", "editado em (original da API)", "texto"),
    ("editado_por_id", "editado por (id)", "inteiro"),
    ("editado_por_nome", "editado por", "texto"),
    ("origem_edicao", "origem da edição", "texto"),
    ("total_size", "tamanho dos anexos (bytes)", "inteiro"),
]


def linha_meta(p: dict) -> dict:
    m = p.get("meta_data") or {}
    criado, criado_orig = data_local(m.get("created_at"))
    editado, editado_orig = data_local(m.get("updated_at"))
    coord = m.get("created_at_coordinates") or {}
    lat, lon = lat_long(coord)
    props = coord.get("properties") or {} if isinstance(coord, dict) else {}
    return {
        "id": p.get("id"), "criado_em": criado, "criado_em_original": criado_orig,
        "criado_por_id": m.get("created_by_user_id"), "criado_por_nome": m.get("created_by_user_name"),
        "origem_criacao": m.get("created_at_source"), "dispositivo": m.get("created_at_device"),
        "lat": lat, "long": lon, "precisao_m": props.get("precision"), "altitude_m": props.get("elevation"),
        "editado_em": editado, "editado_em_original": editado_orig,
        "editado_por_id": m.get("updated_by_user_id"), "editado_por_nome": m.get("updated_by_user_name"),
        "origem_edicao": m.get("updated_at_source"), "total_size": m.get("total_size"),
    }


class Achatador:
    """Recebe a estrutura do formulário e, página a página, os preenchimentos."""

    def __init__(self, estrutura: dict) -> None:
        self.estrutura = estrutura
        self.tabelas: dict[str, Tabela] = {}
        self._nome_por_comp: dict[str, str] = {}
        self.principal = self._nova("preenchimentos", "1 linha por preenchimento")
        for chave, rot, tipo in META:
            self.principal.col(chave, rot, tipo)
        # passagem de registro: fixa todas as colunas pela estrutura, mesmo sem dado
        self._preencher(estrutura.get("components") or [], {}, {}, self.principal, "", "", None, registrar=True)

    # ---- tabelas -----------------------------------------------------------------------------
    def _nova(self, nome: str, descricao: str) -> Tabela:
        base, n = nome[:31], 2
        while nome in self.tabelas:
            sufixo = f"_{n}"
            nome = base[:31 - len(sufixo)] + sufixo
            n += 1
        t = Tabela(nome, descricao)
        self.tabelas[nome] = t
        return t

    def _tabela_de(self, comp: dict, prefixo_nome: str, rotulo: str, colunas_base: list) -> Tabela:
        chave = comp["id"]
        if chave not in self._nome_por_comp:
            descricao = {"grupo": "1 linha por item do grupo repetível", "valores": "1 linha por valor do campo",
                         "arquivos": "1 linha por arquivo do campo"}[prefixo_nome] + f" '{rotulo}'"
            t = self._nova(f"{prefixo_nome}_{slug(comp.get('label') or chave, 22)}", descricao)
            t.chave_campo, t.rotulo_campo = chave, rotulo
            for c, r, tp in colunas_base:
                t.col(c, r, tp)
            self._nome_por_comp[chave] = t.nome
        return self.tabelas[self._nome_por_comp[chave]]

    def tabela_do_campo(self, chave: str) -> Tabela | None:
        """Tabela própria de um campo (grupo repetível, multivalorado ou arquivo), se houver."""
        nome = self._nome_por_comp.get(chave)
        return self.tabelas.get(nome) if nome else None

    # ---- achatamento -------------------------------------------------------------------------
    def adicionar(self, preenchimento: dict) -> None:
        linha = linha_meta(preenchimento)
        pid = str(preenchimento.get("id"))
        self._preencher(self.estrutura.get("components") or [], preenchimento.get("answer") or {},
                        linha, self.principal, "", pid, None)
        self.principal.linhas.append(linha)

    def _preencher(self, comps, valores, linha, tabela: Tabela, prefixo: str, pid: str,
                   id_item: str | None, registrar: bool = False) -> None:
        valores = valores if isinstance(valores, dict) else {}
        conhecidas = set()
        for c in comps:
            k = c.get("id")
            conhecidas.add(k)
            rot = prefixo + (c.get("label") or k)
            tipo = c.get("type") or ""
            v = valores.get(k)
            if tipo == "group":
                if eh_multiplo(c):
                    base = [("id_item", "id do item", "id"), ("id_preenchimento", "id do preenchimento", "id")]
                    if id_item is not None or (registrar and tabela is not self.principal):
                        base.append(("id_item_pai", "id do item pai", "id"))
                    tg = self._tabela_de(c, "grupo", rot, base)
                    tabela.col(f"{k}__qtd", f"{rot} · qtd de itens", "inteiro")
                    if registrar:
                        self._preencher(c.get("components") or [], {}, {}, tg, "", "", "x", registrar=True)
                        continue
                    itens = v if isinstance(v, list) else ([] if v is None else [v])
                    linha[f"{k}__qtd"] = len(itens)
                    for i, item in enumerate(itens):  # base 0, como o código da planilha
                        idi = f"{id_item or pid}.{i}"
                        sub = {"id_item": idi, "id_preenchimento": pid}
                        if id_item is not None:
                            sub["id_item_pai"] = id_item
                        self._preencher(c.get("components") or [], item, sub, tg, "", pid, idi)
                        tg.linhas.append(sub)
                else:
                    self._preencher(c.get("components") or [], v or {}, linha, tabela, rot + " · ", pid,
                                    id_item, registrar)
            elif eh_arquivo(c) or (isinstance(v, list) and v and isinstance(v[0], str) and v[0].startswith("http")):
                base = [("id_preenchimento", "id do preenchimento", "id"), ("id_item", "id do item", "id"),
                        ("posicao", "posição no campo (a partir de 0)", "inteiro"), ("link", "link do arquivo", "link")]
                ta = self._tabela_de(c, "arquivos", rot, base)
                ta.links.add("link")
                tabela.col(f"{k}__qtd", f"{rot} · qtd de arquivos", "inteiro")
                if registrar:
                    continue
                links = v if isinstance(v, list) else ([v] if v else [])
                linha[f"{k}__qtd"] = len(links)
                for n, link in enumerate(links):  # base 0, como o código na aba da mídia
                    ta.linhas.append({"id_preenchimento": pid, "id_item": id_item, "posicao": n, "link": link})
            elif tipo in TIPOS_COORDENADA or (isinstance(v, dict) and "coordinates" in v):
                tabela.col(f"{k}__lat", f"{rot} · lat", "coordenada")
                tabela.col(f"{k}__long", f"{rot} · long", "coordenada")
                if not registrar:
                    linha[f"{k}__lat"], linha[f"{k}__long"] = lat_long(v)
            elif isinstance(v, dict) and "answer_id" in v or tipo in ("relational", "relation"):
                tabela.col(k, rot, "texto")
                tabela.col(f"{k}__id", f"{rot} · id do preenchimento relacionado", "id")
                if not registrar and isinstance(v, dict):
                    linha[k], linha[f"{k}__id"] = v.get("label"), v.get("answer_id")
            elif eh_multiplo(c):
                tabela.col(k, f"{rot} (valores separados por |)", "texto")
                base = [("id_preenchimento", "id do preenchimento", "id"), ("id_item", "id do item", "id"),
                        ("valor", "valor", "texto")]
                tv = self._tabela_de(c, "valores", rot, base)
                if registrar:
                    continue
                vals = v if isinstance(v, list) else ([] if v is None else [v])
                linha[k] = " | ".join(str(_texto(x)) for x in vals) if vals else None
                for x in vals:
                    tv.linhas.append({"id_preenchimento": pid, "id_item": id_item, "valor": _texto(x)})
            else:
                tabela.col(k, rot, tipo)
                if not registrar:
                    linha[k] = _texto(v)
        if not registrar:
            for k, v in valores.items():
                if k not in conhecidas:
                    tabela.col(k, f"{prefixo}{k} (fora da estrutura atual)", "texto")
                    linha[k] = _texto(v)

    # ---- resumo compacto (para a IA ler) -----------------------------------------------------
    def resumo(self, preenchimento: dict, limite_texto: int = 300) -> dict:
        m = linha_meta(preenchimento)
        r = {"id": m["id"], "criado_em": m["criado_em"], "autor": m["criado_por_nome"],
             "autor_id": m["criado_por_id"], "origem": m["origem_criacao"],
             "lat": m["lat"], "long": m["long"]}
        if m["editado_em"]:
            r["editado_em"] = m["editado_em"]
            r["editado_por"] = m["editado_por_nome"]
        campos, grupos, anexos = {}, {}, [0]

        def visitar(comps, valores, prefixo):
            valores = valores if isinstance(valores, dict) else {}
            for c in comps:
                k, rot, tipo = c.get("id"), prefixo + (c.get("label") or c.get("id")), c.get("type")
                v = valores.get(k)
                if tipo == "group":
                    if eh_multiplo(c):
                        itens = v if isinstance(v, list) else []
                        grupos[rot] = len(itens)
                        anexos[0] += json.dumps(itens).count("http")
                    else:
                        visitar(c.get("components") or [], v, rot + " · ")
                elif eh_arquivo(c):
                    anexos[0] += len(v) if isinstance(v, list) else (1 if v else 0)
                elif v is None or v == [] or v == "":
                    continue
                elif tipo in TIPOS_COORDENADA or (isinstance(v, dict) and "coordinates" in v):
                    la, lo = lat_long(v)
                    campos[rot] = f"{coord5_texto(la)}, {coord5_texto(lo)}"
                elif isinstance(v, dict) and "answer_id" in v:
                    campos[rot] = v.get("label")
                else:
                    if isinstance(v, str) and len(v) > limite_texto:
                        v = v[:limite_texto] + "..."
                    campos[rot] = v

        visitar(self.estrutura.get("components") or [], preenchimento.get("answer") or {}, "")
        r["campos"] = campos
        if grupos:
            r["itens_por_grupo_repetivel"] = grupos
        r["qtd_anexos"] = anexos[0]
        return r


# --------------------------------------------------------------------------------------------
# Plano de anexos (sem baixar nada)
# --------------------------------------------------------------------------------------------

def plano_anexos(ach: Achatador, fid, nome_form: str) -> list[dict]:
    """1 linha por arquivo, com a pasta e o nome que ele receberia (O item
    (_iNN) e a posição (_NN final) no nome usam os mesmos números do código da planilha (base 0)."""
    principal = {str(l["id"]): l for l in ach.principal.linhas}
    # coordenada de cada item: a primeira coluna de coordenada da tabela do grupo
    coord_item: dict[str, tuple] = {}
    for t in ach.tabelas.values():
        if not t.nome.startswith("grupo_"):
            continue
        lat_cols = [k for k in t.colunas if k.endswith("__lat")]
        if not lat_cols:
            continue
        kl = lat_cols[0]
        for l in t.linhas:
            coord_item[l["id_item"]] = (l.get(kl), l.get(kl[:-5] + "__long"))
    arquivos_por_preench: dict[str, int] = {}
    for t in ach.tabelas.values():
        if t.nome.startswith("arquivos_"):
            for l in t.linhas:
                arquivos_por_preench[l["id_preenchimento"]] = arquivos_por_preench.get(l["id_preenchimento"], 0) + 1
    pasta_form = f"{fid}_{slug(nome_form, 30)}"
    saida = []
    for t in ach.tabelas.values():
        if not t.nome.startswith("arquivos_"):
            continue
        chave_campo, rotulo = t.chave_campo, t.rotulo_campo or t.nome
        campo_curto = slug(rotulo.split(" · ")[-1], 20)
        for l in t.linhas:
            pid = l["id_preenchimento"]
            p = principal.get(pid, {})
            criado = p.get("criado_em") or ""
            dia, mes = criado[:10] or "sem-data", criado[:7] or "sem-data"
            id_item = l.get("id_item")
            parte_item = ""
            if id_item:
                rel = id_item[len(pid) + 1:] if id_item.startswith(pid + ".") else id_item
                parte_item = "_i" + "-".join(f"{int(x):02d}" for x in rel.split(".") if x.isdigit())
            ext = Path(urlparse(l["link"]).path).suffix.lower() or ".bin"
            nome = f"{dia}_{pid.replace('.', '-')}_{campo_curto}{parte_item}_{int(l['posicao']):02d}{ext}"
            pasta = f"{pasta_form}/{mes}/{pid.replace('.', '-')}"
            total = p.get("total_size") or 0
            n = arquivos_por_preench.get(pid, 0) or 1
            li, lo = coord_item.get(id_item, (None, None)) if id_item else (None, None)
            saida.append({
                "arquivo_local": f"{pasta}/{nome}", "pasta": pasta, "nome_arquivo": nome,
                "id_preenchimento": pid, "id_item": id_item, "chave_campo": chave_campo,
                "rotulo_campo": rotulo, "posicao": l["posicao"], "data_preenchimento": criado,
                "autor": p.get("criado_por_nome"), "lat_preenchimento": p.get("lat"),
                "long_preenchimento": p.get("long"), "lat_item": li, "long_item": lo,
                "link_original": l["link"], "bytes_estimados": round(total / n) if total else None,
                "situacao": "pendente",
            })
    return saida
