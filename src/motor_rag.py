import os
import re
import time
import chromadb
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.errors import APIError

from src.prompts_cdc import RespostaCDC, montar_prompt
from src.seguranca import detectar_injeccao_obvia, mascarar_dados_pessoais

load_dotenv()

_RAIZ_PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CAMINHO_CHROMA = os.path.join(_RAIZ_PROJETO, "chroma_cdc")
_COLECAO_CACHE = None
_CLIENTE_GENAI = None

# Cache simples em memória para evitar chamadas repetidas na demo e economizar cota
_CACHE_RESPOSTAS: dict[tuple, dict] = {}

# Fila de modelos Flash disponíveis na sua conta (cotas independentes no Free Tier)
MODELOS_FALLBACK = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
]


def _obter_colecao():
    global _COLECAO_CACHE
    if _COLECAO_CACHE is None:
        cliente_chroma = chromadb.PersistentClient(path=_CAMINHO_CHROMA)
        _COLECAO_CACHE = cliente_chroma.get_collection(name="cdc_2026")
    return _COLECAO_CACHE


def _obter_cliente_genai():
    global _CLIENTE_GENAI
    if _CLIENTE_GENAI is None:
        # Timeout curto e sem retries longos internos para não travar 90s em caso de 503
        _CLIENTE_GENAI = genai.Client(
            http_options=types.HttpOptions(timeout=20_000)  # 20 segundos máx por tentativa
        )
    return _CLIENTE_GENAI


EXPANSAO_JURIDICA = {
    "arrependi": ["arrependimento", "desistir", "sete dias", "fora do estabelecimento", "art. 49"],
    "desistir": ["desistir", "arrependimento", "sete dias", "art. 49"],
    "internet": ["fora do estabelecimento", "comércio eletrônico", "desistir", "art. 49"],
    "defeito": ["defeito", "vício", "vícios", "qualidade", "art. 12", "art. 14", "art. 18"],
    "troca": ["vício", "vícios", "substituição", "prazo", "art. 18", "art. 26"],
    "cobrança": ["cobrança", "indevida", "engano", "devolução em dobro", "art. 42"],
    "propaganda": ["publicidade", "enganosa", "abusiva", "art. 37"],
}


def _buscar_hibrido_rapido(colecao, pergunta: str, top_k: int = 3, max_chars_trecho: int = 650) -> list[dict]:
    n_candidatos = min(6, colecao.count()) if colecao.count() > 0 else top_k
    res_vetorial = colecao.query(
        query_texts=[pergunta],
        n_results=n_candidatos,
    )

    docs = list(res_vetorial["documents"][0]) if res_vetorial["documents"] else []
    metas = list(res_vetorial["metadatas"][0]) if res_vetorial["metadatas"] else []
    dists = list(res_vetorial["distances"][0]) if res_vetorial["distances"] else []
    ids = list(res_vetorial["ids"][0]) if res_vetorial["ids"] else []

    palavras = set(re.findall(r"\b[a-záàâãéêíóôõúç]{3,}\b", pergunta.lower()))
    termos_busca = set(palavras)
    for p in list(palavras):
        if p in EXPANSAO_JURIDICA:
            termos_busca.update(EXPANSAO_JURIDICA[p])

    termos_resgate = []
    if any(k in palavras for k in ["arrependi", "desistir", "internet"]):
        termos_resgate.append("arrependimento")
    if any(k in palavras for k in ["defeito", "troca", "vício", "vicio"]):
        termos_resgate.append("vícios")

    ids_vistos = set(ids)
    for termo in termos_resgate:
        encontrados = colecao.get(where_document={"$contains": termo})
        for eid, edoc, emeta in zip(encontrados["ids"][:2], encontrados["documents"][:2], encontrados["metadatas"][:2]):
            if eid not in ids_vistos:
                ids_vistos.add(eid)
                ids.append(eid)
                docs.append(edoc)
                metas.append(emeta)
                dists.append(0.35)

    candidatos = []
    for doc, meta, dist in zip(docs, metas, dists):
        doc_lower = doc.lower()
        hits = sum(1 for t in termos_busca if t in doc_lower)
        score = dist - (hits * 0.08)
        candidatos.append({
            "artigo": meta.get("artigo", "Artigo"),
            "norma": meta.get("norma", "CDC"),
            "texto": doc[:max_chars_trecho],
            "score": score,
        })

    candidatos.sort(key=lambda x: x["score"])
    selecionados = candidatos[:top_k]

    return [
        {
            "id": f"D{idx}",
            "artigo": item["artigo"],
            "norma": item["norma"],
            "texto": item["texto"],
        }
        for idx, item in enumerate(selecionados, start=1)
    ]


