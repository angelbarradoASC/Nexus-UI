# Docker Tanda 1

## Desarrollo

Comando explicito de desarrollo:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

## Produccion

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d
```

## Validacion de sintaxis

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml config
docker compose -f docker-compose.yml -f docker-compose.prod.yml config
```

## Variables obligatorias en produccion

- `APP_ENVIRONMENT=production`
- `SECRET_KEY`
- `CREDENTIAL_STORE_KEY`
- `APP_USERS`
- `MONGO_URI`
- `REDIS_PASSWORD`
- `SESSION_SECURE_COOKIE=true`
- `OUTREACH_SMTP_PASSWORD` y `OUTREACH_IMAP_PASSWORD` cuando `OUTREACH_ENABLED=true`
- `BRAVE_SEARCH_API_KEY` cuando `BRAVE_SEARCH_ENABLED=true`
- `GOOGLE_PLACES_API_KEY` cuando `GOOGLE_PLACES_ENABLED=true`
