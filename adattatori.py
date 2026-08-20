ADATTATORI — uno per ogni formato in cui un organizzatore pubblica il calendario.

Ogni adattatore riceve del testo grezzo (HTML, ICS, CSV) e restituisce
una lista di Evento. Se un sito cambia struttura, si aggiusta il suo
adattatore e basta: il resto del sistema non si accorge di nulla.

Aggiungere un nuovo organizzatore = aggiungere una riga in fonti.py,
non riscrivere codice.
"""

from __future__ import annotations

import csv
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from core import Evento, RegistroCircuiti, leggi_data, leggi_prezzo, _costruisci
from core import _MESI, _semplifica

INTESTAZIONI = {
    # Ci presentiamo. Un bot che si nasconde è un bot che si fa bloccare.
    "User-Agent": "PaddockBot/0.1 (aggregatore calendari track day; contatto: tuamail@esempio.it)"
}
TIMEOUT = 20


# --------------------------------------------------------------------------

class AccessoNegato(Exception):
    """Il sito vieta l'accesso automatico nel suo robots.txt."""


_ROBOT_CACHE: dict[str, RobotFileParser] = {}


def robots_permette(url: str) -> bool:
    """
    Legge il robots.txt del sito e dice se possiamo leggere questa pagina.

    robots.txt e' il cartello all'ingresso di un sito: dice ai programmi
    automatici dove possono entrare. Non e' una barriera tecnica, e'
    una richiesta. Rispettarla e' la differenza fra essere un servizio
    
