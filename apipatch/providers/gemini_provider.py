"""
Google Gemini & Vertex AI Provider for ApiPatch
Supports both Google AI Studio (API Key) and Google Cloud Vertex AI (Service Account / 300$ Credits)
with automatic rate-limit (429) retry and seamless fallback.
"""

import os
import time
import json
import re
import urllib.request
import urllib.parse
import urllib.error
from typing import Dict, Any, List, Optional
from apipatch.providers.base import BaseProvider


class GeminiProvider(BaseProvider):
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        project_id: Optional[str] = None,
        location: Optional[str] = None
    ):
        super().__init__(
            api_key=api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"),
            model=model or "gemini-2.5-flash"
        )
        # Alternate fallback models
        self.fallback_models = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-flash-latest"]
        
        # Vertex AI / Google Cloud Service Account Auto-Detection
        self.vertex_client = None
        self.is_vertex = False

        creds_file = (
            os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            or (None if api_key else ("gcc_auth.json" if os.path.isfile("gcc_auth.json") else None))
            or (None if api_key else ("gcc-auth.json" if os.path.isfile("gcc-auth.json") else None))
        )
        if creds_file and os.path.isfile(creds_file):
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.abspath(creds_file)
            if not project_id:
                try:
                    with open(creds_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        project_id = data.get("project_id")
                except Exception:
                    pass

        self.project_id = project_id or os.getenv("VERTEX_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT")
        self.location = location or os.getenv("VERTEX_LOCATION") or os.getenv("GOOGLE_CLOUD_LOCATION") or "us-central1"

        if self.project_id and (not api_key or project_id):
            try:
                from google import genai
                self.vertex_client = genai.Client(
                    vertexai=True,
                    project=self.project_id,
                    location=self.location
                )
                self.is_vertex = True
            except Exception:
                self.vertex_client = None

    def _call_model(self, model_name: str, prompt: str) -> Optional[str]:
        clean_model = model_name[7:] if model_name.startswith("models/") else model_name

        # 1. Call via Vertex AI (Google Cloud Credits) if initialized
        if self.is_vertex and self.vertex_client:
            try:
                response = self.vertex_client.models.generate_content(
                    model=clean_model,
                    contents=prompt,
                    config={
                        "response_mime_type": "application/json",
                        "temperature": 0.0
                    }
                )
                if response and response.text:
                    return response.text
            except Exception as e:
                # If Vertex fails on this model, re-raise so fallback loop catches it
                raise e

        # 2. Call via standard Google AI Studio REST API
        if not self.api_key:
            raise ValueError(
                "No Gemini API credentials found. Either configure Google Cloud Vertex AI "
                "(gcc_auth.json / GOOGLE_APPLICATION_CREDENTIALS) or set GEMINI_API_KEY."
            )

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{clean_model}:generateContent?key={self.api_key}"
        )
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.0
            }
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=90) as response:
            data = json.loads(response.read().decode("utf-8"))
            candidates = data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                if parts:
                    return parts[0].get("text", "")
        return None

    def _execute_with_fallbacks(self, prompt: str) -> Dict[str, Any]:
        models_to_try = [self.model] + [m for m in self.fallback_models if m != self.model]
        last_err = None
        for current_model in models_to_try:
            try:
                raw_text = self._call_model(current_model, prompt)
                if raw_text:
                    return self.clean_json_response(raw_text)
                return {"has_breaking_changes": False, "detected_issues": [], "refactored_code": ""}

            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="ignore")
                last_err = f"HTTP {e.code}: {err_body}"
                if e.code in {429, 503, 500, 404, 502, 504}:
                    time.sleep(2.0)
                    continue
                raise ValueError(f"Gemini API HTTP {e.code}: {err_body}")

            except Exception as e:
                last_err = str(e)
                continue

        if last_err and any(code in str(last_err) for code in ("429", "503")):
            raise ValueError(f"Gemini models temporarily busy or rate-limited: {last_err}")

        return {"has_breaking_changes": False, "detected_issues": [], "refactored_code": ""}

    def audit_code(
        self,
        file_name: str,
        code: str,
        detected_libraries: List[str],
        project_context: Optional[str] = None
    ) -> Dict[str, Any]:
        if not self.api_key and not self.is_vertex:
            raise ValueError(
                "No Gemini credentials found. Set GEMINI_API_KEY, GOOGLE_API_KEY, "
                "or place Google Cloud credentials in gcc_auth.json / GOOGLE_APPLICATION_CREDENTIALS."
            )
        prompt = self.build_prompt(file_name, code, detected_libraries, project_context=project_context)
        return self._execute_with_fallbacks(prompt)

    def heal_code(
        self,
        file_name: str,
        original_code: str,
        broken_code: str,
        validation_error: str,
        detected_libraries: Optional[List[str]] = None,
        project_context: Optional[str] = None
    ) -> Dict[str, Any]:
        if not self.api_key and not self.is_vertex:
            raise ValueError(
                "No Gemini credentials found. Set GEMINI_API_KEY, GOOGLE_API_KEY, "
                "or place Google Cloud credentials in gcc_auth.json / GOOGLE_APPLICATION_CREDENTIALS."
            )
        prompt = self.build_healing_prompt(
            file_name=file_name,
            original_code=original_code,
            broken_code=broken_code,
            validation_error=validation_error,
            detected_libraries=detected_libraries,
            project_context=project_context
        )
        return self._execute_with_fallbacks(prompt)
