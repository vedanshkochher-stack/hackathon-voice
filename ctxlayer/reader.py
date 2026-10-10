"""The one function every consumer needs: read a context file into (meta, sections).

Bots, dashboards, campaign jobs and exec call-prep all use this; none of them touch the builder,
the event store or the source APIs. That separation is what makes the files reusable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .config import CONTEXT_DIR


@dataclass
class Context:
    meta: dict
    body: str
    sections: dict[str, list[str]] = field(default_factory=dict)
    path: Path | None = None
    raw: str = ""

    @property
    def title(self) -> str:
        return self.body.splitlines()[0].lstrip("# ").strip() if self.body else ""

    @property
    def headline(self) -> str:
        for line in self.body.splitlines():
            if line.startswith("> "):
                return line[2:]
        return ""


def parse(text: str, path: Path | None = None) -> Context:
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        raise ValueError("not an imctx file: missing frontmatter")
    meta, body = yaml.safe_load(m.group(1)), m.group(2)
    sections, cur = {}, "_head"
    for line in body.splitlines():
        if line.startswith("## "):
            cur = re.sub(r"\s*\(.*\)$", "", line[3:]).strip()
            sections[cur] = []
        elif line.strip():
            sections.setdefault(cur, []).append(line)
    return Context(meta=meta, body=body, sections=sections, path=path, raw=text)


def path_for(glid: str, role: str, root: Path = CONTEXT_DIR) -> Path:
    return root / str(glid) / f"{role}.md"


def read(glid: str, role: str, root: Path = CONTEXT_DIR) -> Context | None:
    p = path_for(glid, role, root)
    if not p.exists():
        return None
    return parse(p.read_text(encoding="utf-8"), p)


def read_all(role: str | None = None, root: Path = CONTEXT_DIR) -> list[Context]:
    out = []
    for p in sorted(root.glob("*/*.md")):
        if role and p.stem != role:
            continue
        out.append(parse(p.read_text(encoding="utf-8"), p))
    return out
