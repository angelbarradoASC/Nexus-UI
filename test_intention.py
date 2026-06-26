# test_intention.py
import asyncio
import sys
import os

# IMPORTANTE: Configurar URL para localhost ANTES de importar
os.environ["LLM_API_BASE_URL"] = "http://localhost:1234/v1"

# Añadir app al path
sys.path.insert(0, './app')

from agents.intention_agent import IntentionAgent

async def test_intentions():
    """Prueba el IntentionAgent con varias consultas"""
    
    agent = IntentionAgent()
    
    test_queries = [
        "diagnostica el servidor WEB-01-PRO",
        "el web-02 está con la CPU al 100%",
        "crea un ticket para el problema de memoria",
        "hola, ¿cómo estás?",
        "revisa el servidor de base de datos que va lento",
        "el linux de producción tiene problemas",
    ]
    
    print("=" * 60)
    print("PRUEBAS DEL INTENTION AGENT")
    print("=" * 60)
    
    for query in test_queries:
        print(f"\n📝 Consulta: '{query}'")
        result = await agent.classify(query)
        
        print(f"   ✓ Intención: {result['intention']}")
        print(f"   ✓ Entidades: {result['entities']}")
        print(f"   ✓ Confianza: {result['confidence']}")
        if result['follow_up_question']:
            print(f"   ⚠️  Pregunta: {result['follow_up_question']}")
        print("-" * 60)

if __name__ == "__main__":
    asyncio.run(test_intentions())