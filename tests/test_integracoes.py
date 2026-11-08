"""Clientes das integrações: resiliência da visão (retry, circuito), GeoSampa (fallback) e Open-Meteo."""
import pytest

from conftest import P1, Resp, SessaoClima, SessaoVisao, SessaoWFS, foto_unica
from rua_acesa_rpa.clima import ClienteClima
from rua_acesa_rpa.postes import LocalizadorPostes
from rua_acesa_rpa.repositorio import Repositorio
from rua_acesa_rpa.visao import ClienteVisao, FotoRejeitada, VisaoIndisponivel


def _cliente(sessao, dormidas=None, **kw):
    return ClienteVisao("http://visao.teste", tentativas=3, backoff_s=1.0, limite_circuito=2, sessao=sessao,
                        dormir=(dormidas if dormidas is not None else []).append, **kw)


@pytest.fixture
def foto(tmp_path):
    return foto_unica(tmp_path / "R1.jpg")


# ---------------------------------------------------------------- visão
def test_visao_sucesso(foto):
    r = _cliente(SessaoVisao()).detectar(foto)
    assert r.veredito == "confirmado" and r.confianca_apagado == pytest.approx(0.91)


def test_visao_retry_com_backoff_exponencial(foto):
    s, dormidas = SessaoVisao(), []
    s.timeouts_restantes = 2
    r = _cliente(s, dormidas).detectar(foto)
    assert r.veredito == "confirmado" and len(s.chamadas) == 3 and dormidas == [1.0, 2.0]


def test_visao_fora_do_ar_e_circuito_abre(foto):
    s = SessaoVisao()
    s.fora = True
    c = _cliente(s)
    for _ in range(2):
        with pytest.raises(VisaoIndisponivel, match="sem conexão"):
            c.detectar(foto)
    assert c.circuito_aberto and len(s.chamadas) == 6
    with pytest.raises(VisaoIndisponivel, match="circuito aberto"):
        c.detectar(foto)
    assert len(s.chamadas) == 6  # circuito aberto: nem tenta


def test_visao_5xx_e_repetido(foto):
    s = SessaoVisao({"R1": "http500"})
    with pytest.raises(VisaoIndisponivel, match="HTTP 500"):
        _cliente(s).detectar(foto)
    assert len(s.chamadas) == 3


def test_visao_foto_recusada_nao_repete(foto):
    s = SessaoVisao({"R1": "http415"})
    with pytest.raises(FotoRejeitada, match="415"):
        _cliente(s).detectar(foto)
    assert len(s.chamadas) == 1


def test_visao_resposta_fora_do_contrato_nao_repete(foto):
    s = SessaoVisao({"R1": "lixo"})
    with pytest.raises(VisaoIndisponivel, match="resposta inválida"):
        _cliente(s).detectar(foto)
    assert len(s.chamadas) == 1


def test_visao_sucesso_zera_contador_de_falhas(foto):
    s = SessaoVisao()
    c = _cliente(s)
    s.fora = True
    with pytest.raises(VisaoIndisponivel):
        c.detectar(foto)
    s.fora = False
    c.detectar(foto)
    assert c.falhas_seguidas == 0


# ---------------------------------------------------------------- GeoSampa
@pytest.fixture
def repo(tmp_path):
    r = Repositorio(tmp_path / "t.db")
    yield r
    r.fechar()


def test_poste_mais_proximo_via_wfs_sem_placa_repetida(repo, cfg):
    loc = LocalizadorPostes("http://wfs", repo, cfg.postes_csv, sessao=SessaoWFS())
    res = loc.localizar(P1[0] + 5 / 111_320, P1[1], 40)
    assert res.poste.placa == "IP0000001" and res.fonte == "geosampa_wfs" and res.distancia_m == pytest.approx(5, abs=0.5)
    assert len(repo.postes_cache_na_caixa(-24, -47, -23, -46)) == 1


def test_nenhum_poste_no_raio(repo, cfg):
    res = LocalizadorPostes("http://wfs", repo, cfg.postes_csv, sessao=SessaoWFS()).localizar(-23.60, -46.60, 40)
    assert res.poste is None and res.fonte == "nenhuma"


def test_wfs_fora_usa_cache(repo, cfg):
    s = SessaoWFS()
    LocalizadorPostes("http://wfs", repo, None, sessao=s).localizar(*P1, 40)  # aquece o cache
    s.fora = True
    res = LocalizadorPostes("http://wfs", repo, None, sessao=s).localizar(*P1, 40)
    assert res.fonte == "cache" and res.poste.placa == "IP0000001" and "indisponível" in res.aviso


def test_wfs_fora_sem_cache_usa_recorte_csv(repo, cfg):
    s = SessaoWFS()
    s.fora = True
    loc = LocalizadorPostes("http://wfs", repo, cfg.postes_csv, sessao=s)
    assert loc.localizar(*P1, 40).fonte == "csv"
    loc.localizar(*P1, 40)
    assert s.chamadas == 1  # depois da 1ª falha não insiste no mesmo lote


# ---------------------------------------------------------------- Open-Meteo
def test_clima_noite_chuvosa_e_cache():
    s = SessaoClima(chuva=True, nuvens=90)
    c = ClienteClima("http://clima", sessao=s)
    cond = c.consultar(-23.561, -46.656)
    assert cond.disponivel and cond.chuva_noturna and cond.encoberto and cond.horas_noturnas == 12
    c.consultar(-23.5612, -46.6561)  # vizinho (~1 km): mesma consulta
    assert s.chamadas == 1


def test_clima_fora_do_ar_degrada():
    s = SessaoClima()
    s.fora = True
    cond = ClienteClima("http://clima", tentativas=2, sessao=s, dormir=lambda _: None).consultar(-23.5, -46.6)
    assert not cond.disponivel and "indisponível" in cond.detalhe and s.chamadas == 2


def test_clima_resposta_quebrada_degrada():
    class Quebrada(SessaoClima):
        def get(self, *a, **k):
            return Resp(200, {"sem": "hourly"})
    cond = ClienteClima("http://clima", tentativas=1, sessao=Quebrada()).consultar(-23.5, -46.6)
    assert not cond.disponivel
