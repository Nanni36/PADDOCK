"""
PADDOCK — motore di raccolta calendari track day.

Questo modulo contiene il cuore del sistema:
  1. il modello dati di un evento          -> Evento
  2. la normalizzazione dei nomi circuito  -> normalizza_circuito()
  3. il riconoscimento delle date italiane -> leggi_data()
  4. l'eliminazione dei doppioni           -> deduplica()
  5. l'esportazione per il sito            -> esporta()

Il principio: ogni organizzatore pubblica i suoi dati come vuole
(tabella HTML, calendario ICS, PDF, foglio Excel). Ogni "adattatore"
in adattatori.py sa leggere UN formato e restituisce sempre lo stesso
oggetto Evento. Il resto del sistema non sa e non deve sapere da dove
arrivano i dati.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from pathlib import Path

# --------------------------------------------------------------------------
# 1. MODELLO DATI
# --------------------------------------------------------------------------


@dataclass
class Evento:
    """Un giorno in pista, come lo vedrà l'utente finale."""

    circuito: str                    # nome canonico, es. "Misano World Circuit"
    data: date                       # giorno dell'evento
    organizzatore: str               # chi lo organizza
    fonte_url: str                   # da dove l'abbiamo preso (tracciabilità)
    paese: str = "IT"
    prezzo: float | None = None      # in euro, None se non pubblicato
    posti_liberi: int | None = None
    posti_totali: int | None = None
    livelli: list[str] = field(default_factory=list)   # Base / Intermedio / Avanzato
    url_iscrizione: str | None = None
    note: str | None = None

    # ---- chiave di identità -------------------------------------------------
    @property
    def chiave(self) -> tuple:
        """
        Due righe con la stessa chiave sono lo STESSO evento reale.
        Circuito + data + organizzatore: se lo stesso organizzatore fa due
        turni lo stesso giorno sullo stesso circuito, per il pilota è
        comunque una sola giornata prenotabile.
        """
        return (self.circuito, self.data, _semplifica(self.organizzatore))

    def a_dizionario(self) -> dict:
        d = asdict(self)
        d["data"] = self.data.isoformat()
        return d


# --------------------------------------------------------------------------
# 2. NORMALIZZAZIONE CIRCUITI
# --------------------------------------------------------------------------

def _semplifica(testo: str) -> str:
    """Minuscolo, senza accenti, senza punteggiatura, spazi compattati."""
    testo = unicodedata.normalize("NFKD", testo)
    testo = "".join(c for c in testo if not unicodedata.combining(c))
    testo = re.sub(r"[^a-z0-9 ]+", " ", testo.lower())
    return re.sub(r"\s+", " ", testo).strip()


# Parole che compaiono ovunque e non aiutano a distinguere un circuito.
_RUMORE = {
    "circuito", "circuit", "autodromo", "autodrom", "automotodrom",
    "internazionale", "international", "world", "di", "de", "del", "della",
    "raceway", "ring", "park", "speedway", "pista", "track",
}


def _impronta(nome: str) -> frozenset:
    """Insieme delle parole significative di un nome di circuito."""
    return frozenset(_semplifica(nome).split()) - _RUMORE


class RegistroCircuiti:
    """
    Riconosce che "Misano", "MWC Marco Simoncelli" e
    "Autodromo Internazionale di Misano" sono lo stesso posto.

    Il file dati/circuiti.json contiene il nome canonico e gli alias noti.
    Se arriva un nome mai visto, viene segnalato invece che scartato in
    silenzio: i buchi nei dati vanno visti, non nascosti.
    """

    def __init__(self, percorso: Path):
        self._voci = json.loads(percorso.read_text(encoding="utf-8"))
        self._indice: dict[frozenset, dict] = {}
        for voce in self._voci:
            for nome in [voce["nome"]] + voce.get("alias", []):
                impronta = _impronta(nome)
                if impronta:
                    self._indice[impronta] = voce
        self.sconosciuti: set[str] = set()

    def risolvi(self, nome_grezzo: str) -> tuple[str, str]:
        """Restituisce (nome canonico, paese). Non solleva eccezioni."""
        impronta = _impronta(nome_grezzo)

        # corrispondenza esatta
        if impronta in self._indice:
            v = self._indice[impronta]
            return v["nome"], v["paese"]

        # corrispondenza parziale: "misano" dentro "misano world circuit"
        candidati = [
            (len(k & impronta), v)
            for k, v in self._indice.items()
            if k & impronta
        ]
        if candidati:
            candidati.sort(key=lambda x: -x[0])
            v = candidati[0][1]
            return v["nome"], v["paese"]

        self.sconosciuti.add(nome_grezzo.strip())
        return nome_grezzo.strip(), "??"


# --------------------------------------------------------------------------
# 3. DATE
# --------------------------------------------------------------------------

