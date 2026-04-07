"""Multi-provider LLM integration — Claude, GPT, Gemini."""

import json
import re
from typing import Optional

from screencompanion.config import (
    SYSTEM_PROMPT, LLM_PROVIDERS, load_user_config,
    RECONCILE_SYSTEM_PROMPT, RECONCILE_USER_TEMPLATE,
    CODE_GEN_SYSTEM_PROMPT, CODE_GEN_USER_TEMPLATE,
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
        self._validator_api_key: str = ""
        self.document_images: list = []   # list[ImageData]
        self._images_pending: bool = False
        self._dataframe = None  # pandas DataFrame for CSV/XLSX files

    def configure(self, provider: str, api_key: str, model: str = ""):
        """Set the LLM provider and API key."""
        self._provider = provider
        self._api_key = api_key
        self._model = model or LLM_PROVIDERS[provider]["default_model"]
        self._client = None  # Reset client to force re-init

    def configure_validator(self, provider: str, api_key: str):
        """Set an optional validator that checks completeness using all 3 models of the provider."""
        self._validator_provider = provider
        self._validator_api_key = api_key

    def clear_validator(self):
        self._validator_provider = ""
        self._validator_api_key = ""

    def is_configured(self) -> bool:
        return bool(self._provider and self._api_key)

    def has_validator(self) -> bool:
        return bool(self._validator_provider and self._validator_api_key)

    def set_document(self, path: str, content: str, images: list = None, dataframe=None):
        """Update document context. Clears conversation history."""
        self.document_content = content
        self.document_path = path
        self.messages = []
        self.document_images = images or []
        self._images_pending = bool(self.document_images)
        self._dataframe = dataframe

    def ask(self, user_message: str) -> str:
        """Send a message and return the LLM response."""
        if not self.is_configured():
            return "Please configure your LLM provider in settings first."

        self.messages.append({"role": "user", "content": user_message})

        # For structured data (CSV/XLSX), execute pandas code for precise answers
        if self._dataframe is not None:
            try:
                response = self._ask_with_code(user_message)
                self.messages.append({"role": "assistant", "content": response})
                return response
            except Exception:
                pass  # Fall through to regular LLM path

        inject_images = self._images_pending
        if inject_images:
            self._images_pending = False  # clear before call; restore on error

        try:
            if self._provider == "anthropic":
                response = self._ask_anthropic(inject_images)
            elif self._provider == "openai":
                response = self._ask_openai(inject_images)
            elif self._provider == "google":
                response = self._ask_google(inject_images)
            else:
                response = f"Unknown provider: {self._provider}"
        except Exception as e:
            error_msg = str(e)
            self.messages.pop()
            if inject_images:
                self._images_pending = True  # restore so user can retry
            return f"API Error: {error_msg}"

        if inject_images:
            self.document_images = []  # free memory after successful send

        # Cross-check with 3 independent validator models and reconcile
        if self.has_validator():
            try:
                validator_answers = self._get_validator_answers(user_message)
                if validator_answers:
                    response = self._reconcile(user_message, response, validator_answers)
            except Exception:
                pass  # Never block the user due to validator failure

        self.messages.append({"role": "assistant", "content": response})
        return response

    def _ask_with_code(self, question: str) -> str:
        """Generate pandas code via LLM, execute it, and return the result."""
        import pandas as pd

        df = self._dataframe
        schema = "\n".join(f"  {col}: {dtype}" for col, dtype in df.dtypes.items())
        sample = df.head(3).to_string(index=False)

        raw = self._call_one_shot(
            self._provider,
            self._api_key,
            self._model,
            CODE_GEN_SYSTEM_PROMPT,
            [{"role": "user", "content": CODE_GEN_USER_TEMPLATE.format(
                schema=schema, sample=sample, question=question,
            )}],
        )

        # Strip markdown fences if the model wrapped the code
        code = raw.strip()
        if code.startswith("```"):
            code = re.sub(r"^```[a-z]*\n?", "", code)
            code = re.sub(r"\n?```$", "", code.strip())
        code = code.strip()

        safe_builtins = {
            "len": len, "str": str, "int": int, "float": float,
            "round": round, "list": list, "dict": dict, "sorted": sorted,
            "sum": sum, "min": min, "max": max, "range": range,
            "enumerate": enumerate, "zip": zip, "bool": bool,
            "isinstance": isinstance, "abs": abs, "print": print,
        }
        namespace = {"df": df.copy(), "pd": pd, "__builtins__": safe_builtins}
        exec(code, namespace)  # noqa: S102

        result = namespace.get("result")
        if result is None:
            raise ValueError("Code did not set `result`")

        if hasattr(result, "to_string"):
            return result.to_string(index=False)
        return str(result)

    def _get_validator_answers(self, question: str) -> list[str]:
        """Get independent answers from all 3 models of the validator provider."""
        models = LLM_PROVIDERS.get(self._validator_provider, {}).get("models", [])
        system = self._build_system_prompt()  # includes document context
        messages = [{"role": "user", "content": question}]
        answers = []
        for model in models:
            try:
                answer = self._call_one_shot(
                    self._validator_provider,
                    self._validator_api_key,
                    model,
                    system,
                    messages,
                )
                answers.append(answer)
            except Exception:
                pass
        return answers

    def _reconcile(self, question: str, primary: str, validator_answers: list[str]) -> str:
        """Ask the primary model to reconcile its answer against the validator answers."""
        answers_text = "\n\n".join(f"[{i + 1}] {a}" for i, a in enumerate(validator_answers))
        user_content = RECONCILE_USER_TEMPLATE.format(
            document=self.document_content or "No document loaded.",
            question=question,
            primary=primary,
            answers=answers_text,
        )
        try:
            return self._call_one_shot(
                self._provider,
                self._api_key,
                self._model,
                RECONCILE_SYSTEM_PROMPT,
                [{"role": "user", "content": user_content}],
            )
        except Exception:
            return primary

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

    def _ask_anthropic(self, inject_images: bool = False) -> str:
        """Call Anthropic Claude API."""
        import anthropic
        import base64

        if not self._client:
            self._client = anthropic.Anthropic(api_key=self._api_key)

        messages = list(self.messages)

        if inject_images and self.document_images:
            content_blocks = []
            for img in self.document_images:
                content_blocks.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": img.media_type,
                        "data": base64.standard_b64encode(img.data).decode("utf-8"),
                    },
                })
            content_blocks.append({"type": "text", "text": messages[-1]["content"]})
            messages = messages[:-1] + [{"role": "user", "content": content_blocks}]

        response = self._client.messages.create(
            model=self._model,
            max_tokens=8192,
            system=self._build_system_prompt(),
            messages=messages,
        )
        return response.content[0].text

    def _ask_openai(self, inject_images: bool = False) -> str:
        """Call OpenAI GPT API."""
        import openai
        import base64

        if not self._client:
            self._client = openai.OpenAI(api_key=self._api_key)

        messages = [
            {"role": "system", "content": self._build_system_prompt()},
            *self.messages,
        ]

        if inject_images and self.document_images:
            content_parts = []
            for img in self.document_images:
                b64 = base64.standard_b64encode(img.data).decode("utf-8")
                content_parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{img.media_type};base64,{b64}"},
                })
            content_parts.append({"type": "text", "text": messages[-1]["content"]})
            messages[-1] = {"role": "user", "content": content_parts}

        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            max_tokens=8192,
        )
        return response.choices[0].message.content

    def _ask_google(self, inject_images: bool = False) -> str:
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
        last_text = self.messages[-1]["content"]

        if inject_images and self.document_images:
            from google.generativeai import types as genai_types
            parts = [
                genai_types.Part.from_bytes(data=img.data, mime_type=img.media_type)
                for img in self.document_images
            ]
            parts.append(last_text)
            response = chat.send_message(parts)
        else:
            response = chat.send_message(last_text)

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

    @staticmethod
    def parse_math_instructions(response: str) -> Optional[dict]:
        """Extract a math calculation instruction from LLM response.

        Looks for a fenced JSON block with {"action": "calculate", "function": ..., "args": {...}}.
        Returns the dict, or None if not found.
        """
        pattern = r"```json\s*\n?(.*?)\n?\s*```"
        matches = re.findall(pattern, response, re.DOTALL)

        for match in matches:
            try:
                data = json.loads(match)
                if isinstance(data, dict) and data.get("action") == "calculate":
                    fn = data.get("function")
                    args = data.get("args", {})
                    if fn:
                        return {"function": fn, "args": args}
            except json.JSONDecodeError:
                continue

        return None

    @staticmethod
    def execute_math(function: str, args: dict) -> dict:
        """Execute a deterministic math calculation. Returns the provenance envelope."""
        from screencompanion import math_tools

        # Map short names used in the system prompt to actual function names
        fn_map = {
            "add": math_tools.decimal_add,
            "subtract": math_tools.decimal_subtract,
            "multiply": math_tools.decimal_multiply,
            "divide": math_tools.decimal_divide,
            "sum_values": math_tools.decimal_sum,
            "average": math_tools.decimal_average,
            "weighted_average": math_tools.decimal_weighted_average,
            "round": math_tools.decimal_round,
            "percentage": math_tools.decimal_percentage,
            "percentage_change": math_tools.decimal_percentage_change,
            "variance": math_tools.decimal_variance,
            "compound_growth": math_tools.decimal_compound_growth,
            "margin": math_tools.decimal_margin,
            "roi": math_tools.decimal_roi,
            "npv": math_tools.decimal_npv,
            "irr": math_tools.decimal_irr,
            "payback_period": math_tools.decimal_payback_period,
            "cagr": math_tools.decimal_cagr,
            "current_ratio": math_tools.decimal_current_ratio,
            "quick_ratio": math_tools.decimal_quick_ratio,
            "debt_to_equity": math_tools.decimal_debt_to_equity,
            "working_capital": math_tools.decimal_working_capital,
            "dso": math_tools.decimal_dso,
            "ebitda": math_tools.decimal_ebitda,
            "gross_margin": math_tools.decimal_gross_margin,
            "operating_margin": math_tools.decimal_operating_margin,
            "roe": math_tools.decimal_roe,
            "roa": math_tools.decimal_roa,
            "fx_convert": math_tools.decimal_fx_convert,
            "rank": math_tools.decimal_rank,
            "threshold_check": math_tools.decimal_threshold_check,
        }

        fn = fn_map.get(function)
        if fn is None:
            raise ValueError(f"Unknown math function: {function}")

        # Convert integer args from JSON (which parses them as int) to proper types
        import inspect
        sig = inspect.signature(fn)
        coerced = {}
        for param_name, param in sig.parameters.items():
            if param_name in args:
                val = args[param_name]
                if param.annotation == int and isinstance(val, str):
                    coerced[param_name] = int(val)
                else:
                    coerced[param_name] = val
            elif param.default is not inspect.Parameter.empty:
                pass  # use default
        # Pass any extra args not in signature (handled by the function)
        for k, v in args.items():
            if k not in coerced:
                coerced[k] = v

        return fn(**coerced)
