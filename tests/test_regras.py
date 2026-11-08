"""Regras de negócio puras: prioridade, classificação do LDR, LGPD e deduplicação."""
import pytest
from PIL import Image

from conftest import P1
from rua_acesa_rpa import lgpd
from rua_acesa_rpa.clima import CondicaoClima
from rua_acesa_rpa.deduplicacao import solicitacao_aberta_para
from rua_acesa_rpa.modelos import Evidencia
from rua_acesa_rpa.prioridade import calcular, classificar_luminosidade, faixa_de
from rua_acesa_rpa.repositorio import Repositorio

CHUVA = CondicaoClima(disponivel=True, chuva_noturna=True, precipitacao_noturna_mm=3.0,
                      nebulosidade_noturna_pct=95.0, horas_noturnas=12)
SECO = CondicaoClima(disponivel=True, chuva_noturna=False, nebulosidade_noturna_pct=20.0, horas_noturnas=12)
FORA = CondicaoClima(disponivel=False, detalhe="Open-Meteo indisponível")


# ---------------------------------------------------------------- prioridade
def test_confirmada_simples_e_baixa():
    p = calcular(Evidencia.CONFIRMADA, 1, False, SECO, 0)
    assert (p.score, p.faixa) == (40, "baixa")


def test_noite_chuvosa_e_encoberta_sobe_para_media():
    p = calcular(Evidencia.CONFIRMADA, 1, False, CHUVA, 0)
    assert (p.score, p.faixa) == (65, "media")
    assert any("chuva" in m for m in p.motivos) and any("encoberto" in m for m in p.motivos)


def test_varios_relatos_e_robo_levam_a_alta():
    p = calcular(Evidencia.CONFIRMADA, 3, True, CHUVA, 0)
    assert p.score == 40 + 12 + 15 + 10 + 15 and p.faixa == "alta"


def test_relatos_extras_e_dias_tem_teto_e_score_max_100():
    p = calcular(Evidencia.CONFIRMADA, 50, True, CHUVA, 365)
    assert p.score == 100
    assert any("+30" in m for m in p.motivos) and any("+10" in m and "dia" in m for m in p.motivos)


def test_sensor_nao_conta_corroboracao_duas_vezes():
    assert calcular(Evidencia.SENSOR, 0, True, SECO, 0).score == 25


def test_clima_indisponivel_e_ignorado_e_explicado():
    p = calcular(Evidencia.INCONCLUSIVA, 1, False, FORA, 0)
    assert p.score == 20 and "clima indisponível" in p.motivos[-1]


@pytest.mark.parametrize("score, faixa", [(44, "baixa"), (45, "media"), (69, "media"), (70, "alta")])
def test_limites_das_faixas(score, faixa):
    assert faixa_de(score) == faixa


@pytest.mark.parametrize("lux, esperado", [(0, "escuro"), (4.9, "escuro"), (5, "fraco"), (14.9, "fraco"),
                                           (15, "adequado"), (300, "adequado")])
def test_classificacao_do_ldr(lux, esperado):
    assert classificar_luminosidade(lux, 5, 15) == esperado


# ---------------------------------------------------------------- LGPD
def test_hash_do_contato_e_estavel_normalizado_e_depende_do_salt():
    h1 = lgpd.hash_contato("Maria@Example.com ", "s1")
    assert h1 == lgpd.hash_contato("maria@example.com", "s1")
    assert h1 != lgpd.hash_contato("maria@example.com", "s2")
    assert lgpd.hash_contato("(11) 91234-5678", "s1") == lgpd.hash_contato("11912345678", "s1")
    assert "maria" not in h1


def test_mascaras():
    assert lgpd.mascarar_contato("maria@example.com") == "m***@example.com"
    assert lgpd.mascarar_contato("+55 11 91234-5678") == "***78"


def test_sanitizar_remove_email_e_telefone_de_logs():
    s = lgpd.sanitizar("contato maria@example.com ou (11) 91234-5678 no relato R-1001")
    assert "maria@" not in s and "91234" not in s and "R-1001" in s


def test_foto_regravada_sem_exif(tmp_path):
    origem, destino = tmp_path / "com_gps.jpg", tmp_path / "limpa.jpg"
    img = Image.new("RGB", (32, 32), (10, 20, 30))
    exif = Image.Exif()
    exif[0x010F] = "CelularDoCidadao"          # Make
    exif[0x8825] = {2: (23.0, 33.0, 40.0)}     # GPSInfo
    img.save(origem, "JPEG", exif=exif)
    assert Image.open(origem).getexif()
    lgpd.gravar_foto_sem_metadados(origem, destino)
    assert not Image.open(destino).getexif()


# ---------------------------------------------------------------- deduplicação sem poste
def test_dedup_por_distancia_quando_nao_ha_poste(tmp_path):
    repo = Repositorio(tmp_path / "t.db")
    sid = repo.inserir_solicitacao({"latitude": P1[0], "longitude": P1[1], "status": "aguardando_revisao",
                                    "evidencia": "confirmada"})
    perto = solicitacao_aberta_para(repo, None, P1[0] + 10 / 111_320, P1[1], raio_dedup_m=30)
    longe = solicitacao_aberta_para(repo, None, P1[0] + 80 / 111_320, P1[1], raio_dedup_m=30)
    assert perto["id"] == sid and longe is None
    repo.atualizar_solicitacao(sid, status="resolvida")
    assert solicitacao_aberta_para(repo, None, P1[0], P1[1], raio_dedup_m=30) is None  # só abertas agrupam
