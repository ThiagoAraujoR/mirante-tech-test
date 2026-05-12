"""Configurações compartilhadas dos testes."""

from __future__ import annotations

import sys
from pathlib import Path

# Permite importar `modernizer` sem instalar o pacote.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
