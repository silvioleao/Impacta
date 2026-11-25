# Assistente Jurídico de Consulta ao CDC (RAG)

Protótipo desenvolvido para a disciplina **Advanced Generative AI** (MBA em AI-Engineering & Multi-Agents) com foco em apoiar advogados júniores, estagiários e paralegais na consulta e triagem preliminar com base no Código de Defesa do Consumidor (`CDC-2026-site.pdf` — Procon-SP)[cite: 1, 532].

## 1. Como configurar e executar

1. **Crie e ative o ambiente virtual:**
   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # Linux/Mac:
   source .venv/bin/activate
   
Instale as dependências:
pip install google-genai chromadb pypdf pydantic streamlit python-dotenv

Configure a variável de ambiente:
Crie um arquivo .env na raiz do projeto (não versionado via .gitignore) contendo:
GEMINI_API_KEY=sua_chave_aqui

Coloque o PDF do CDC em data/cdc_2026.pdf e indexe no ChromaDB:
python src/indexar_cdc.py

Execute a interface web (Streamlit):
streamlit run app.py

Execute a avaliação em lote (v1, v2, v3):
python -m eval.avaliar_versoes --versoes v1 v2 v3