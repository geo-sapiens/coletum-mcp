"""Cliente do Webservice V2 do Coletum (só leitura) e validação dos filtros.

Configuração por variáveis de ambiente (ou arquivo .env):
  COLETUM_TOKEN        token do Webservice V2 (obrigatório; nunca é impresso)
  COLETUM_BASE_URL     padrão https://coletum.com/api/webservice/v2 (produção)
  COLETUM_VERIFICAR_SSL  "0" ou "1"; padrão: 0 para localhost, 1 para os demais
  COLETUM_PASTA        pasta raiz dos arquivos: saídas em <pasta>/saidas e modelos em <pasta>/modelos
                       (vazia = Documentos/Coletum)
  COLETUM_PASTA_SAIDA, COLETUM_PASTA_MODELOS  pastas separadas; valem por cima de COLETUM_PASTA
  COLETUM_INTERVALO_S  intervalo mínimo, em segundos, entre o início de duas requisições (padrão 0,5)
  COLETUM_MAX_CHAMADAS_HORA  teto de chamadas por hora, janela móvel, somando todas as sessões (padrão 300)
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx

AQUI = Path(__file__).resolve().parent
BASE_PADRAO = "https://coletum.com/api/webservice/v2"
# Peso de uma chamada à API v2 na cota mensal da conta: hoje 5 chamadas bem-sucedidas = 1 unidade da cota.
# É regra de transição do produto, que vale enquanto a API v1 existir e pode mudar depois. Se mudar, muda só aqui:
# chamadas_api, cota_consumida e as estimativas de contar_preenchimentos saem desta constante.
PESO_COTA_V2 = 0.2
ORIGEM_DO_USO = "mcp"            # vai em toda requisição, como source=mcp
INTERVALO_PADRAO_S = 0.5         # entre o início de duas requisições
MAX_CHAMADAS_HORA_PADRAO = 300   # janela móvel de 1 hora
JANELA_S = 3600.0
ARQUIVO_USO = ".uso_api.json"
ORIGENS = {"mobile": "mobile", "aplicativo": "mobile", "web_private": "web_private",
           "web_privado": "web_private", "web_public": "web_public", "web_publico": "web_public"}


class ErroColetum(Exception):
    """Erro com mensagem em português, pronta para devolver à IA."""


class FiltroInvalido(ErroColetum):
    pass


def _ler_env_arquivo() -> dict[str, str]:
    """Procura um .env (só para desenvolvimento) na pasta atual, na pasta do servidor e na pasta acima."""
    candidatos = [Path.cwd() / ".env", AQUI / ".env", AQUI.parent / ".env"]
    vistos = set()
    for c in candidatos:
        c = c.resolve()
        if c in vistos or not c.is_file():
            continue
        vistos.add(c)
        valores = {}
        for linha in c.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            k, v = linha.split("=", 1)
            valores[k.strip()] = v.strip().strip('"').strip("'")
        if "COLETUM_TOKEN" in valores:
            return valores
    return {}


def pasta_padrao(sub: str, casa: Path | None = None) -> Path:
    """Pasta padrão do Coletum na máquina de quem usa.

    Com COLETUM_PASTA definida (e não vazia): <COLETUM_PASTA>/<sub>. Sem ela: Documentos/Coletum/<sub> (Mac,
    Windows, OneDrive), senão ~/Coletum/<sub>. COLETUM_PASTA_SAIDA e COLETUM_PASTA_MODELOS, quando definidas,
    valem por cima disso (quem as lê é server.resolver_pasta e modelos.pasta_modelos).
    """
    raiz = (config("COLETUM_PASTA") or "").strip()
    if raiz:
        return Path(raiz).expanduser() / sub
    casa = casa or Path.home()
    for d in (casa / "Documents", casa / "Documentos", casa / "OneDrive" / "Documents", casa / "OneDrive" / "Documentos"):
        if d.is_dir():
            return d / "Coletum" / sub
    return casa / "Coletum" / sub


def config(nome: str, padrao: str | None = None) -> str | None:
    if os.environ.get(nome):
        return os.environ[nome]
    return _ler_env_arquivo().get(nome, padrao)


@dataclass
class Contador:
    """Conta as requisições de uma chamada de ferramenta.

    chamadas = respostas 200, que é o que a API registra na cota (erro não conta).
    """
    requisicoes: int = 0
    chamadas: int = 0

    @property
    def cota(self) -> float:
        """Cota mensal consumida por estas chamadas (cada chamada à API v2 pesa PESO_COTA_V2)."""
        return cota_de(self.chamadas)


def cota_de(chamadas: int) -> float:
    """Cota mensal consumida por `chamadas` chamadas bem-sucedidas à API v2, em 2 casas."""
    return round(chamadas * PESO_COTA_V2, 2)


def _numero(nome: str, padrao: float, minimo: float) -> float:
    """Lê um número da configuração; vazio, inválido ou abaixo do mínimo cai no padrão."""
    bruto = config(nome)
    if bruto is None or str(bruto).strip() == "":
        return padrao
    try:
        v = float(str(bruto).strip().replace(",", "."))
    except ValueError:
        return padrao
    return v if v >= minimo else padrao


class _Limites:
    """Proteção contra rajadas, compartilhada por todas as requisições do processo: intervalo mínimo entre o
    início de duas requisições e teto de chamadas por hora (janela móvel). Os horários ficam num arquivo pequeno
    (.uso_api.json, na pasta raiz do Coletum) para valer entre sessões; se o arquivo não puder ser lido ou
    gravado, vale a contagem em memória."""

    def __init__(self) -> None:
        self._trava = threading.Lock()
        self._ultimo_inicio: float | None = None  # relógio monotônico
        self._horarios: list[float] = []          # relógio de parede, só do último hora

    @staticmethod
    def arquivo() -> Path:
        return pasta_padrao("saidas").parent / ARQUIVO_USO

    def _ler(self) -> list[float]:
        try:
            dados = json.loads(self.arquivo().read_text(encoding="utf-8"))
            return [float(x) for x in dados.get("chamadas", []) if isinstance(x, (int, float))]
        except (OSError, ValueError, AttributeError, TypeError):
            return []

    def _gravar(self, horarios: list[float]) -> None:
        try:
            alvo = self.arquivo()
            alvo.parent.mkdir(parents=True, exist_ok=True)
            tmp = alvo.with_name(alvo.name + f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps({"chamadas": horarios}), encoding="utf-8")
            os.replace(tmp, alvo)
        except OSError:
            pass  # sem arquivo, segue só com a contagem em memória

    def antes_de_chamar(self) -> None:
        """Dorme o que falta do intervalo mínimo, recusa se passou do teto por hora e registra a chamada."""
        intervalo = _numero("COLETUM_INTERVALO_S", INTERVALO_PADRAO_S, 0.0)
        teto = int(_numero("COLETUM_MAX_CHAMADAS_HORA", MAX_CHAMADAS_HORA_PADRAO, 1))
        with self._trava:
            agora = time.time()
            recentes = sorted({h for h in (*self._horarios, *self._ler()) if agora - h < JANELA_S})
            if len(recentes) >= teto:
                libera_em = max(1, int(recentes[0] + JANELA_S - agora) + 1)
                minutos = -(-libera_em // 60)
                raise ErroColetum(
                    f"Limite de segurança do conector: {len(recentes)} chamadas à API na última hora (teto de {teto}). "
                    f"Nada foi chamado agora. Volta a liberar em cerca de {minutos} min "
                    f"(às {datetime.fromtimestamp(recentes[0] + JANELA_S).strftime('%H:%M')}). "
                    "Espere e repita, ou estreite o pedido (filtros, menos páginas).")
            if self._ultimo_inicio is not None:
                falta = intervalo - (time.monotonic() - self._ultimo_inicio)
                if falta > 0:
                    time.sleep(falta)
            self._ultimo_inicio = time.monotonic()
            recentes.append(time.time())
            self._horarios = recentes
            self._gravar(recentes)


_limites = _Limites()


class ColetumAPI:
    def __init__(self) -> None:
        token = config("COLETUM_TOKEN")
        if not token:
            raise ErroColetum("COLETUM_TOKEN não configurado. Defina a variável de ambiente ou um arquivo .env.")
        self.base = (config("COLETUM_BASE_URL", BASE_PADRAO) or BASE_PADRAO).rstrip("/")
        host = urlparse(self.base).hostname or ""
        verificar = config("COLETUM_VERIFICAR_SSL")
        if verificar is None:
            verificar_ssl = host not in ("localhost", "127.0.0.1", "::1")
        else:
            verificar_ssl = verificar.strip() not in ("0", "false", "nao", "não")
        self._cliente = httpx.Client(
            base_url=self.base,
            headers={"Token": token, "Accept": "application/json", "Accept-Encoding": "gzip"},
            verify=verificar_ssl,
            timeout=httpx.Timeout(300.0, connect=15.0),
        )

    def get(self, caminho: str, params: dict, contador: Contador) -> dict:
        params = {**{k: v for k, v in params.items() if v is not None}, "source": ORIGEM_DO_USO}
        _limites.antes_de_chamar()  # recusa aqui, antes de chamar, se passou do teto por hora
        contador.requisicoes += 1
        try:
            r = self._cliente.get(caminho, params=params)
        except httpx.HTTPError as e:
            raise ErroColetum(f"Não foi possível falar com a API ({type(e).__name__}). "
                              "Confira COLETUM_BASE_URL e se o servidor está no ar.") from None
        if r.status_code == 200:
            contador.chamadas += 1
            return r.json()
        detalhe = ""
        try:
            corpo = r.json()
            detalhe = (corpo.get("error") or {}).get("message") if isinstance(corpo.get("error"), dict) else corpo.get("message")
        except Exception:
            pass
        detalhe = f" Detalhe da API: {detalhe}" if detalhe else ""
        mensagens = {
            400: "A API recusou um parâmetro da consulta (400).",
            401: "Token recusado pela API (401). Confira o COLETUM_TOKEN.",
            403: "Acesso negado pela API (403).",
            404: "Formulário não encontrado nesta conta (404). Confira o id com listar_formularios.",
            429: "Cota mensal da API esgotada (429). Espere a renovação da cota ou fale com o Coletum.",
        }
        raise ErroColetum(mensagens.get(r.status_code, f"A API respondeu com erro {r.status_code}.") + detalhe)


# --------------------------------------------------------------------------------------------
# Filtros
# --------------------------------------------------------------------------------------------

def _data(nome: str, valor: str | None) -> tuple[str | None, datetime | None]:
    if valor is None or str(valor).strip() == "":
        return None, None
    s = str(valor).strip()
    exemplo = "Use AAAA-MM-DD (ex.: 2026-08-01) ou data e hora ISO (ex.: 2026-08-01T08:00:00-03:00)."
    try:
        if len(s) == 10:
            d = date.fromisoformat(s)
            return s, datetime(d.year, d.month, d.day)
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.isoformat(), dt
    except ValueError:
        raise FiltroInvalido(f"Filtro {nome} inválido: '{s}' não é uma data válida. {exemplo}") from None


def _inteiro(nome: str, valor) -> int | None:
    if valor is None or str(valor).strip() == "":
        return None
    try:
        n = int(str(valor).strip())
    except ValueError:
        raise FiltroInvalido(f"Filtro {nome} inválido: '{valor}' não é um id numérico de usuário.") from None
    if n <= 0:
        raise FiltroInvalido(f"Filtro {nome} inválido: o id do usuário precisa ser positivo.")
    return n


def montar_filtros(criado_depois_de=None, criado_antes_de=None, editado_depois_de=None,
                   editado_antes_de=None, origem=None, criado_por=None, editado_por=None) -> dict:
    """Valida os filtros em português e devolve os parâmetros da API. Não chama a API."""
    params: dict = {}
    pares = [("criado_depois_de", "criado_antes_de", "created_after", "created_before",
              criado_depois_de, criado_antes_de),
             ("editado_depois_de", "editado_antes_de", "updated_after", "updated_before",
              editado_depois_de, editado_antes_de)]
    for n_ini, n_fim, api_ini, api_fim, v_ini, v_fim in pares:
        s_ini, d_ini = _data(n_ini, v_ini)
        s_fim, d_fim = _data(n_fim, v_fim)
        if d_ini and d_fim:
            a, b = d_ini, d_fim
            if a.tzinfo is None or b.tzinfo is None:
                a, b = a.replace(tzinfo=None), b.replace(tzinfo=None)
            if a >= b:
                raise FiltroInvalido(f"Período inválido: {n_ini} ({s_ini}) precisa ser anterior a {n_fim} ({s_fim}).")
        if s_ini:
            params[api_ini] = s_ini
        if s_fim:
            params[api_fim] = s_fim
    if origem is not None and str(origem).strip() != "":
        chave = str(origem).strip().lower()
        if chave not in ORIGENS:
            raise FiltroInvalido(f"Filtro origem inválido: '{origem}'. Use mobile (aplicativo), "
                                 "web_private (sistema, usuário logado) ou web_public (link público).")
        params["created_at_source"] = ORIGENS[chave]
    cp = _inteiro("criado_por", criado_por)
    ep = _inteiro("editado_por", editado_por)
    if cp:
        params["created_by"] = cp
    if ep:
        params["updated_by"] = ep
    return params


def descrever_filtros(params: dict) -> str:
    nomes = {"created_after": "criado depois de", "created_before": "criado antes de",
             "updated_after": "editado depois de", "updated_before": "editado antes de",
             "created_at_source": "origem", "created_by": "criado pelo usuário",
             "updated_by": "editado pelo usuário"}
    if not params:
        return "sem filtro (todos os preenchimentos)"
    return "; ".join(f"{nomes.get(k, k)} {v}" for k, v in params.items())
