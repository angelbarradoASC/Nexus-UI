# Baseline Funcional Nexus Desktop

- Fecha: `2026-06-21`
- Rama: `chore/audit-tanda-1-safety`
- Commit SHA: `2d8e085fcac8803974ee82181c54fe77009f1e8f`

## Arranque Desktop

Comando canónico actual:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_open_nexus_desktop.ps1
```

## Comando de Tests

Comando base actual:

```powershell
python -m pytest -q
```

## Rutas Funcionales Conocidas

Rutas de superficie desktop y API confirmadas desde el runtime actual:

- `GET /`
- `GET /health`
- `GET /login`
- `POST /login`
- `GET /logout`
- `GET /open-nexus`
- `GET /open-nexus/models`
- `GET /nexus-v1`
- `GET /nexus-sales`
- `GET /nexus-prompts`
- `GET /nexus/settings`
- `GET /nexus/campaign`
- `GET /nexus/vault`
- `GET /api/desktop/runtime`
- `GET /api/desktop/settings/summary`
- `GET /api/desktop/providers`
- `PUT /api/desktop/providers`
- `GET /api/desktop/operator/integrations`
- `PUT /api/desktop/operator/integrations`
- `POST /api/desktop/operator/integrations/test`
- `DELETE /api/desktop/operator/integrations/{integration_id}`
- `POST /api/desktop/resolve`
- `POST /api/metrics/ingest`
- `POST /api/quick-action`
- `GET /api/nexus/health`
- `POST /api/nexus/chat`
- `GET /api/nexus/outreach/status`
- `GET /api/nexus/outreach/campaigns`
- `GET /api/nexus/outreach/events`
- `POST /api/nexus/outreach/launch`
- `POST /api/nexus/outreach/campaigns/{campaign_id}/run-due`
- `POST /api/nexus/prospecting/interpret`
- `POST /api/nexus/prospecting/run`
- `POST /api/nexus/prospecting/runs/{run_id}/resume`
- `GET /api/nexus/prospecting/runs/{run_id}`
- `GET /api/nexus/prospecting/runs/{run_id}/logs`
- `GET /api/nexus/prospecting/results`
- `GET /api/nexus/prospecting/discarded`
- `POST /api/nexus/prospecting/results/{result_id}/push-to-crm`
- `POST /api/nexus/prospecting/push-valid-to-crm`
- `GET /api/nexus/prompts`
- `GET /api/nexus/prompts/{prompt_key}`
- `PUT /api/nexus/prompts/{prompt_key}`
- `POST /api/nexus/prompts/{prompt_key}/reset`
- `GET /api/nexus/approvals`
- `GET /api/nexus/approvals/pending/count`
- `GET /api/nexus/approvals/{approval_id}`
- `POST /api/nexus/approvals/{approval_id}/approve`
- `POST /api/nexus/approvals/{approval_id}/reject`

## Hashes UI Protegidos

El manifiesto completo SHA-256 por fichero protegido está fijado en:

```text
docs/audit/ui_contract.sha256
```

Ese manifiesto cubre todas las rutas protegidas:

- `app/templates/**`
- `app/static/**`
- `products/desktop/ui/templates/**`
- `products/desktop/ui/static/**`
- `products/web/ui/templates/**`
- `products/web/ui/static/**`

