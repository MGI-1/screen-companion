"""Multi-provider LLM integration — Claude, GPT, Gemini."""

import json
import re
from typing import Optional

from screencompanion.config import (
    SYSTEM_PROMPT, LLM_PROVIDERS, load_user_config,
    RECONCILE_SYSTEM_PROMPT, RECONCILE_USER_TEMPLATE,
    CODE_GEN_SYSTEM_PROMPT, CODE_GEN_USER_TEMPLATE,
    get_output_tokens, is_reasoning_model,
)
from screencompanion.interpreter import interpret, Interpretation
from screencompanion.logging_setup import get_logger

_log = get_logger("chat")


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
        self._output_tokens: int = 4_096
        self._last_math_result: Optional[dict] = None  # consumed by app.py for sidebar
        self._last_interpretation: Optional[Interpretation] = None  # consumed by app.py for UI hint

    def configure(self, provider: str, api_key: str, model: str = ""):
        """Set the LLM provider and API key."""
        self._provider = provider
        self._api_key = api_key
        info = LLM_PROVIDERS[provider]
        # A model saved by an older build may no longer be offered; fall back
        # rather than sending a name the API will reject.
        if model and model in info.get("models", []):
            self._model = model
        else:
            self._model = info["default_model"]
        self._output_tokens = get_output_tokens(self._provider, self._model)
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
        # Rebuild the provider client on the next call. Google Gemini bakes the
        # document text into the client's system_instruction at CREATION time
        # and reuses that client for every later message — so without this reset
        # a client created while the previous document was open keeps answering
        # about that document even after the user switches files. (Anthropic /
        # OpenAI pass the system prompt per-request, so they were unaffected;
        # resetting them here is harmless — they just re-init.)
        self._client = None

    def ask(self, user_message: str) -> str:
        """Send a message and return the LLM response."""
        if not self.is_configured():
            return "Please configure your LLM provider in settings first."

        # No document loaded → refuse rather than let the model hallucinate an
        # answer about a document that isn't there. Detection can briefly clear
        # the document (focus flapping between windows); a question asked in
        # that window would otherwise get a fully fabricated answer with no
        # grounding (e.g. inventing an "Intellectual Property" contract section
        # for a task spreadsheet).
        if not self.document_content and self._dataframe is None:
            return (
                "No document is loaded, so there's nothing for me to read yet. "
                "Switch to a document (or click the 🔍 detect button) and ask again."
            )

        # Reset prior math result so app.py never re-renders a stale sidebar
        self._last_math_result = None

        # Intelligent input interpretation: classify intent, extract entities,
        # scan the document for the sections most likely to contain the
        # answer. Injected into the system prompt (_build_system_prompt
        # reads self._last_interpretation) so every LLM turn is sharpened
        # without polluting conversation history.
        self._last_interpretation = interpret(user_message, self.document_content)

        self.messages.append({"role": "user", "content": user_message})

        # Excel/CSV (a DataFrame is available): ALWAYS answer by generating and
        # running code — it is exact and deterministic (user preference). Other
        # document types (PDF/Word/text) have no DataFrame to run code against,
        # so they fall through to the LLM, which emits a calculation block only
        # when the question actually needs math (see the system-prompt guidance
        # keyed off the detected intent) — i.e. code is used there only if
        # required.
        use_code = self._dataframe is not None
        _log.info(
            "ask: path=%r df_present=%s content_len=%d use_code=%s",
            self.document_path, self._dataframe is not None,
            len(self.document_content or ""), use_code,
        )
        if use_code:
            # Distinct-value count/list questions ("how many owners", "give me
            # the list of owners") are answered by a fixed Python computation,
            # NOT LLM-generated code. The generator is non-deterministic — it
            # would sometimes count cell entries (11) and sometimes split them
            # into individuals (5), and its list would drop/duplicate rows — so
            # the count and the list could disagree. Computing both from the
            # same `unique()` here makes them always consistent.
            det = self._try_distinct_value_answer(user_message)
            if det is not None:
                self.messages.append({"role": "assistant", "content": det})
                return det
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
            response = self._dispatch_provider(inject_images)
        except Exception as e:
            error_msg = str(e)
            self.messages.pop()
            if inject_images:
                self._images_pending = True  # restore so user can retry
            return f"API Error: {error_msg}"

        if inject_images:
            self.document_images = []  # free memory after successful send

        # ── Math feedback loop ────────────────────────────────────────
        # If the model emitted a calculation block, execute it deterministically
        # and re-ask the model with the result injected so its prose answer
        # actually reflects the computed numbers. Capped at one round.
        math_instr = self.parse_math_instructions(response)
        if math_instr:
            try:
                envelope = self.execute_math(
                    math_instr["function"], math_instr["args"]
                )
                self._last_math_result = envelope
                response = self._continue_with_math_result(
                    response, math_instr["function"], envelope
                )
            except Exception as exc:
                # Math failure shouldn't block the user — surface the error
                # in the sidebar via _last_math_result and keep original prose.
                self._last_math_result = {
                    "result": "ERROR",
                    "formula": f"{math_instr.get('function', '?')} failed",
                    "error": str(exc),
                }

        # Strip any residual JSON calc block so app.py doesn't double-execute
        response = self._strip_calc_block(response)

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

    def _dispatch_provider(self, inject_images: bool) -> str:
        """Route to the configured provider's _ask_* method."""
        if self._provider == "anthropic":
            return self._ask_anthropic(inject_images)
        if self._provider == "openai":
            return self._ask_openai(inject_images)
        if self._provider == "google":
            return self._ask_google(inject_images)
        return f"Unknown provider: {self._provider}"

    def _continue_with_math_result(
        self, first_response: str, function: str, envelope: dict
    ) -> str:
        """
        Feed a deterministic math result back to the LLM for one more round
        so it can write a final answer using the computed value.

        Synthetic feedback messages are popped before returning so they never
        leak into long-term conversation history.
        """
        # Append the model's first response to history so it sees its own thinking
        self.messages.append({"role": "assistant", "content": first_response})

        feedback_payload = json.dumps(envelope, indent=2, default=str)
        feedback_msg = (
            f"Tool result for {function}:\n{feedback_payload}\n\n"
            "Use this exact result to write the final answer for the user. "
            "If the envelope contains `filtered_items`, `top_items`, or "
            "`ranked_items`, list ONLY those items — do not add or remove any. "
            "Do not emit another calculation block."
        )
        self.messages.append({"role": "user", "content": feedback_msg})

        try:
            final_response = self._dispatch_provider(inject_images=False)
        except Exception:
            # Roll back synthetic turns and fall back to the original response
            self.messages.pop()  # feedback user msg
            self.messages.pop()  # first assistant msg
            return first_response

        # Drop synthetic turns; the caller will append the final response itself
        self.messages.pop()  # feedback user msg
        self.messages.pop()  # first assistant msg
        return final_response

    @staticmethod
    def _strip_calc_block(text: str) -> str:
        """Remove any ```json {"action":"calculate", ...} ``` block from text."""
        pattern = r"```json\s*\n?\{[^`]*\"action\"\s*:\s*\"calculate\"[^`]*\}\s*\n?```"
        cleaned = re.sub(pattern, "", text, flags=re.DOTALL).strip()
        return cleaned or text

    def consume_last_math_result(self) -> Optional[dict]:
        """Pop and return the math envelope from the most recent ask() call."""
        envelope = self._last_math_result
        self._last_math_result = None
        return envelope

    # Cell separators that bundle several names/items into one cell, e.g.
    # "Aman, Anutosh, Rishabh" or "Anutosh and Rishabh" or "Rishabh (+Anutosh)".
    _BUNDLE_SPLIT = re.compile(r"\s*(?:,|&|\+|/|\band\b)\s*", re.IGNORECASE)
    _FILTER_CUES = re.compile(
        r"\b(assigned to|owned by|responsible for|handled by|belongs?\s+to|"
        r"above|below|greater than|less than|more than|at least|at most|"
        r"top\s+\d|bottom\s+\d|where\b.*\bis)\b",
        re.IGNORECASE,
    )
    _LIST_CUES = re.compile(r"\b(list|names?\s+of|who\s+(are|is)|show\s+me)\b", re.IGNORECASE)
    _COUNT_CUES = re.compile(r"\b(how\s+many|number\s+of|count|how\s+much)\b", re.IGNORECASE)

    def _match_column(self, question: str):
        """Return the DataFrame column the question refers to, or None.

        Matches a column name (or its singular/plural form) as a whole word in
        the question — e.g. "owners" → the "Owner" column.
        """
        ql = question.lower()
        best = None
        for col in self._dataframe.columns:
            cl = str(col).lower().strip()
            if not cl or cl.startswith("_"):
                continue
            variants = {cl, cl + "s", cl[:-1] if cl.endswith("s") else cl}
            if any(v and re.search(r"\b" + re.escape(v) + r"\b", ql) for v in variants):
                if best is None or len(cl) > len(str(best).lower()):
                    best = col
        return best

    def _try_distinct_value_answer(self, question: str):
        """Deterministically answer 'how many / list the distinct values of column X'.

        Computes the count AND the list from the SAME `unique()` result so they
        can never disagree — unlike LLM-generated code, which varies run to run.
        When cells bundle several names, also reports the distinct individuals
        in parentheses so the number is unambiguous (e.g. "11 owner entries
        (5 unique people)"). Returns None when the question isn't a plain
        distinct-value count/list (e.g. it has a filter), so the caller falls
        back to generated code.
        """
        df = self._dataframe
        if df is None or self._last_interpretation is None:
            return None
        if self._last_interpretation.intent not in ("extract", "calculate"):
            return None
        # A filtered/threshold question needs real code — don't hijack it.
        if self._FILTER_CUES.search(question):
            return None
        wants_list = bool(self._LIST_CUES.search(question))
        wants_count = bool(self._COUNT_CUES.search(question))
        if not (wants_list or wants_count):
            return None
        col = self._match_column(question)
        if col is None:
            return None

        vals = [str(v).strip() for v in df[col].dropna().tolist()]
        vals = [v for v in vals if v and v.lower() != "nan"]
        entries = list(dict.fromkeys(vals))  # order-preserving distinct cells
        if not entries:
            return None
        n = len(entries)
        label = str(col).strip()

        # The "unique individuals" clarification only makes sense for people
        # columns — splitting free-text (e.g. a Task sentence with commas)
        # produces nonsense. So compute it only for owner/assignee-type columns.
        is_person = any(k in label.lower() for k in
                        ("owner", "assign", "person", "people", "author", "responsible", "name"))

        indiv, seen, bundled = [], set(), False
        if is_person:
            for cell in entries:
                # Drop parenthetical notes FIRST ("(with Akshat)", "(+Anutosh)")
                # so the bundle-splitter doesn't tear them into fragments, then
                # split the remaining bundled names.
                cleaned = re.sub(r"\([^)]*\)", " ", cell)
                parts = [p.strip(" .") for p in self._BUNDLE_SPLIT.split(cleaned) if p.strip(" .")]
                if len(parts) > 1:
                    bundled = True
                for p in parts:
                    if p and p.lower() not in seen:
                        seen.add(p.lower())
                        indiv.append(p)
        clarify = is_person and bundled and len(indiv) != n

        if wants_list:
            out = [f"There are {n} distinct {label} entries:"]
            out += [f"- {e}" for e in entries]
            if clarify:
                out += ["", f"(These {n} entries cover {len(indiv)} unique people: "
                            f"{', '.join(indiv)}.)"]
            text = "\n".join(out)
        else:  # pure count
            if clarify:
                text = (f"There are {n} distinct {label} entries "
                        f"({len(indiv)} unique people: {', '.join(indiv)}).")
            else:
                text = f"There are {n} distinct {label} entries."
        return self._clean_datetime_strings(text)

    def _ask_with_code(self, question: str) -> str:
        """Generate pandas code via LLM, execute it, and return the result."""
        import pandas as pd

        df = self._dataframe
        schema = "\n".join(f"  {col}: {dtype}" for col, dtype in df.dtypes.items())

        # For multi-sheet workbooks, show samples per sheet so the LLM knows the structure
        if "_sheet_name" in df.columns:
            sample_parts = []
            for sheet_name in df["_sheet_name"].unique():
                sheet_df = df[df["_sheet_name"] == sheet_name]
                sample_parts.append(
                    f"Sheet '{sheet_name}' ({len(sheet_df)} rows):\n"
                    + sheet_df.head(3).to_string(index=False)
                )
            sample = "\n\n".join(sample_parts)
        else:
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

        # Render list-like results (Series/ndarray/list from .unique(), filters,
        # etc.) as one exact value per line — never collapse via str() into an
        # ugly array repr. This keeps the executed, verbatim values intact
        # instead of falling back to the text model, which paraphrases names.
        if hasattr(result, "tolist"):          # numpy ndarray / pandas Series
            items = result.tolist()
            text = "\n".join(f"- {x}" for x in items)
        elif isinstance(result, (list, tuple, set)):
            text = "\n".join(f"- {x}" for x in result)
        elif hasattr(result, "to_string"):     # DataFrame
            text = result.to_string(index=False)
        else:
            text = str(result)

        return self._clean_datetime_strings(text)

    @staticmethod
    def _clean_datetime_strings(text: str) -> str:
        """Strip fake time/date parts from datetime strings in output.

        - '2023-03-09 00:00:00' → '2023-03-09' (midnight = date only)
        - '1900-01-01 14:30:00' → '14:30:00'   (placeholder date = time only)
        """
        # Remove midnight timestamps (date-only values)
        text = re.sub(r'(\d{4}-\d{2}-\d{2})\s+00:00:00(?:\.0+)?', r'\1', text)
        # Remove placeholder date for time-only values
        text = re.sub(r'1900-01-01\s+(\d{2}:\d{2}:\d{2})', r'\1', text)
        return text

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
        # Validator/reconcile calls don't need the model's full output window
        # but the old 1024 cap was too small — answers were getting truncated.
        # Use the model's full output ceiling, capped at 8192 to keep one-shot
        # validation cheap.
        one_shot_tokens = min(get_output_tokens(provider, model), 8192)

        if provider == "anthropic":
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            resp = client.messages.create(
                model=model,
                max_tokens=one_shot_tokens,
                system=system,
                messages=messages,
            )
            return resp.content[0].text

        elif provider == "openai":
            import openai
            client = openai.OpenAI(api_key=api_key)
            full_messages = [{"role": "system", "content": system}, *messages]
            token_kwargs: dict = {}
            if is_reasoning_model(provider, model):
                token_kwargs["max_completion_tokens"] = one_shot_tokens
            else:
                token_kwargs["max_tokens"] = one_shot_tokens
            resp = client.chat.completions.create(
                model=model,
                messages=full_messages,
                **token_kwargs,
            )
            return resp.choices[0].message.content

        elif provider == "google":
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            gmodel = genai.GenerativeModel(
                model_name=model,
                system_instruction=system,
                generation_config={"max_output_tokens": one_shot_tokens},
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
        """Build system prompt with document context and intent framing."""
        prompt = SYSTEM_PROMPT
        if self.document_content:
            prompt += (
                f"\n\nThe user has the following document open: {self.document_path}\n\n"
                f"<document_content>\n{self.document_content}\n</document_content>"
            )

        interp = self._last_interpretation
        if interp is not None:
            framing = interp.to_task_framing()
            prompt += f"\n\n<task_framing>\n{framing}\n</task_framing>"
            if interp.relevant_excerpts:
                joined = "\n\n---\n\n".join(interp.relevant_excerpts)
                prompt += (
                    "\n\n<likely_relevant_sections>\n"
                    "These excerpts from the document scored highest against the "
                    "user's keywords. Prefer answering from them when sufficient, "
                    "but fall back to the full document if they don't cover the "
                    "question.\n\n"
                    f"{joined}\n"
                    "</likely_relevant_sections>"
                )
        return prompt

    def consume_last_interpretation(self) -> Optional[Interpretation]:
        """Pop and return the interpretation from the most recent ask() call."""
        interp = self._last_interpretation
        self._last_interpretation = None
        return interp

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

        # Stream: the SDK rejects non-streaming requests whose max_tokens could
        # exceed a 10-minute response, which every current model's output
        # ceiling does.
        with self._client.messages.stream(
            model=self._model,
            max_tokens=self._output_tokens,
            system=self._build_system_prompt(),
            messages=messages,
        ) as stream:
            response = stream.get_final_message()
        return next(b.text for b in response.content if b.type == "text")

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

        # Reasoning models (o3-mini, etc.) require max_completion_tokens and
        # reject max_tokens. Detect via the per-model spec in config.
        token_kwargs: dict = {}
        if is_reasoning_model(self._provider, self._model):
            token_kwargs["max_completion_tokens"] = self._output_tokens
        else:
            token_kwargs["max_tokens"] = self._output_tokens

        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            **token_kwargs,
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
                generation_config={"max_output_tokens": self._output_tokens},
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
            "filter_by_threshold": math_tools.decimal_filter_by_threshold,
            "top_n": math_tools.decimal_top_n,
            # Extended specialist tools
            "dpo": math_tools.decimal_dpo,
            "dio": math_tools.decimal_dio,
            "cash_conversion_cycle": math_tools.decimal_cash_conversion_cycle,
            "inventory_turnover": math_tools.decimal_inventory_turnover,
            "interest_coverage": math_tools.decimal_interest_coverage,
            "debt_service_coverage": math_tools.decimal_debt_service_coverage,
            "contribution_margin": math_tools.decimal_contribution_margin,
            "break_even": math_tools.decimal_break_even,
            "wacc": math_tools.decimal_wacc,
            "xnpv": math_tools.decimal_xnpv,
            "xirr": math_tools.decimal_xirr,
            "moving_average": math_tools.decimal_moving_average,
            "exponential_smoothing": math_tools.decimal_exponential_smoothing,
            "z_score": math_tools.decimal_z_score,
            "percentile": math_tools.decimal_percentile,
            "correlation": math_tools.decimal_correlation,
            "volume_price_mix": math_tools.decimal_volume_price_mix,
            "value_at_risk": math_tools.decimal_value_at_risk,
            "loan_payment": math_tools.decimal_loan_payment,
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
