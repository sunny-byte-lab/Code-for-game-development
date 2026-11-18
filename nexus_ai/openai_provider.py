"""N.E.X.U.S. OpenAI & Local LLM Provider.
Compatible with OpenAI, Ollama, LM Studio, Groq, and vLLM through standard HTTP chat completions.
"""

import json
import logging
import urllib.request
import urllib.error
from typing import List, Optional, Iterator
from nexus_ai.provider_base import AIProvider, ChatMessage, AIResponse

logger = logging.getLogger("NEXUS.AI.OpenAI")


class OpenAIProvider(AIProvider):
    """OpenAI / Local LLM provider via standard /v1/chat/completions endpoint."""

    def __init__(self, api_key: str = "", model_name: str = "gpt-4o-mini", base_url: str = "https://api.openai.com/v1"):
        self.api_key = api_key
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")
        self.endpoint = f"{self.base_url}/chat/completions"

    @property
    def name(self) -> str:
        return "openai"

    @property
    def is_configured(self) -> bool:
        # Local endpoints (like Ollama / LM Studio) may not require an api_key
        if "127.0.0.1" in self.base_url or "localhost" in self.base_url:
            return True
        return bool(self.api_key and len(self.api_key) > 5)

    def generate(self, messages: List[ChatMessage], system_prompt: Optional[str] = None) -> AIResponse:
        if not self.is_configured:
            return AIResponse(
                content="[AI Error] OpenAI API key or endpoint not configured in N.E.X.U.S.",
                model=self.model_name,
                error="API_KEY_MISSING"
            )

        formatted_msgs = []
        if system_prompt:
            formatted_msgs.append({"role": "system", "content": system_prompt})
        for m in messages:
            formatted_msgs.append({"role": m.role, "content": m.content})

        payload = {
            "model": self.model_name,
            "messages": formatted_msgs,
            "temperature": 0.7
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}" if self.api_key else ""
        }

        req_data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.endpoint, data=req_data, headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp_json = json.loads(resp.read().decode("utf-8"))

            choices = resp_json.get("choices", [])
            if not choices:
                return AIResponse(content="[No response generated]", model=self.model_name)

            msg_out = choices[0].get("message", {}).get("content", "")
            usage = resp_json.get("usage", {})
            return AIResponse(
                content=msg_out,
                model=self.model_name,
                usage={"total_tokens": usage.get("total_tokens", 0)}
            )
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            logger.error(f"OpenAI API HTTP {e.code}: {err_body}")
            return AIResponse(content=f"[OpenAI API Error {e.code}]", model=self.model_name, error=str(e))
        except Exception as e:
            logger.error(f"OpenAI request failed: {e}")
            return AIResponse(content=f"[Connection Error: {e}]", model=self.model_name, error=str(e))

    def stream(self, messages: List[ChatMessage], system_prompt: Optional[str] = None) -> Iterator[str]:
        resp = self.generate(messages, system_prompt)
        if resp.content:
            yield resp.content
