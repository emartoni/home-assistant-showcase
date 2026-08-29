import sys

# Módulos Python nativos auxiliares do Pyscript.
# Mantidos fora de /config/pyscript para que o Pyscript não os interprete,
# garantindo que sejam "regular python functions" compatíveis com task.executor.
if "/config/pyscript_modules" not in sys.path:
    sys.path.append("/config/pyscript_modules")

import importlib
if "anp_helper" in sys.modules:
    importlib.reload(sys.modules["anp_helper"])

import anp_helper
from anp_helper import baixar_zip, extrair_zip, encontrar_csv, coletar_precos_gasolina, salvar_json
from datetime import datetime

# ─────────────────────────────────────────────
# Configurações — ajuste aqui se necessário
# ─────────────────────────────────────────────

# Cidade e estado para filtrar no CSV da ANP
CIDADE = "ARARAS"
ESTADO = "SP"

# Caminho onde o JSON com os resultados será salvo
OUTPUT_FILE = "/config/pyscript/anp_preco.json"

# Caminhos temporários para download e extração do ZIP
TMP_ZIP = "/tmp/anp_combustiveis.zip"
TMP_DIR = "/tmp/anp_combustiveis/"

# ─────────────────────────────────────────────
def get_urls():
    """
    Gera uma lista de URLs candidatas da ANP em ordem decrescente de data.
    A ANP publica arquivos semestrais no formato:
      ca-AAAA-SS.zip  (SS = 01 para 1º semestre, 02 para 2º semestre)

    Tenta os últimos 4 semestres para cobrir casos onde o semestre atual
    ainda não foi publicado (como acontece com ca-2026-01.zip).
    """
    now = datetime.now()
    ano = now.year
    semestre = 1 if now.month <= 6 else 2
    candidates = []
    for i in range(4):
        candidates.append(
            f"https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/arquivos/shpc/dsas/ca/ca-{ano}-{str(semestre).zfill(2)}.zip"
        )
        if semestre == 1:
            semestre = 2
            ano -= 1
        else:
            semestre = 1
    return candidates

@service
async def atualizar_preco_gasolina():
    """
    Serviço principal. Pode ser chamado manualmente via:
      Ferramentas de Desenvolvedor → Ações → pyscript.atualizar_preco_gasolina

    Fluxo:
      1. Tenta baixar o ZIP mais recente da ANP (testa até 4 semestres).
      2. Extrai o ZIP e localiza o CSV dentro dele.
      3. Lê o CSV filtrando por CIDADE/ESTADO e coleta preços de gasolina.
      4. Calcula média, mínimo e máximo dos preços.
      5. Salva o resultado em JSON e atualiza os sensores do HA.

    Importante: todas as operações de arquivo (I/O) são executadas via
    task.executor para não bloquear o event loop do Home Assistant.
    """
    log.info("ANP: início da atualização.")

    urls = get_urls()
    log.info(f"ANP: URLs candidatas = {urls}")

    baixado = False
    url_sucesso = None

    for url in urls:
        try:
            log.info(f"ANP: tentando baixar {url}")
            await task.executor(baixar_zip, url, TMP_ZIP)
            baixado = True
            url_sucesso = url
            log.info(f"ANP: arquivo baixado com sucesso: {url}")
            break
        except Exception as e:
            log.warning(f"ANP: falhou ao baixar {url}: {e}")
            continue

    if not baixado:
        log.error("ANP: nenhum arquivo encontrado (todas URLs falharam).")
        return

    log.info("ANP: extraindo ZIP...")
    await task.executor(extrair_zip, TMP_ZIP, TMP_DIR)
    log.info("ANP: ZIP extraído.")

    csv_file = await task.executor(encontrar_csv, TMP_DIR)
    log.info(f"ANP: CSV encontrado = {csv_file}")

    if not csv_file:
        log.error("ANP: CSV não encontrado dentro do ZIP.")
        return

    log.info(f"ANP: coletando dados para {CIDADE}/{ESTADO}...")
    dados = await task.executor(coletar_precos_gasolina, csv_file, CIDADE, ESTADO)

    log.info(f"ANP: municípios SP com 'ARAR' = {dados['araras_like']}")
    log.info(f"ANP: cidade encontrada = {dados['encontrou_cidade']}")
    log.info(f"ANP: produtos disponíveis = {dados['produtos']}")
    log.info(f"ANP: registros de gasolina = {len(dados['precos'])}")

    if not dados["encontrou_cidade"]:
        log.error(f"ANP: {CIDADE}/{ESTADO} não encontrada no CSV.")
        return

    if not dados["precos"]:
        log.error(f"ANP: nenhum preço de gasolina encontrado para {CIDADE}/{ESTADO}.")
        return

    precos = dados["precos"]
    media = round(sum(precos) / len(precos), 3)
    minimo = round(min(precos), 3)
    maximo = round(max(precos), 3)

    resultado = {
        "preco_medio": media,
        "preco_minimo": minimo,
        "preco_maximo": maximo,
        "amostras": len(precos),
        "cidade": CIDADE,
        "estado": ESTADO,
        "atualizado_em": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "arquivo": url_sucesso,
    }

    await task.executor(salvar_json, OUTPUT_FILE, resultado)
    log.info(f"ANP: JSON salvo em {OUTPUT_FILE}")

    # Removidas as linhas que setavam os sensores diretamente:
    # sensor.preco_gasolina_medio = media
    # sensor.preco_gasolina_minimo = minimo
    # sensor.preco_gasolina_maximo = maximo

    log.info(f"ANP: concluído. Média R$ {media}/L ({len(precos)} postos em {CIDADE}/{ESTADO})")

    # Força o sensor a reler o JSON imediatamente após salvar
    await hass.services.async_call(
        "homeassistant", "update_entity",
        {"entity_id": "sensor.gasolina_media_araras_anp"}
    )

@time_trigger("cron(0 6 * * 1)")
async def atualizar_automatico():
    """
    Executa a atualização automaticamente toda segunda-feira às 06:00.
    A ANP publica dados semanalmente, então segunda é um bom momento
    para garantir que os dados mais recentes estão disponíveis.
    """
    await atualizar_preco_gasolina()