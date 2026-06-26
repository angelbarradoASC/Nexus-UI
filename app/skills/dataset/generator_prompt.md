# Prompt para generar ejemplos de entrenamiento con GPT-4 / Claude

Usar este prompt para generar más ejemplos de dataset con un LLM cloud.
El objetivo es llegar a 500-1000 ejemplos antes del primer fine-tuning.

---

## Prompt a usar

```
Eres un generador de datos de entrenamiento para un clasificador de skills de IA.

Tengo los siguientes skills disponibles:

- fichaje.entrada: registrar llegada al trabajo
  Ejemplos reales: "ya he llegado", "buenos días empiezo", "fichar entrada"

- fichaje.salida: registrar salida del trabajo
  Ejemplos reales: "me voy a casa", "hasta mañana", "fin de jornada"

- jira.crear_ticket: crear un ticket/tarea/bug en Jira
  Ejemplos reales: "crea un ticket: el login falla", "abre una incidencia", "nuevo bug"

- jira.consultar_ticket: consultar estado de un ticket existente
  Ejemplos reales: "cómo está NEXUS-42", "estado del ticket PROJ-15"

- ssh.diagnostico: diagnosticar un servidor por SSH
  Ejemplos reales: "revisa el servidor web-01", "cómo está el db-02", "la CPU del servidor api-01 está al 100%"

- web.busqueda: buscar información en internet
  Ejemplos reales: "precio actual del bitcoin", "noticias sobre Python 3.14", "cómo instalar docker"

- general.respuesta: respuesta general del LLM sin herramientas
  Ejemplos reales: "qué es kubernetes", "hola buenos días", "explícame los microservicios"

Para cada skill, genera 30 frases de usuario en español (variadas, naturales, como las diría alguien en el trabajo). Incluye variaciones coloquiales, formales, con errores ortográficos leves, y con contexto adicional irrelevante.

Para cada frase, devuelve una línea JSON en este formato exacto:
{"conversations":[{"role":"system","content":"Eres el router de skills de JAINA. Analiza la consulta del usuario y devuelve SOLO un JSON con: skill_id (string), params (objeto con parámetros extraídos o {}), confidence (0.0-1.0), escalate (true si necesitas un LLM cloud para procesar). Skills disponibles: fichaje.entrada, fichaje.salida, jira.crear_ticket, jira.consultar_ticket, ssh.diagnostico, web.busqueda, general.respuesta"},{"role":"user","content":"FRASE_DEL_USUARIO"},{"role":"assistant","content":"JSON_RESPUESTA"}]}

Para escalate: false si el skill puede ejecutarse sin LLM adicional (fichaje, consultar ticket con ID claro). true si necesita razonamiento cloud (diagnóstico SSH, búsqueda web, respuesta general, crear ticket con descripción compleja).

Genera las 210 líneas (30 por skill × 7 skills).
```

---

## Cuántos ejemplos necesitas

| Fase | Ejemplos | Calidad esperada |
|------|----------|-----------------|
| Arranque (hecho) | 25 | Funcional para pruebas |
| Fine-tuning mínimo | 200-300 | Clasificación decente |
| Fine-tuning bueno | 500-800 | Alta precisión |
| Fine-tuning producción | 1000+ | Robusto a variaciones |

Con el prompt anterior + revisión manual de 30 minutos llegas a 235 ejemplos.
Repitiendo el proceso 3-4 veces con instrucciones de variación llegas a 800+.

---

## Cómo añadir ejemplos reales de producción (fase 2)

Cuando JAINA Desktop esté en uso:
1. Los logs del IntentionAgent guardan (query → skill clasificado → correcto/incorrecto)
2. Un script convierte esos logs al formato JSONL
3. Se filtran los casos con confidence > 0.85 (alta calidad)
4. Se mezclan con los ejemplos sintéticos y se re-entrena

Esto crea un ciclo de mejora continua: cuantos más usuarios, mejor el router.
