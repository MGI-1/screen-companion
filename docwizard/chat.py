"""Multi-provider LLM integration — Claude, GPT, Gemini."""

import json
import re
from typing import Optional

from docwizard.config import SYSTEM_PROMPT, LLM_PROVIDERS, load_user_config


class DocumentChat:
    """Chat with an LLM about a document. Supports multiple providers."""

    def __init__(self):
        self.messages: list[dict] = []
        self.document_content: str = ""
        self.document_path: str = ""
        self._client = None
        self._provider: str = ""
        self._model: str = ""
        self._api_key: str = ""

    def configure(self, provider: str, api_key: str, model: str = ""):
        """Set the LLM provider and API key."""
        self._provider = provider
        self._api_key = api_key
        self._model = model or LLM_PROVIDERS[provider]["default_model"]
        self._client = None  # Reset client to force re-init

    def is_configured(self) -> bool:
        return bool(self._provider and self._api_key)

    def set_document(self, path: str, content: str):
        """Update document context. Clears conversation history."""
        self.document_content = content
        self.document_path = path
        self.messages = []

    def ask(self, user_message: str) -> str:
        """Send a message and return the LLM response."""
        if not self.is_configured():
            return "Please configure your LLM provider in settings first."

        self.messages.append({"role": "user", "content": user_message})

        try:
            if self._provider == "anthropic":
                response = self._ask_anthropic()
            elif self._provider == "openai":
                response = self._ask_openai()
            elif self._provider == "google":
                response = self._ask_google()
            else:
                response = f"Unknown provider: {self._provider}"
        except Exception as e:
            error_msg = str(e)
            # Don't add error responses to history
            self.messages.pop()
            return f"API Error: {error_msg}"

        self.messages.append({"role": "assistant", "content": response})
        return response

    def _build_system_prompt(self) -> str:
        """Build system prompt with document context."""
        prompt = SYSTEM_PROMPT
        if self.document_content:
            prompt += (
                f"\n\nThe user has the following document open: {self.document_path}\n\n"
                f"<document_content>\n{self.document_content}\n</document_content>"
            )
        return prompt

    def _ask_anthropic(self) -> str:
        """Call Anthropic Claude API."""
        import anthropic

        if not self._client:
            self._client = anthropic.Anthropic(api_key=self._api_key)

        response = self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=self._build_system_prompt(),
            messages=self.messages,
        )
        return response.content[0].text

    def _ask_openai(self) -> str:
        """Call OpenAI GPT API."""
        import openai

        if not self._client:
            self._client = openai.OpenAI(api_key=self._api_key)

        messages = [
            {"role": "system", "content": self._build_system_prompt()},
            *self.messages,
        ]

        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            max_tokens=4096,
        )
        return response.choices[0].message.content

    def _ask_google(self) -> str:
        """Call Google Gemini API."""
        import google.generativeai as genai

        if not self._client:
            genai.configure(api_key=self._api_key)
            self._client = genai.GenerativeModel(
                model_name=self._model,
                system_instruction=self._build_system_prompt(),
            )

        # Convert message history to Gemini format
        history = []
        for msg in self.messages[:-1]:  # Exclude latest user message
            role = "user" if msg["role"] == "user" else "model"
            history.append({"role": role, "parts": [msg["content"]]})

        chat = self._client.start_chat(history=history)
        response = chat.send_message(self.messages[-1]["content"])
        return response.text

    @staticmethod
    def parse_edit_instructions(response: str) -> Optional[list[dict]]:
        """Extract edit instructions from LLM response.

        Looks for a fenced JSON block with {"action": "edit", "edits": [...]}.
        Returns the edits list, or None if no edits found.
        """
        pattern = r"```json\s*\n?(.*?)\n?\s*```"
        matches = re.findall(pattern, response, re.DOTALL)

        for match in matches:
            try:
                data = json.loads(match)
                if isinstance(data, dict) and data.get("action") == "edit":
                    edits = data.get("edits", [])
                    if edits:
                        return edits
            except json.JSONDecodeError:
                continue

        return None
