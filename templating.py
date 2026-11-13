"""Renderização simples de templates: substitui {{VARIAVEL}} pelo valor."""
from __future__ import annotations

import re
from typing import Mapping

_PATTERN = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


class TemplateError(Exception):
    """Erro ao renderizar um template."""


def render(text: str, variables: Mapping[str, object]) -> str:
    def replace(match: "re.Match[str]") -> str:
        key = match.group(1)
        if key not in variables:
            raise TemplateError(f"variável não definida: {key}")
        return str(variables[key])

    return _PATTERN.sub(replace, text)
