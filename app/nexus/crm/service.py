"""Bridge between Nexus outreach campaigns and the Assets internal CRM."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from nexus.connectors.crm import AssetsCRMConnector
from nexus.outreach.repository import OutreachRepository


class CRMBridgeService:
    """Expose CRM status and sync outreach prospects into Assets CRM."""

    INTERNAL_DOMAINS = {
        "assetsconsultores.es",
        "sls.assetsconsultores.es",
    }

    def __init__(self, *, cfg, repository: OutreachRepository | None = None, connector: AssetsCRMConnector | None = None) -> None:
        self._cfg = cfg
        self._repository = repository or OutreachRepository(cfg.outreach_data_dir)
        self._connector = connector or AssetsCRMConnector(
            base_url=cfg.assets_crm_base_url,
            username=cfg.assets_crm_username,
            password=cfg.assets_crm_password,
        )

    async def status(self) -> dict[str, Any]:
        connector_status = await self._connector.status()
        campaigns = await self._repository.load_campaigns()
        recent_campaigns = list(reversed(campaigns[-5:]))
        pending_prospects = sum(
            1
            for campaign in campaigns
            for prospect in campaign.get("prospects", [])
            if prospect.get("email") and not prospect.get("crm_sync")
        )
        return {
            "status": "success",
            "provider": "assets-web-api",
            "discovered_source": r"C:\DEV\GitHub\assets-web-api",
            "connector": connector_status,
            "campaigns_total": len(campaigns),
            "pending_prospects": pending_prospects,
            "recent_campaigns": recent_campaigns,
        }

    async def sync_campaign(self, campaign_id: str, *, limit: int = 3, dry_run: bool = True) -> dict[str, Any]:
        campaigns = await self._repository.load_campaigns()
        campaign = next((item for item in campaigns if item.get("campaign_id") == campaign_id), None)
        if campaign is None:
            return {"status": "not_found", "campaign_id": campaign_id}

        prospects = [prospect for prospect in campaign.get("prospects", []) if prospect.get("email")]
        prospects = [prospect for prospect in prospects if not prospect.get("crm_sync")]
        prospects = prospects[: max(1, int(limit))]
        if not prospects:
            return {
                "status": "noop",
                "campaign_id": campaign_id,
                "dry_run": dry_run,
                "synced_count": 0,
                "results": [],
            }

        results: list[dict[str, Any]] = []
        for prospect in prospects:
            lead_payload = self._build_lead_payload(campaign, prospect)
            if dry_run:
                result = {
                    "status": "preview",
                    "provider": "assets-web-api",
                    "company_payload": lead_payload["company_payload"],
                    "pipeline_payload": lead_payload["pipeline_payload"],
                    "note_payload": lead_payload["note_payload"],
                    "prospect_id": prospect.get("prospect_id"),
                    "email": prospect.get("email"),
                }
            else:
                existing_company = await self._connector.find_company_by_domain(lead_payload["company_payload"]["domain"])
                if existing_company is None:
                    created = await self._connector.create_company(lead_payload["company_payload"])
                    company = created.get("company", {})
                else:
                    company = existing_company
                company_id = company.get("id")
                if company_id:
                    await self._connector.update_company_pipeline(company_id, lead_payload["pipeline_payload"])
                    await self._connector.add_pipeline_note(company_id, lead_payload["note_payload"])
                result = {
                    "status": "created",
                    "provider": "assets-web-api",
                    "company_id": company_id,
                    "company_name": company.get("name"),
                    "domain": company.get("domain"),
                    "reused": existing_company is not None,
                    "prospect_id": prospect.get("prospect_id"),
                    "email": prospect.get("email"),
                }
            prospect["crm_sync"] = {
                "provider": "assets-web-api",
                "status": result["status"],
                "synced_at": datetime.now(timezone.utc).isoformat(),
                "company_id": result.get("company_id"),
                "dry_run": dry_run,
            }
            results.append(result)

        campaign["updated_at"] = datetime.now(timezone.utc).isoformat()
        await self._repository.save_campaigns(campaigns)
        return {
            "status": "accepted",
            "campaign_id": campaign_id,
            "dry_run": dry_run,
            "synced_count": len(results),
            "results": results,
        }

    async def ingest_inbound_mail(
        self,
        message: dict[str, Any],
        *,
        dry_run: bool = True,
        create_company_if_missing: bool = True,
    ) -> dict[str, Any]:
        sender_email = str((message or {}).get("sender_email") or message.get("from", {}).get("email", "")).strip().lower()
        if "@" not in sender_email:
            return {"status": "invalid", "reason": "sender_email_missing"}

        domain = sender_email.split("@", 1)[1]
        if domain in self.INTERNAL_DOMAINS:
            return {
                "status": "ignored",
                "reason": "internal_sender",
                "sender_email": sender_email,
                "domain": domain,
            }

        existing_company = await self._connector.find_company_by_domain(domain)
        payloads = self._build_mail_payloads(message, domain=domain)
        stage = payloads["pipeline_payload"]["pipeline_stage"]

        if dry_run:
            return {
                "status": "preview",
                "domain": domain,
                "sender_email": sender_email,
                "matched_company": existing_company,
                "create_company_if_missing": create_company_if_missing,
                "company_payload": payloads["company_payload"],
                "pipeline_payload": payloads["pipeline_payload"],
                "note_payload": payloads["note_payload"],
                "proposed_stage": stage,
            }

        company = existing_company
        created = False
        if company is None and create_company_if_missing:
            created_response = await self._connector.create_company(payloads["company_payload"])
            company = created_response.get("company", {})
            created = True

        if not company:
            return {
                "status": "unmatched",
                "domain": domain,
                "sender_email": sender_email,
                "reason": "company_not_found",
            }

        company_id = company.get("id")
        if not company_id:
            return {
                "status": "error",
                "domain": domain,
                "sender_email": sender_email,
                "reason": "company_id_missing",
            }

        await self._connector.update_company_pipeline(company_id, payloads["pipeline_payload"])
        await self._connector.add_pipeline_note(company_id, payloads["note_payload"])

        return {
            "status": "accepted",
            "domain": domain,
            "sender_email": sender_email,
            "company_id": company_id,
            "company_name": company.get("name") or payloads["company_payload"]["name"],
            "created_company": created,
            "proposed_stage": stage,
        }

    def _build_lead_payload(self, campaign: dict[str, Any], prospect: dict[str, Any]) -> dict[str, Any]:
        company_name = prospect.get("company") or prospect.get("company_domain") or prospect.get("email")
        domain = (prospect.get("company_domain") or prospect.get("email", "").split("@")[-1]).lower()
        description_lines = [
            f"Campaña: {campaign.get('campaign_name', '')}",
            f"Propuesta: {campaign.get('proposition', '')}",
            f"CTA: {campaign.get('cta', '')}",
        ]
        if prospect.get("notes"):
            description_lines.append(f"Notas prospecto: {prospect['notes']}")
        company_payload: dict[str, Any] = {
            "name": company_name,
            "domain": domain,
            "status": "prospect",
            "notes": "\n".join(line for line in description_lines if line.strip()),
            "lead_source": "cold",
        }
        pipeline_payload: dict[str, Any] = {
            "pipeline_stage": "new",
            "contact_name": prospect.get("first_name") or prospect.get("email"),
            "contact_email": prospect.get("email"),
            "contact_phone": "",
            "lead_source": "cold",
            "next_followup": (date.today() + timedelta(days=4)).isoformat(),
            "estimated_value": None,
        }
        note_payload: dict[str, Any] = {
            "note_type": "note",
            "content": (
                f"Lead importado por Nexus desde outreach.\n"
                f"Campaña: {campaign.get('campaign_name', '')}\n"
                f"Propuesta: {campaign.get('proposition', '')}\n"
                f"Contacto: {prospect.get('first_name') or ''} <{prospect.get('email')}>"
            ).strip(),
            "next_followup": pipeline_payload["next_followup"],
            "is_done": False,
        }
        return {
            "company_payload": company_payload,
            "pipeline_payload": pipeline_payload,
            "note_payload": note_payload,
        }

    def _build_mail_payloads(self, message: dict[str, Any], *, domain: str) -> dict[str, Any]:
        sender_name = str(message.get("sender_name") or message.get("from", {}).get("name") or "").strip()
        sender_email = str(message.get("sender_email") or message.get("from", {}).get("email") or "").strip().lower()
        subject = str(message.get("subject") or "(sin asunto)").strip()
        preview = str(message.get("preview") or message.get("body_text") or message.get("clean_body_text") or "").strip()
        classification_hint = str(message.get("classification_hint") or "").strip().lower()

        stage_map = {
            "positive_reply": "meeting",
            "meeting_request": "meeting",
            "proposal_request": "proposal",
            "pricing_request": "proposal",
            "customer_request": "contacted",
            "neutral_reply": "contacted",
            "negative_reply": "lost",
        }
        next_followup_days = {
            "positive_reply": 2,
            "meeting_request": 2,
            "proposal_request": 1,
            "pricing_request": 1,
            "customer_request": 2,
            "neutral_reply": 4,
            "negative_reply": 14,
        }
        pipeline_stage = stage_map.get(classification_hint, "contacted")
        next_followup = (date.today() + timedelta(days=next_followup_days.get(classification_hint, 3))).isoformat()

        company_name = domain.split(".", 1)[0].replace("-", " ").title() if domain else sender_email
        company_payload = {
            "name": company_name,
            "domain": domain,
            "status": "prospect",
            "lead_source": "inbound_email",
            "contact_name": sender_name or sender_email,
            "contact_email": sender_email,
            "notes": f"Empresa creada desde correo entrante procesado por Nexus.\nAsunto: {subject}",
        }
        pipeline_payload = {
            "pipeline_stage": pipeline_stage,
            "contact_name": sender_name or sender_email,
            "contact_email": sender_email,
            "lead_source": "inbound_email",
            "last_contact": date.today().isoformat(),
            "next_followup": next_followup,
        }
        note_payload = {
            "note_type": "email",
            "content": (
                f"Correo entrante procesado por Nexus.\n"
                f"De: {sender_name or sender_email} <{sender_email}>\n"
                f"Asunto: {subject}\n"
                f"Resumen: {preview[:1200]}"
            ).strip(),
            "note_date": date.today().isoformat(),
            "next_followup": next_followup,
            "is_done": False,
        }
        return {
            "company_payload": company_payload,
            "pipeline_payload": pipeline_payload,
            "note_payload": note_payload,
        }
