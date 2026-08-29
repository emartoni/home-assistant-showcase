import urllib.request
import zipfile
import csv
import os
import json

def baixar_zip(url, tmp_zip):
    """
    Faz o download do arquivo ZIP da ANP para um caminho temporário.
    Usa urllib para não precisar de dependências externas.
    """
    urllib.request.urlretrieve(url, tmp_zip)

def extrair_zip(tmp_zip, tmp_dir):
    """
    Extrai o conteúdo do ZIP baixado para um diretório temporário.
    Cria o diretório se não existir.
    """
    os.makedirs(tmp_dir, exist_ok=True)
    with zipfile.ZipFile(tmp_zip, 'r') as z:
        z.extractall(tmp_dir)

def encontrar_csv(tmp_dir):
    """
    Procura o primeiro arquivo .csv dentro do diretório extraído.
    Retorna o caminho completo do CSV ou None se não encontrar.
    """
    for f in os.listdir(tmp_dir):
        if f.endswith(".csv"):
            return os.path.join(tmp_dir, f)
    return None

def coletar_precos_gasolina(csv_file, cidade, estado):
    """
    Lê o CSV da ANP e coleta:
      - Todos os municípios do estado que contêm 'ARAR' (para diagnóstico do nome exato).
      - Todos os produtos disponíveis na cidade/estado filtrada.
      - Todos os preços de venda de produtos com 'GASOLINA' no nome.

    O CSV usa ponto e vírgula como separador e codificação utf-8-sig (BOM).

    Colunas relevantes do CSV da ANP:
      - "Estado - Sigla"  → UF (ex: SP)
      - "Municipio"       → Nome da cidade em maiúsculas (ex: ARARAS)
      - "Produto"         → Nome do combustível (ex: GASOLINA COMUM)
      - "Valor de Venda"  → Preço com vírgula decimal (ex: 6,29)

    Retorna um dicionário com:
      - encontrou_cidade: bool indicando se a cidade foi achada no CSV
      - produtos: lista de produtos disponíveis na cidade/estado
      - precos: lista de floats com os preços de gasolina encontrados
      - araras_like: lista de municípios do estado que contêm 'ARAR' (diagnóstico)
    """
    produtos = set()
    encontrou_cidade = False
    precos = []
    municipios_estado = set()

    with open(csv_file, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            municipio = row.get("Municipio", "").strip().upper()
            uf = row.get("Estado - Sigla", "").strip().upper()
            produto = row.get("Produto", "").strip()
            preco_raw = row.get("Valor de Venda", "").strip().replace(",", ".")

            if uf == estado:
                municipios_estado.add(municipio)

            if municipio == cidade and uf == estado:
                encontrou_cidade = True
                produtos.add(produto)

                if "GASOLINA" in produto.upper():
                    try:
                        precos.append(float(preco_raw))
                    except ValueError:
                        continue

    araras_like = [m for m in municipios_estado if "ARAR" in m]

    return {
        "encontrou_cidade": encontrou_cidade,
        "produtos": list(produtos),
        "precos": precos,
        "araras_like": araras_like,
    }

def salvar_json(output_file, resultado):
    """
    Salva o dicionário de resultado como JSON no caminho indicado.

    Usa escrita atômica para garantir que o JSON existente NUNCA seja
    corrompido ou perdido em caso de falha durante a escrita:
      1. Escreve em um arquivo temporário (.tmp) primeiro.
      2. Só substitui o arquivo original se a escrita for bem-sucedida.
      3. Em caso de erro, o arquivo temporário é removido e o original
         permanece intacto com os dados do último ciclo bem-sucedido.

    Isso garante resiliência: se o pyscript falhar na próxima execução,
    o sensor continua lendo o último JSON válido salvo.
    """
    tmp_file = output_file + ".tmp"

    try:
        # Passo 1: escreve no arquivo temporário
        with open(tmp_file, "w") as f:
            json.dump(resultado, f, ensure_ascii=False, indent=2)

        # Passo 2: só substitui o original se a escrita foi bem-sucedida
        os.replace(tmp_file, output_file)

    except Exception as e:
        # Passo 3: remove o .tmp corrompido sem tocar no original
        if os.path.exists(tmp_file):
            os.remove(tmp_file)
        raise e  # re-lança para o pyscript logar o erro corretamente

def ler_json(output_file):
    """
    Lê o JSON existente e retorna o dicionário.
    Retorna None se o arquivo não existir ou estiver corrompido.

    Útil para o pyscript verificar o último estado salvo antes de
    iniciar um novo ciclo de download, ou para fallback em caso de erro.
    """
    if not os.path.exists(output_file):
        return None
    try:
        with open(output_file, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None