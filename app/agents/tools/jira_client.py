"""
Cliente JIRA REST API v3 (compatible con Jira Cloud free tier).

Configuración via .env:
    USE_JIRA=true
    JIRA_URL=https://tu-dominio.atlassian.net
    JIRA_EMAIL=tu@email.com
    JIRA_API_TOKEN=tu_api_token
    JIRA_PROJECT_KEY=NEXUS
"""

import os
import base64
import logging
from typing import Optional, Dict, List

import httpx

logger = logging.getLogger(__name__)


class JiraClient:
    """
    Cliente ligero para la API REST de Jira Cloud v3.
    Usa httpx con autenticación Basic (email + API token).
    """

    def __init__(self):
        self.enabled = os.getenv('USE_JIRA', 'false').lower() == 'true'
        self.base_url = os.getenv('JIRA_URL', '').rstrip('/')
        self.email = os.getenv('JIRA_EMAIL', '')
        self.api_token = os.getenv('JIRA_API_TOKEN', '')
        self.project_key = os.getenv('JIRA_PROJECT_KEY', 'NEXUS')

        if self.enabled and not all([self.base_url, self.email, self.api_token]):
            logger.warning(
                "USE_JIRA=true pero faltan JIRA_URL, JIRA_EMAIL o JIRA_API_TOKEN. "
                "El cliente JIRA quedará deshabilitado."
            )
            self.enabled = False

        if self.enabled:
            credentials = f"{self.email}:{self.api_token}"
            encoded = base64.b64encode(credentials.encode()).decode()
            self._headers = {
                "Authorization": f"Basic {encoded}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            logger.info(f"JiraClient inicializado — proyecto: {self.project_key}")
        else:
            logger.info("JiraClient deshabilitado (USE_JIRA=false)")

    # ------------------------------------------------------------------
    # Operaciones principales
    # ------------------------------------------------------------------

    async def create_issue(
        self,
        summary: str,
        description: str,
        issue_type: str = "Task",
        project_key: Optional[str] = None,
    ) -> Dict:
        """
        Crea un issue en Jira.

        Returns:
            {"key": "NEXUS-1", "id": "10001", "url": "https://..."}
        """
        self._check_enabled()
        project = project_key or self.project_key
        payload = {
            "fields": {
                "project": {"key": project},
                "summary": summary,
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": description}],
                        }
                    ],
                },
                "issuetype": {"name": issue_type},
            }
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.base_url}/rest/api/3/issue",
                json=payload,
                headers=self._headers,
            )
            resp.raise_for_status()
            data = resp.json()
            issue_key = data["key"]
            return {
                "key": issue_key,
                "id": data["id"],
                "url": f"{self.base_url}/browse/{issue_key}",
            }

    async def get_issue(self, issue_key: str) -> Dict:
        """Obtiene los detalles de un issue por su clave (ej: NEXUS-42)."""
        self._check_enabled()
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self.base_url}/rest/api/3/issue/{issue_key}",
                headers=self._headers,
            )
            resp.raise_for_status()
            data = resp.json()
            fields = data.get("fields", {})
            return {
                "key": data["key"],
                "summary": fields.get("summary", ""),
                "status": fields.get("status", {}).get("name", ""),
                "assignee": (fields.get("assignee") or {}).get("displayName", "Sin asignar"),
                "priority": (fields.get("priority") or {}).get("name", ""),
                "created": fields.get("created", ""),
                "updated": fields.get("updated", ""),
                "url": f"{self.base_url}/browse/{data['key']}",
            }

    async def add_comment(self, issue_key: str, comment: str) -> Dict:
        """Añade un comentario a un issue existente."""
        self._check_enabled()
        payload = {
            "body": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": comment}],
                    }
                ],
            }
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.base_url}/rest/api/3/issue/{issue_key}/comment",
                json=payload,
                headers=self._headers,
            )
            resp.raise_for_status()
            return {"issue_key": issue_key, "comment_id": resp.json().get("id")}

    async def search_issues(self, jql: str, max_results: int = 10) -> List[Dict]:
        """
        Busca issues usando JQL.

        Ejemplo jql: 'project = NEXUS AND status = "In Progress"'
        """
        self._check_enabled()
        params = {
            "jql": jql,
            "maxResults": max_results,
            "fields": "summary,status,assignee,priority,created",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self.base_url}/rest/api/3/search",
                params=params,
                headers=self._headers,
            )
            resp.raise_for_status()
            issues = resp.json().get("issues", [])
            return [
                {
                    "key": i["key"],
                    "summary": i["fields"].get("summary", ""),
                    "status": i["fields"].get("status", {}).get("name", ""),
                    "assignee": (i["fields"].get("assignee") or {}).get("displayName", "Sin asignar"),
                    "url": f"{self.base_url}/browse/{i['key']}",
                }
                for i in issues
            ]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _check_enabled(self):
        if not self.enabled:
            raise RuntimeError(
                "JiraClient no está habilitado. "
                "Configura USE_JIRA=true y las variables JIRA_* en .env"
            )
