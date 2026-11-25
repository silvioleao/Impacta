import argparse
import json
import os
from src.motor_rag import consultar_cdc


def carregar_casos(caminho_jsonl: str, limite: int | None = None) -> list[dict]:
    casos = []
    with open(caminho_jsonl, "r", encoding="utf-8") as f:
        for linha in f:
            linha_s = linha.strip()
            if linha_s:
                casos.append(json.loads(linha_s))
    return casos[:limite] if limite else casos


def avaliar(versoes: list[str], limite: int | None = None):
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    caminho_casos = os.path.join(raiz, "eval", "casos_de_teste.jsonl")
    caminho_saida = os.path.join(raiz, "eval", "resultados_avaliacao.json")

    casos = carregar_casos(caminho_casos, limite=limite)
    historico = []

    for versao in versoes:
        print("=" * 65)
        print(f"AVALIANDO VERSÃO DE PROMPT: {versao} ({len(casos)} casos)")
        print("=" * 65)

        latencias = []
        for caso in casos:
            res = consultar_cdc(
                pergunta=caso["entrada"],
                versao_prompt=versao
            )
            latencias.append(res["latencia_seg"])

            registro = {
                "versao": versao,
                "id": caso["id"],
                "tipo": caso["tipo"],
                "entrada": caso["entrada"],
                "esperado": caso["esperado"],
                "criterio_eliminatorio": caso["criterio_eliminatorio"],
                "bloqueado": res["bloqueado"],
                "dados_mascarados": res["dados_mascarados"],
                "encontrado_na_base": res["encontrado_na_base"],
                "artigos_citados": res["artigos_citados"],
                "resposta": res["resposta"],
                "latencia_seg": res["latencia_seg"],
            }
            historico.append(registro)

            print(
                f"[{caso['id']}] tipo={caso['tipo']} | "
                f"bloq={res['bloqueado']} | masc={res['dados_mascarados']} | "
                f"base={res['encontrado_na_base']} | lat={res['latencia_seg']}s"
            )

        media_lat = round(sum(latencias) / len(latencias), 2) if latencias else 0.0
        print(f"\nResumo {versao}: {len(latencias)} casos | Latência média = {media_lat}s\n")

    with open(caminho_saida, "w", encoding="utf-8") as out:
        json.dump(historico, out, ensure_ascii=False, indent=2)

    print(f"Resultados salvos em: {caminho_saida}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Avalia versões de prompt do Assistente CDC.")
    parser.add_argument(
        "--versoes",
        nargs="+",
        default=["v3"],
        choices=["v1", "v2", "v3"],
        help="Versões a testar, ex: --versoes v1 v2 v3"
    )
    parser.add_argument(
        "--limite",
        type=int,
        default=None,
        help="Limita a quantidade de casos (útil para economizar cota gratuita da API)"
    )
    args = parser.parse_args()
    avaliar(versoes=args.versoes, limite=args.limite)