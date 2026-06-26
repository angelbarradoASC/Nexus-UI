# Open-Nexus Desktop Product

Este directorio es la fuente de verdad de Nexus Desktop.

Arbol canónico:
- `products/desktop/backend/app.py`: backend FastAPI real del desktop
- `products/desktop/bootstrap.py`: registro de routers y static del producto
- `products/desktop/routes/ui.py`: rutas HTML del desktop
- `products/desktop/ui/templates/*`: vistas del desktop
- `products/desktop/ui/static/*`: assets del desktop

Reglas:
- cuando digamos `Nexus`, hablamos de este producto desktop
- cualquier cambio visual o de runtime del desktop se hace aqui
- `desktop/backend/app.py` es solo un shim de compatibilidad
- la web legacy no debe volver a ser la fuente de verdad del desktop
