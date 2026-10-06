"""Apoio dos modelos Typst: download das fotos e formatação de valores.

O Baixador baixa anexos pelo link direto do armazenamento, sem o token da API, só de hosts permitidos.
O fmt_valor devolve o texto pronto de um valor (Sim/Não, número com vírgula, data dd/mm/aaaa, coordenada).
Usados pelo contrato.py, que monta os dados que o template Typst lê. Com COLETUM_FOTOS_TESTE ligado (só no
ambiente local de teste), a foto cujo download falha vira uma imagem simulada (fotos_teste.py).
"""
from __future__ import annotations

import json
import os
import re
from urllib.parse import urlparse

import httpx

import fotos_teste
from achatar import coord5_texto, data_local, lat_long


def _numero(v) -> str:
    if isinstance(v, bool):
        return "Sim" if v else "Não"
    if isinstance(v, int):
        return str(v)
    s = f"{v:.6f}".rstrip("0").rstrip(".")
    return s.replace(".", ",")


def fmt_valor(v, tipo: str = "") -> str | None:
    if v is None or v == "" or v == [] or v == {}:
        return None
    if isinstance(v, bool):
        return "Sim" if v else "Não"
    if isinstance(v, (int, float)):
        return _numero(v)
    if isinstance(v, dict):
        if "coordinates" in v:
            la, lo = lat_long(v)
            return f"{coord5_texto(la)}, {coord5_texto(lo)}" if la is not None and lo is not None else None
        if "answer_id" in v:
            return str(v.get("label") or v.get("answer_id"))
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, list):
        partes = [fmt_valor(x, tipo) for x in v]
        partes = [p for p in partes if p]
        return ", ".join(partes) or None
    s = str(v)
    # campo data: a V2 manda o dia com hora e fuso ('2026-09-23T00:00:00-03:00'); vale o dia como veio, como a planilha
    if tipo == "date" and re.match(r"\d{4}-\d{2}-\d{2}(T|$)", s):
        return f"{s[8:10]}/{s[5:7]}/{s[:4]}"
    if tipo in ("datetime", "date_time") and re.match(r"\d{4}-\d{2}-\d{2}T", s):
        local, _ = data_local(s)
        if local:
            return f"{local[8:10]}/{local[5:7]}/{local[:4]} {local[11:16]}"
    return s



class Baixador:
    """Baixa anexos pelo link direto do armazenamento, SEM o token da API.

    Só aceita http(s) em hosts permitidos (padrão storage.googleapis.com; COLETUM_HOSTS_ANEXOS muda).
    Depois de 5 falhas seguidas para de tentar e marca as demais como indisponíveis com o mesmo motivo.
    Com COLETUM_FOTOS_TESTE ligado (só no ambiente local de teste), a foto cujo download real
    falhou vira uma imagem simulada (fotos_teste.py); simulada(link) diz quais foram.
    """

    MAX_BYTES = 30_000_000
    NAO_SIMULA = ("download desligado na configuração", "endereço fora dos hosts permitidos")

    def __init__(self, ativo: bool) -> None:
        self.ativo = ativo
        hosts = os.environ.get("COLETUM_HOSTS_ANEXOS", "storage.googleapis.com")
        self.hosts = {h.strip().lower() for h in hosts.split(",") if h.strip()}
        self._cli = httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0), follow_redirects=False)
        self.tentativas = self.baixadas = self.bytes = 0
        self.falhas_seguidas = 0
        self.parada: str | None = None
        self.motivos: dict[str, int] = {}
        self._cache: dict[str, tuple[bytes | None, str | None]] = {}
        self.simular = fotos_teste.ligado()
        self.simuladas = 0
        self.motivos_simuladas: dict[str, int] = {}
        self._simulados: set[str] = set()

    def baixar(self, link: str, rotulo: str | None = None, tipo: str | None = None) -> tuple[bytes | None, str | None]:
        if link in self._cache:
            return self._cache[link]
        r = self._baixar(link)
        if (r[0] is None and self.simular and r[1] not in self.NAO_SIMULA
                and fotos_teste.simulavel(link)):
            self.simuladas += 1
            self.motivos_simuladas[r[1]] = self.motivos_simuladas.get(r[1], 0) + 1
            self._simulados.add(link)
            r = (fotos_teste.gerar(link, rotulo, tipo), None)
        elif r[0] is None:
            self.motivos[r[1]] = self.motivos.get(r[1], 0) + 1
        self._cache[link] = r
        return r

    def simulada(self, link: str) -> bool:
        return link in self._simulados

    def resumo(self) -> dict:
        """download_de_fotos das respostas; as chaves das simuladas só aparecem com a simulação ligada."""
        r = {"tentativas": self.tentativas, "baixadas": self.baixadas, "mb_baixados": round(self.bytes / 1e6, 2),
             "motivos_de_falha": self.motivos}
        if self.simular:
            r.update({"simuladas": self.simuladas, "motivos_das_simuladas": self.motivos_simuladas})
        return r

    def _baixar(self, link: str) -> tuple[bytes | None, str | None]:
        if not self.ativo:
            return None, "download desligado na configuração"
        if self.parada:
            return None, self.parada
        u = urlparse(link or "")
        if u.scheme not in ("http", "https") or (u.hostname or "").lower() not in self.hosts:
            return None, "endereço fora dos hosts permitidos"
        self.tentativas += 1
        motivo = None
        try:
            with self._cli.stream("GET", link) as r:
                if r.status_code != 200:
                    motivo = f"o link respondeu {r.status_code}"
                else:
                    buf = bytearray()
                    for bloco in r.iter_bytes():
                        buf.extend(bloco)
                        if len(buf) > self.MAX_BYTES:
                            motivo = "arquivo maior que 30 MB"
                            break
                    if motivo is None:
                        self.baixadas += 1
                        self.bytes += len(buf)
                        self.falhas_seguidas = 0
                        return bytes(buf), None
        except httpx.HTTPError as e:
            motivo = f"o link não respondeu ({type(e).__name__})"
        self.falhas_seguidas += 1
        if self.falhas_seguidas >= 5:
            self.parada = f"{motivo}; após 5 falhas seguidas as demais não foram tentadas"
        return None, motivo

    def fechar(self) -> None:
        self._cli.close()
