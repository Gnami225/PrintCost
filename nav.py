"""Registre des pages (renseigné par ``app.py`` à chaque exécution).

Permet aux pages de créer des liens (``st.page_link``) et de naviguer
(``st.switch_page``) sans importer ``app.py``.
"""

from __future__ import annotations

from typing import Any

PAGES: dict[str, Any] = {}


def page(nom: str) -> Any:
    return PAGES[nom]
