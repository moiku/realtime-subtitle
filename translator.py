from collections import deque
import os
import re
import threading

from openai import OpenAI, OpenAIError


SYSTEM_PROMPT = """You are a simultaneous interpreter producing live English subtitles for a university lecture{domain}, spoken in Japanese.
Each user message contains one segment of raw Japanese speech recognition (ASR) output.

Rules:
1. The ASR text has no punctuation and contains fillers (えー, あの, まあ, なんか), self-corrections and occasional misrecognitions. Drop fillers. For a self-correction keep only the corrected version. If a word looks misrecognized (e.g. a homophone), infer the intended term from context and the glossary.
2. A segment may be only part of a longer sentence. Translate just this segment so that it reads as a natural continuation of the previous subtitles. Never repeat content that was already translated, and never anticipate words that are not in this segment (a sentence may stay unfinished).
3. Always use the glossary translation for any listed term.
4. Japanese fractions read denominator first: "X分のY" means Y/X (6分の2 = 2/6, λ分の1 = 1/λ).
5. Preserve numbers, formulas, negations and who-did-what exactly. Do not add explanations or content that was not said.
6. Write concise, plain English suitable for subtitles.
7. Output only the English subtitle text. If the segment contains no content (only fillers or noise), output nothing.
{glossary}"""


class Translator:
    def __init__(self, api_key=None, base_url=None, model="gpt-4.1-mini", target_lang="English",
                 glossary=None, domain="", context_size=3):
        """
        Translates ASR segments with an LLM, using a glossary and the last few
        (source, translation) pairs as context. Calls are serialized by a lock
        so that the context stays in order.
        """
        self.target_lang = target_lang
        self.model = model

        # If no key provided, check env. If still none, we might be in local mode (no auth) or fail.
        # Some local servers don't need a valid key, but the client requires a string.
        if not api_key:
            api_key = os.getenv("OPENAI_API_KEY", "dummy-key-for-local")

        if not base_url:
            base_url = os.getenv("OPENAI_BASE_URL")

        self.base_url = base_url
        self.client = OpenAI(api_key=api_key, base_url=base_url)

        glossary_block = ""
        if glossary is not None and glossary.terms:
            glossary_block = "\nGlossary (Japanese = English):\n" + glossary.prompt_block()
        self.system_prompt = SYSTEM_PROMPT.format(
            domain=f" on {domain}" if domain else "", glossary=glossary_block)
        if target_lang != "English":
            self.system_prompt = self.system_prompt.replace("English", target_lang)

        # Logging
        print(f"[Translator] Initialized:")
        print(f"  - Base URL: {base_url or 'https://api.openai.com/v1 (default)'}")
        print(f"  - Model: {model}")
        print(f"  - Target Language: {target_lang}")
        print(f"  - Glossary terms: {len(glossary.terms) if glossary else 0}")
        print(f"  - API Key: {'set' if api_key != 'dummy-key-for-local' else 'not set'}")

        # Context carryover for sentence continuity
        self.history = deque(maxlen=context_size)
        self._lock = threading.Lock()

    def _strip_thinking(self, text):
        """Remove <think>...</think> tags from response (for reasoning models)"""
        # Remove think tags and their content
        cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
        return cleaned.strip()

    def _user_message(self, text):
        if not self.history:
            return f"Segment:\n{text}"
        ctx = "\n".join(f"JA: {ja}\nEN: {en}" for ja, en in self.history)
        return f"Previous segments (context only, do not translate again):\n{ctx}\n\nSegment:\n{text}"

    def translate(self, text, use_context=True):
        """
        Translates the given text. Returns the translated string.
        Uses previous segments as context for continuity.
        """
        if not text or not text.strip():
            return ""

        with self._lock:
            user = self._user_message(text) if use_context else f"Segment:\n{text}"
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        # System prompt is identical across calls, so it hits the prompt cache
                        {"role": "system", "content": self.system_prompt},
                        {"role": "user", "content": user}
                    ],
                    temperature=0.2,
                    max_tokens=500,
                    timeout=10.0     # 10s timeout to prevent hanging
                )
                result = self._strip_thinking(response.choices[0].message.content or "")
                self.history.append((text, result))
                return result
            except OpenAIError as e:
                print(f"Translation Error: {e}")
                return f"[Error: {e}]"
            except Exception as e:
                print(f"Unexpected Error: {e}")
                return text

if __name__ == "__main__":
    t = Translator()
    print(t.translate("こんにちは、今日は確率統計の基礎をやります"))
