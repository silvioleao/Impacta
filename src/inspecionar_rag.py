import os
import chromadb

raiz_projeto = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
cliente = chromadb.PersistentClient(path=os.path.join(raiz_projeto, "chroma_cdc"))
colecao = cliente.get_collection(name="cdc_2026")

print("Total de chunks na coleção:", colecao.count())

# 1. Busca textual direta por "49" ou "arrependimento" ou "defeito"
for termo in ["49", "arrependimento", "defeito", "vício"]:
    res = colecao.get(where_document={"$contains": termo})
    print(f"Chunks contendo '{termo}': {len(res['ids'])}")
    for doc_id, meta, doc in zip(res["ids"][:2], res["metadatas"][:2], res["documents"][:2]):
        trecho_curto = " ".join(doc.split())[:220]
        print(f"   [{doc_id}] {meta} -> {trecho_curto}...")

# 2. Mostra o que a busca vetorial está trazendo para as perguntas de consumidor
perguntas = [
    "Comprei um produto pela internet há 4 dias e me arrependi, posso devolver?",
    "Tenho direito a troca com defeito?"
]

for p in perguntas:
    print("\n" + "=" * 60)
    print("PERGUNTA:", p)
    q = colecao.query(query_texts=[p], n_results=4)
    for rank, (doc, meta, dist) in enumerate(zip(q["documents"][0], q["metadatas"][0], q["distances"][0]), start=1):
        print(f"  Rank {rank} | dist={dist:.4f} | meta={meta}")
        print("   ", " ".join(doc.split())[:240])