"""Multi-provider LLM integration — Claude, GPT, Gemini."""

import json
import re
from typing import Optional

from docwizard.config import (
    SYSTEM_PROMPT, LLM_PROVIDERS, load_user_config,
    VALIDATOR_SYSTEM_PROMPT, VALIDATOR_USER_TEMPLATE,
)


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
        self._validator_provider: str = ""
        self._validator_model: str = ""
        self._validator_api_key: str = ""

    def configure(self, provider: str, api_key: str, model: str = ""):
        """Set the LLM provider and API key."""
        self._provider = provider
        self._api_key = api_key
        self._model = model or LLM_PROVIDERS[provider]["default_model"]
        self._client = None  # Reset client to force re-init

    def configure_validator(self, provider: str, api_key: str, model: str = ""):
        """Set an optional secondary model to validate output completeness."""
        self._validator_provider = provider
        self._validator_api_key = api_key
        self._validator_model = model or LLM_PROVIDERS[provider]["default_model"]

    def clear_validator(self):
        self._validator_provider = ""
        self._validator_api_key = ""
        self._validator_model = ""

    def is_configured(self) -> bool:
        return bool(self._provider and self._api_key)

    def has_validator(self) -> bool:
        return bool(self._validator_provider and self._validator_api_key)

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
            self.messages.pop()
            return f"API Error: {error_msg}"

        # Validate completeness with a second model if configured
        if self.has_validator():
            try:
                is_complete, reason = self._validate_response(user_message, response)
                if not is_complete:
                    response = self._request_completion(user_message, response, reason)
            except Exception:
                pass  # Never block the user due to validator failure

        self.messages.append({"role": "assistant", "content": response})
        return response

    def _validate_response(self, question: str, response: str) -> tuple[bool, str]:
        """Ask the validator model whether the response is complete.

        Returns (is_complete, reason).
        """
        prompt = VALIDATOR_USER_TEMPLATE.format(question=question, response=response)
        messages = [{"role": "user", "content": prompt}]
        raw = self._call_one_shot(
            self._validator_provider,
            self._validator_api_key,
            self._validator_model,
            VALIDATOR_SYSTEM_PROMPT,
            messages,
        )
        try:
            data = json.loads(raw.strip())
            return bool(data.get("complete", True)), data.get("reason", "")
        except (json.JSONDecodeError, AttributeError):
            return True, ""

    def _request_completion(self, original_question: str, partial: str, reason: str) -> str:
        """Ask the primary model to complete a truncated response."""
        followup = (
            f"Your previous response was incomplete ({reason}). "
            f"Please provide the full, complete answer to the original question without repeating the part you already covered. "
            f"Original question: {original_question}"
        )
        temp_messages = list(self.messages) + [
            {"role": "assistant", "content": partial},
            {"role": "user", "content": followup},
        ]
        try:
            completion = self._call_one_shot(
                self._provider,
                self._api_key,
                self._model,
                self._build_system_prompt(),
                temp_messages,
            )
            return partial + "\n\n" + completion
        except Exception:
            return partial

    def _call_one_shot(
        self,
        provider: str,
        api_key: str,
        model: str,
        system: str,
        messages: list[dict],
    ) -> str:
        """Make a single stateless API call to any provider."""
        if provider == "anthropic":
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            resp = client.messages.create(
                model=model,
                max_tokens=1024,
                system=system,
                messages=messages,
            )
            return resp.content[0].text

        elif provider == "openai":
            import openai
            client = openai.OpenAI(api_key=api_key)
            full_messages = [{"role": "system", "content": system}, *messages]
            resp = client.chat.completions.create(
                model=model,
                messages=full_messages,
                max_tokens=1024,
            )
            return resp.choices[0].message.content

        elif provider == "google":
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            gmodel = genai.GenerativeModel(
                model_name=model,
                system_instruction=system,
            )
            history = []
            for msg in messages[:-1]:
                role = "user" if msg["role"] == "user" else "model"
                history.append({"role": role, "parts": [msg["content"]]})
            chat = gmodel.start_chat(history=history)
            resp = chat.send_message(messages[-1]["content"])
            return resp.text

        raise ValueError(f"Unknown provider: {provider}")

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
            max_tokens=8192,
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
            max_tokens=8192,
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
