"""Glossary loading for translation and ASR hints.

Two formats are accepted:
- Markdown (.md): every table row whose first cell contains Japanese is read as
  | 日本語 | English | (optional note) |. This lets a course glossary such as
  lec-ml/2026/GLOSSARY-en.md stay the single source of truth.
- YAML (.yaml/.yml): {"terms": [{"ja": ..., "en": ..., "note": ...}], "asr_hints": [...]}
"""
import os
import re
from dataclasses import dataclass, field

import yaml

_JA = re.compile(r"[぀-ヿ一-鿿]")


@dataclass
class Glossary:
    terms: list = field(default_factory=list)       # [(ja, en, note)]
    asr_hints: list = field(default_factory=list)   # Japanese words to bias ASR toward

    def prompt_block(self):
        """Glossary lines for the translation system prompt"""
        lines = []
        for ja, en, note in self.terms:
            lines.append(f"- {ja} = {en}" + (f"  ({note})" if note else ""))
        return "\n".join(lines)

    def asr_prompt(self):
        return "、".join(self.asr_hints)


def _clean(cell):
    cell = cell.replace("**", "").replace("`", "").strip()
    return re.sub(r"<br\s*/?>", " ", cell)


def _load_markdown(path):
    terms = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line.startswith("|") or set(line) <= set("|-: "):
            continue
        cells = [_clean(c) for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        # Round-title tables start with a number column: | 2 | 確率統計の基礎 | Foundations ... |
        if cells[0].isdigit() and len(cells) >= 3:
            cells = cells[1:]
        ja, en = cells[0], cells[1]
        if not _JA.search(ja) or ja == "日本語" or not en:
            continue
        note = cells[2] if len(cells) > 2 else ""
        terms.append((ja, en, note))
    return terms


def _load_yaml(path):
    data = yaml.safe_load(open(path, encoding="utf-8")) or {}
    terms = [(t["ja"], t["en"], t.get("note", "")) for t in data.get("terms", [])]
    return terms, list(data.get("asr_hints", []))


def load_glossary(paths):
    g = Glossary()
    for path in paths:
        path = os.path.expanduser(path.strip())
        if not path:
            continue
        if not os.path.exists(path):
            print(f"[Glossary] Warning: not found: {path}")
            continue
        if path.endswith((".yaml", ".yml")):
            terms, hints = _load_yaml(path)
            g.terms += terms
            g.asr_hints += hints
        else:
            g.terms += _load_markdown(path)
        print(f"[Glossary] Loaded {path}")
    print(f"[Glossary] {len(g.terms)} terms, {len(g.asr_hints)} ASR hints")
    return g
