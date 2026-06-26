"""
worker/worker.py
-----------------
Worker NEXUS-UI - consume tareas de la cola Redis y las procesa.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import redis.asyncio as aioredis
from loguru import logger

sys.path.insert(0, "/app")

from agents.orchestration_agent import OrchestrationAgent, OrchestrationResult
from utils.logger import setup_logging

REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", "")
RESULT_TTL = 300
POLL_TIMEOUT = 2


async def main() -> None:
    setup_logging(
        nivel=os.environ.get("LOG_LEVEL", "INFO"),
        archivo=Path("logs/worker.log") if os.path.isdir("logs") else None,
    )

    logger.info("Worker NEXUS arrancando | redis={}:{}", REDIS_HOST, REDIS_PORT)

    redis: aioredis.Redis | None = None
    try:
        redis = aioredis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=0,
            password=REDIS_PASSWORD or None,
            decode_responses=True,
        )
        await redis.ping()
        logger.info("Worker conectado a Redis")
    except Exception as e:
        logger.critical("Worker: no se pudo conectar a Redis | {}", e)
        sys.exit(1)

    orchestrator = OrchestrationAgent()
    logger.info("Worker listo - esperando tareas...")

    running = True

    try:
        while running:
            try:
                item = await redis.brpop("nexus_tasks", timeout=POLL_TIMEOUT)

                if item is None:
                    continue

                _, task_json = item
                task_data = json.loads(task_json)
                task_id = task_data.get("task_id", "unknown")
                username = task_data.get("username", "unknown")

                logger.info(
                    "Worker procesando | task_id={} | usuario={} | query_len={}",
                    task_id,
                    username,
                    len(task_data.get("user_query", "")),
                )

                result = await _procesar_tarea(orchestrator, task_data, redis)

                result_key = f"nexus_results_{task_id}"
                await redis.lpush(result_key, json.dumps(result))
                await redis.expire(result_key, RESULT_TTL)

                logger.info(
                    "Worker tarea completada | task_id={} | exito={}",
                    task_id,
                    result.get("success", False),
                )

            except asyncio.CancelledError:
                running = False
                break
            except json.JSONDecodeError as e:
                logger.error("Worker: JSON invalido en cola | {}", e)
            except Exception as e:
                logger.exception("Worker: error en el loop | {}", e)
                await asyncio.sleep(1)

    finally:
        await redis.aclose()
        logger.info("Worker detenido limpiamente")


async def _procesar_tarea(
    orchestrator: OrchestrationAgent,
    task_data: dict,
    redis: aioredis.Redis,
) -> dict:
    task_id = task_data.get("task_id", "unknown")
    user_query = task_data.get("user_query", "")
    channel = f"nexus_stream_{task_id}"

    try:
        result: OrchestrationResult = await orchestrator.process(user_query)

        if result.success and result.stream_chunks:
            for chunk in result.stream_chunks:
                await redis.publish(
                    channel,
                    json.dumps({"type": "chunk", "content": chunk}),
                )

        final_payload = {
            "success": result.success,
            "response": result.response,
            "intent": result.intent,
            "routing_trace": result.routing_trace,
            "error": result.error,
        }
        await redis.publish(channel, json.dumps({"type": "done", "content": final_payload}))
        return final_payload
    except Exception as exc:
        error_msg = str(exc)
        logger.exception("Worker: error procesando tarea {}", task_id)
        await redis.publish(channel, json.dumps({"type": "error", "content": error_msg}))
        return {"success": False, "response": "", "intent": None, "routing_trace": [], "error": error_msg}


if __name__ == "__main__":
    asyncio.run(main())
