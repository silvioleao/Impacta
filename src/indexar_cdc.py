import os
import re
from pypdf import PdfReader
import chromadb

def extrair_trechos_cdc(caminho_pdf: str, tamanho_max: int = 1200, sobreposicao: int = 150):
    print("1. Lendo e limpando o PDF...")
    reader = PdfReader(caminho_pdf)
    linhas_limpas = []

    for pagina in reader.pages:
        texto_extraido = pagina.extract_text()
        if not texto_extraido:
            continue
        for linha in texto_extraido.splitlines():
            linha_s = linha.strip()
            # Remove marcadores típicos de índice/rodapé do PDF
            if not linha_s or "(ÍNDICE)" in linha_s:
                continue
            linhas_limpas.append(linha_s)

    texto_completo = "\n".join(linhas_limpas)

    # Divide pelos artigos (aceita "Art. 49", "Art. 49.", "Art. 49-A", etc.)
    blocos = re.split(r'(?m)^(?=Art\.\s*\d+[º°]?(?:-[A-Z])?\b)', texto_completo)

    chunks = []
    norma_atual = "CDC / Normas Anexas (CDC-2026-site.pdf)"

    for bloco in blocos:
        bloco_s = bloco.strip()
        if not bloco_s:
            continue

        # Detecta mudança de norma quando aparecer "DECRETO" ou "LEI Nº"
        if "DECRETO Nº" in bloco_s.upper() and not bloco_s.startswith("Art."):
            norma_atual = bloco_s.splitlines()[0][:80]
            continue

        if not bloco_s.startswith("Art."):
            continue

        match = re.match(r'^(Art\.\s*\d+[º°]?(?:-[A-Z])?)', bloco_s)
        artigo_id = match.group(1) if match else "Artigo"

        # Se o artigo for muito longo, divide em janelas com sobreposição para não perder contexto
        if len(bloco_s) <= tamanho_max:
            partes = [bloco_s]
        else:
            partes = []
            inicio = 0
            while inicio < len(bloco_s):
                fim = inicio + tamanho_max
                partes.append(bloco_s[inicio:fim])
                if fim >= len(bloco_s):
                    break
                inicio = max(0, fim - sobreposicao)

        for idx_parte, parte in enumerate(partes, start=1):
            chunks.append({
                "texto": parte,
                "artigo": artigo_id,
                "norma": norma_atual,
                "parte": f"{idx_parte}/{len(partes)}",
                "fonte": "CDC-2026-site.pdf (Procon-SP)"
            })

    print(f"Total de trechos indexados: {len(chunks)}")
    return chunks

def criar_banco_vetorial(chunks):
    print("2. Recriando coleção no ChromaDB...")
    raiz_projeto = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    caminho_chroma = os.path.join(raiz_projeto, "chroma_cdc")

    cliente_chroma = chromadb.PersistentClient(path=caminho_chroma)

    try:
        cliente_chroma.delete_collection("cdc_2026")
    except Exception:
        pass

    colecao = cliente_chroma.create_collection(
        name="cdc_2026",
        metadata={"hnsw:space": "cosine"}
    )

    documentos = [c["texto"] for c in chunks]
    metadados = [
        {
            "artigo": c["artigo"],
            "norma": c["norma"],
            "parte": c["parte"],
            "fonte": c["fonte"]
        }
        for c in chunks
    ]
    ids = [f"chunk_{i}" for i in range(len(chunks))]

    # Insere em lotes de 100 para evitar picos de memória
    tamanho_lote = 100
    for i in range(0, len(documentos), tamanho_lote):
        colecao.add(
            documents=documentos[i:i + tamanho_lote],
            metadatas=metadados[i:i + tamanho_lote],
            ids=ids[i:i + tamanho_lote]
        )

    print("Sucesso! Base do CDC reindexada.")

if __name__ == "__main__":
    raiz_projeto = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    caminho_pdf = os.path.join(raiz_projeto, "data", "cdc_2026.pdf")
    trechos = extrair_trechos_cdc(caminho_pdf)
    criar_banco_vetorial(trechos)