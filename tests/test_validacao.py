"""Etapa 1 — validação: cada problema de entrada vira uma mensagem clara (nunca uma falha silenciosa)."""
from datetime import timedelta

import pytest

from conftest import criar_relato, foto_unica
from rua_acesa_rpa.repositorio import agora
from rua_acesa_rpa.validacao import RelatoInvalido, validar_relato

KW = {"max_foto_mb": 10, "max_idade_dias": 30}


def test_relato_de_cidadao_valido(cfg):
    v = validar_relato(criar_relato(cfg, "R1"), **KW)
    assert v.relato.id == "R1" and v.foto.name == "R1.jpg"


def test_relato_do_robo_valido_sem_foto(cfg):
    v = validar_relato(criar_relato(cfg, "R2", origem="robo", lux=3.0), **KW)
    assert v.foto is None and v.relato.leitura.luminosidade_lux == 3.0


@pytest.mark.parametrize("conteudo, trecho", [
    ('{"id": "R3", "origem": ', "JSON inválido"),
    ("", "arquivo vazio"),
    ("[1, 2]", "objeto"),
])
def test_json_malformado(cfg, conteudo, trecho):
    arq = cfg.pasta_entrada / "R3.json"
    arq.write_text(conteudo, encoding="utf-8")
    with pytest.raises(RelatoInvalido, match=trecho):
        validar_relato(arq, **KW)


def test_cidadao_sem_foto(cfg):
    with pytest.raises(RelatoInvalido, match="exige foto"):
        validar_relato(criar_relato(cfg, "R4", foto=False), **KW)


def test_robo_sem_leitura(cfg):
    arq = criar_relato(cfg, "R5", origem="robo")
    arq.write_text(arq.read_text().replace('"leitura"', '"outra_coisa"'))
    with pytest.raises(RelatoInvalido, match="campos inválidos"):
        validar_relato(arq, **KW)


def test_foto_ausente(cfg):
    arq = criar_relato(cfg, "R6")
    (cfg.pasta_entrada / "R6.jpg").unlink()
    with pytest.raises(RelatoInvalido, match="não encontrada"):
        validar_relato(arq, **KW)


def test_foto_corrompida(cfg):
    arq = criar_relato(cfg, "R7")
    (cfg.pasta_entrada / "R7.jpg").write_bytes(b"isto nao e uma imagem")
    with pytest.raises(RelatoInvalido, match="corrompida"):
        validar_relato(arq, **KW)


def test_foto_grande_demais(cfg):
    with pytest.raises(RelatoInvalido, match="excede o limite"):
        validar_relato(criar_relato(cfg, "R8"), max_foto_mb=0.0001, max_idade_dias=30)


def test_foto_com_caminho_e_bloqueada(cfg):
    foto_unica(cfg.raiz / "segredo.jpg")
    arq = criar_relato(cfg, "R9")
    arq.write_text(arq.read_text().replace('"R9.jpg"', '"../segredo.jpg"'))
    with pytest.raises(RelatoInvalido, match="sem caminho"):
        validar_relato(arq, **KW)


def test_coordenada_fora_de_sp(cfg):
    with pytest.raises(RelatoInvalido, match="fora do município"):
        validar_relato(criar_relato(cfg, "R10", pos=(-22.9068, -43.1729)), **KW)


def test_data_no_futuro(cfg):
    with pytest.raises(RelatoInvalido, match="futuro"):
        validar_relato(criar_relato(cfg, "R11", minutos=-60), **KW)


def test_relato_antigo_demais(cfg):
    arq = criar_relato(cfg, "R12", criado_em=(agora() - timedelta(days=45)).isoformat())
    with pytest.raises(RelatoInvalido, match="mais de 30 dias"):
        validar_relato(arq, **KW)


def test_leitura_impossivel_do_ldr(cfg):
    with pytest.raises(RelatoInvalido, match="luminosidade_lux"):
        validar_relato(criar_relato(cfg, "R13", origem="robo", lux=-4), **KW)


def test_campo_desconhecido_e_rejeitado(cfg):
    with pytest.raises(RelatoInvalido, match="cpf"):
        validar_relato(criar_relato(cfg, "R14", cpf="000.000.000-00"), **KW)