def _gerar_com_fallback(cliente_genai, modelo_preferido: str, system_inst: str, user_prompt: str):
    """
    Tenta o modelo escolhido primeiro; se houver sobrecarga (503) ou limite de cota (429),
    pula automaticamente para o próximo modelo Flash disponível na conta.
    """
    fila_modelos = [modelo_preferido] + [m for m in MODELOS_FALLBACK if m != modelo_preferido]
    ultimo_erro = None

    for mod in fila_modelos:
        if "2.5" in mod:
            cfg = types.GenerateContentConfig(
                system_instruction=system_inst,
                temperature=0.2,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
                response_mime_type="application/json",
                response_schema=RespostaCDC,
            )
        else:
            cfg = types.GenerateContentConfig(
                system_instruction=system_inst,
                temperature=1.0,
                thinking_config=types.ThinkingConfig(thinking_level="low"),
                response_mime_type="application/json",
                response_schema=RespostaCDC,
            )

        try:
            resp = cliente_genai.models.generate_content(
                model=mod,
                contents=user_prompt,
                config=cfg,
            )
            if resp and resp.parsed:
                return resp.parsed, mod
        except APIError as e:
            ultimo_erro = e
            continue
        except Exception as e:
            ultimo_erro = e
            continue

    raise RuntimeError(f"Todos os modelos falharam. Último erro: {ultimo_erro}")

def consultar_cdc(
    pergunta: str,
    versao_prompt: str = "v3",
    modelo: str = "gemini-3.8-flash",
    top_k: int = 3,
    usar_cache: bool = True,
) -> dict:
    inicio = time.time()

    # 1. Guardrail de entrada
    if detectar_injeccao_obvia(pergunta):
        return {
            "bloqueado": True,
            "motivo_bloqueio": "Tentativa de prompt injection ou acesso a instruções internas detectada.",
            "encontrado_na_base": False,
            "artigos_citados": [],
            "resposta": "Solicitação bloqueada por diretrizes de segurança. Consulte apenas dúvidas sobre o CDC.",
            "trechos_recuperados": [],
            "dados_mascarados": [],
            "modelo_utilizado": "guardrail-local",
            "latencia_seg": round(time.time() - inicio, 2),
        }

    # 2. Guardrail LGPD
    pergunta_limpa, dados_mascarados = mascarar_dados_pessoais(pergunta)

    # Verifica cache antes de chamar busca/LLM
    chave_cache = (pergunta_limpa.strip().lower(), versao_prompt, modelo, top_k)
    if usar_cache and chave_cache in _CACHE_RESPOSTAS:
        cached = dict(_CACHE_RESPOSTAS[chave_cache])
        cached["dados_mascarados"] = dados_mascarados
        cached["latencia_seg"] = round(time.time() - inicio, 3)
        cached["modelo_utilizado"] = f"{cached['modelo_utilizado']} (cache)"
        return cached

    # 3. Busca híbrida rápida no ChromaDB
    colecao = _obter_colecao()
    trechos_recuperados = _buscar_hibrido_rapido(colecao, pergunta_limpa, top_k=top_k)

    blocos_texto = [
        f'<documento id="{t["id"]}" artigo="{t["artigo"]}" norma="{t["norma"]}">\n{t["texto"]}\n</documento>'
        for t in trechos_recuperados
    ]
    trechos_formatados = "\n".join(blocos_texto)

    # 4. Monta o prompt na versão escolhida (v1, v2 ou v3)
    system_inst, user_prompt = montar_prompt(versao_prompt, trechos_formatados, pergunta_limpa)

    # 5. Chama o Gemini com fallback automático entre modelos
    cliente_genai = _obter_cliente_genai()
    try:
        parsed, modelo_usado = _gerar_com_fallback(cliente_genai, modelo, system_inst, user_prompt)
    except Exception as erro:
        return {
            "bloqueado": False,
            "motivo_bloqueio": None,
            "encontrado_na_base": False,
            "artigos_citados": [],
            "resposta": f"Não foi possível obter resposta dos modelos no momento ({erro}).",
            "trechos_recuperados": trechos_recuperados,
            "dados_mascarados": dados_mascarados,
            "modelo_utilizado": "indisponível",
            "latencia_seg": round(time.time() - inicio, 2),
        }

    # 6. Guardrail de saída
    texto_final = parsed.analise_juridica
    artigos_final = parsed.artigos_citados
    if not parsed.encontrado_na_base:
        texto_final = "Não encontrado na base do CDC"
        artigos_final = []

    resultado = {
        "bloqueado": False,
        "motivo_bloqueio": None,
        "encontrado_na_base": parsed.encontrado_na_base,
        "artigos_citados": artigos_final,
        "resposta": texto_final,
        "trechos_recuperados": trechos_recuperados,
        "dados_mascarados": dados_mascarados,
        "modelo_utilizado": modelo_usado,
        "latencia_seg": round(time.time() - inicio, 2),
    }

    if usar_cache:
        _CACHE_RESPOSTAS[chave_cache] = dict(resultado)

    return resultado