import os
import chromadb

raiz_projeto = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
cliente_chroma = chromadb.PersistentClient(path=os.path.join(raiz_projeto, "chroma_cdc"))
colecao = cliente_chroma.get_collection(name="cdc_2026")

print("Total de documentos indexados:", colecao.count())

# Verifica se algum documento menciona 'arrependimento' ou 'Art. 49'
achados = colecao.get(where_document={"$contains": "arrependimento"})
print("Documentos contendo 'arrependimento':", len(achados["ids"]))
for doc_id, meta in zip(achados["ids"], achados["metadatas"]):
    print("  ->", doc_id, meta)

# Testa a busca para a pergunta 1
res = colecao.query(
    query_texts=["Comprei um produto pela internet há 4 dias e me arrependi, posso devolver?"],
    n_results=3
)
print("\nTop 3 trechos recuperados:")
for i, (doc, meta) in enumerate(zip(res["documents"][0], res["metadatas"][0]), start=1):
    print(f"--- Rank {i} | {meta} ---")
    print(doc[:300].replace("\n", " "), "...")