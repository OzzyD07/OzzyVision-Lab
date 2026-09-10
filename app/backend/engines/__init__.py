"""Engines package"""
from app.backend.engines.base import BaseVideoEngine
from app.backend.engines.ltx25.engine import LTX25Engine
from app.backend.engines.minimax_h3.engine import MiniMaxH3Engine

ENGINES = {
    "ltx25": LTX25Engine(),
    "minimax_h3": MiniMaxH3Engine()
}

def get_engine(name: str = "ltx25") -> BaseVideoEngine:
    return ENGINES.get(name, ENGINES["ltx25"])