_MESI = {
    "gennaio": 1, "gen": 1, "january": 1, "jan": 1,
    "febbraio": 2, "feb": 2, "february": 2,
    "marzo": 3, "mar": 3, "march": 3,
    "aprile": 4, "apr": 4, "april": 4,
    "maggio": 5, "mag": 5, "may": 5,
    "giugno": 6, "giu": 6, "june": 6, "jun": 6,
    "luglio": 7, "lug": 7, "july": 7, "jul": 7,
    "agosto": 8, "ago": 8, "august": 8, "aug": 8,
    "settembre": 9, "set": 9, "sett": 9, "september": 9, "sep": 9,
    "ottobre": 10, "ott": 10, "october": 10, "oct": 10,
    "novembre": 11, "nov": 11, "november": 11,
    "dicembre": 12, "dic": 12, "december": 12, "dec": 12,
}


def leggi_data(testo: str, anno_predefinito: int | None = None) -> date | None:
    """
    Legge le forme più comuni sui siti degli organizzatori:
        12/09/2026 · 12-09-26 · 12 settembre 2026 · sab 12 set · 2026-09-12
    Restituisce None se non riconosce nulla: meglio un buco dichiarato
    che una data inventata.
    """
    if not testo:
        return None
    t = _semplifica(testo)
    anno_predefinito = anno_predefinito or date.today().year

    # forma ISO
    m = re.search(r"(20\d{2})[ /-](\d{1,2})[ /-](\d{1,2})", t)
    if m:
        a, me, g = map(int, m.groups())
        return _costruisci(a, me, g)

    # forma numerica europea
    m = re.search(r"\b(\d{1,2})[ /.-](\d{1,2})(?:[ /.-](\d{2,4}))?\b", t)
    if m:
        g, me, a = m.group(1), m.group(2), m.group(3)
        anno = int(a) if a else anno_predefinito
        if anno < 100:
            anno += 2000
        return _costruisci(anno, int(me), int(g))

    # forma testuale
    m = re.search(r"\b(\d{1,2})\s+([a-z]+)\s*(\d{4})?", t)
    if m and m.group(2) in _MESI:
        anno = int(m.group(3)) if m.group(3) else anno_predefinito
        return _costruisci(anno, _MESI[m.group(2)], int(m.group(1)))

    return None


def _costruisci(anno: int, mese: int, giorno: int) -> date | None:
    try:
        return date(anno, mese, giorno)
    except ValueError:
        return None


def leggi_prezzo(testo: str) -> float | None:
    """Estrae il primo importo in euro: '€ 250,00' · '250 EUR' · 'da 180€'."""
    if not testo:
        return None
    m = re.search(r"(\d{1,4})(?:[.,](\d{1,2}))?\s*(?:€|eur)", testo.lower())
    if not m:
        m = re.search(r"(?:€|eur)\s*(\d{1,4})(?:[.,](\d{1,2}))?", testo.lower())
    if not m:
        return None
    intero, dec = m.group(1), m.group(2) or "0"
    return float(f"{intero}.{dec.ljust(2, '0')}")


# --------------------------------------------------------------------------
# 4. DOPPIONI
# --------------------------------------------------------------------------

def deduplica(eventi: list[Evento]) -> list[Evento]:
    """
    Lo stesso evento può arrivare da più fonti (sito del circuito +
    sito dell'organizzatore). Teniamo la versione più ricca: quella
    con più campi valorizzati.
    """
    migliori: dict[tuple, Evento] = {}
    for e in eventi:
        esistente = migliori.get(e.chiave)
        if esistente is None or _ricchezza(e) > _ricchezza(esistente):
            migliori[e.chiave] = e
    return sorted(migliori.values(), key=lambda e: (e.data, e.circuito))


def _ricchezza(e: Evento) -> int:
    campi = [e.prezzo, e.posti_liberi, e.posti_totali, e.url_iscrizione]
    return sum(1 for c in campi if c is not None) + len(e.livelli)


# --------------------------------------------------------------------------
# 5. ESPORTAZIONE
# --------------------------------------------------------------------------

def esporta(eventi: list[Evento], percorso: Path, solo_futuri: bool = True) -> dict:
    """Scrive il JSON che alimenta il sito e restituisce un riepilogo."""
    oggi = date.today()
    selezionati = [e for e in eventi if not solo_futuri or e.data >= oggi]

    pacchetto = {
        "aggiornato": datetime.now().isoformat(timespec="seconds"),
        "totale": len(selezionati),
        "eventi": [e.a_dizionario() for e in selezionati],
    }
    percorso.parent.mkdir(parents=True, exist_ok=True)
    percorso.write_text(
        json.dumps(pacchetto, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return {
        "scritti": len(selezionati),
        "scartati_passati": len(eventi) - len(selezionati),
        "circuiti": len({e.circuito for e in selezionati}),
        "organizzatori": len({e.organizzatore for e in selezionati}),
    }
