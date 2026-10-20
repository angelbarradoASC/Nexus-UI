"""Evalua el agente de codigo de PEPO con el conjunto de preguntas de tests/eval.

Corre el agente REAL (el mismo CodeAgent de la app) en proceso, con un modelo de Ollama
configurado en una carpeta temporal: no toca tu configuracion. Mide, por pregunta, si la
respuesta final cita un fichero y una linea correctos, cuantos pasos dio y cuanto tardo.

Uso (desde la raiz del repo, con el venv):
    python scripts/eval_code_agent.py --model qwen3:8b --set fresh
    python scripts/eval_code_agent.py --model qwen3:8b --set fresh --prefetch      # con pre-carga (opt-in)
    python scripts/eval_code_agent.py --model qwen3:8b --set fresh --no-find-code  # ablacion: sin find_code
    python scripts/eval_code_agent.py --retrieval-only                              # solo el buscador, sin LLM

--set: dev | holdout | fresh | all.   --limit N: solo las N primeras.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "app")]

from desktop.code_agent import evaluation as ev  # noqa: E402
from desktop.code_agent.agent import CodeAgent  # noqa: E402
from desktop.code_agent.index import CodeIndex  # noqa: E402
from desktop.code_agent.llm import OllamaToolClient  # noqa: E402
from desktop.code_agent.workspace import Workspace  # noqa: E402
from desktop.storage.code_settings import CodeSettingsStore  # noqa: E402

EVAL_DIR = ROOT / "tests" / "eval"
EXCLUDE = ("tests/eval/",)   # las preguntas contienen su propio texto: no deben poder "contestarse a si mismas"


def load(split: str) -> list[ev.Question]:
    questions = ev.load_questions(EVAL_DIR / "code_questions.json") + ev.load_questions(EVAL_DIR / "code_questions_fresh.json")
    return questions if split == "all" else [q for q in questions if q.split == split]


def retrieval_only(questions: list[ev.Question]) -> None:
    index = CodeIndex(Workspace(ROOT), exclude_prefixes=EXCLUDE)
    index.refresh()
    for k in (5, 8):
        summary = ev.summarize_retrieval(ev.retrieval_report(index, questions, k=k), k=k)
        print(f"recall@{k}:", {name: round(stats[f'recall@{k}'], 2) for name, stats in summary.items() if stats["n"]})


async def run(args: argparse.Namespace) -> None:
    questions = load(args.set)[: args.limit or None]
    workdir = tempfile.mkdtemp(prefix="eval_code_agent_")
    settings = CodeSettingsStore(Path(workdir) / "code_settings.json")
    settings.add_workspace(str(ROOT))
    settings.set_llm(args.url, args.model, args.num_ctx, think=args.think)

    calls = {"n": 0}
    original = OllamaToolClient.call

    async def counting_call(self, messages, **kwargs):
        calls["n"] += 1
        return await original(self, messages, **kwargs)

    OllamaToolClient.call = counting_call
    index = CodeIndex(Workspace(ROOT), exclude_prefixes=EXCLUDE)
    index.refresh()

    rows = []
    for number, question in enumerate(questions, start=1):
        agent = CodeAgent(None, llm_router=None, settings=settings)
        agent.index_exclude_prefixes = EXCLUDE
        agent.prefetch_hits = 8 if args.prefetch else 0
        if args.no_find_code:
            agent.tools = [t for t in agent.tools if t["function"]["name"] != "find_code"]
        # Traza: que herramientas uso el modelo y con que argumentos (para analizar trayectorias, no solo el resultado).
        trace: list[str] = []
        original_dispatch = agent.dispatch_tool

        async def traced(name, args, _orig=original_dispatch, _trace=trace):
            _trace.append(f"{name}({json.dumps(args, ensure_ascii=False)[:140]})")
            return await _orig(name, args)

        agent.dispatch_tool = traced
        calls["n"] = 0
        started = time.time()
        result = await agent.propose(f"eval-{number}", question.question, workspace=str(ROOT))
        elapsed = time.time() - started
        answer = result.get("summary") or result.get("question") or ""
        graded = ev.grade_answer(answer, ev.resolve_symbols(index, question.expect))
        rows.append({
            "id": question.id, "split": question.split, **graded, "steps": calls["n"], "seconds": round(elapsed, 1),
            "answer": answer, "trace": trace,
        })
        print(f"[{number:>2}/{len(questions)}] {graded['grade']:10} {calls['n']} pasos {elapsed:5.0f}s  {question.id}  — {graded['why']}", flush=True)

    total = len(rows) or 1
    correct = sum(1 for r in rows if r["grade"] == "correcta")
    partial = sum(1 for r in rows if r["grade"] == "parcial")
    print(
        f"\nmodelo={args.model} think={args.think} prefetch={'si' if args.prefetch else 'no'} find_code={'no' if args.no_find_code else 'si'} conjunto={args.set}: "
        f"correctas {correct}/{total} ({correct / total:.0%}), parciales {partial}, "
        f"pasos medios {sum(r['steps'] for r in rows) / total:.1f}, tiempo medio {sum(r['seconds'] for r in rows) / total:.0f}s"
    )
    if args.out:
        Path(args.out).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--url", default="http://192.168.68.150:11434")
    parser.add_argument("--num-ctx", type=int, default=8192)
    parser.add_argument("--think", action="store_true", help="activa el razonamiento (mas lento)")
    parser.add_argument("--set", default="fresh", choices=["dev", "holdout", "fresh", "all"])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--prefetch", action="store_true", help="activa la pre-carga de evidencia (por defecto apagada: empeoraba)")
    parser.add_argument("--no-find-code", action="store_true", help="sin la herramienta find_code (ablacion)")
    parser.add_argument("--retrieval-only", action="store_true", help="solo mide el buscador, sin LLM")
    parser.add_argument("--out", help="guarda los resultados en este JSON")
    args = parser.parse_args()
    if args.retrieval_only:
        retrieval_only(load(args.set))
        return
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
