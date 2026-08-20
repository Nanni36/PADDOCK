"""
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

from core import Evento, RegistroCircuiti, leggi_data, leggi_prezzo
from core import _MESI

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
    e essere un problema — e questi sono gli stessi organizzatori a cui
    poi dovrai chiedere una commissione.
    """
    pezzi = urlsplit(url)
    radice = f"{pezzi.scheme}://{pezzi.netloc}"

    if radice not in _ROBOT_CACHE:
        rp = RobotFileParser()
        rp.set_url(radice + "/robots.txt")
        try:
            rp.read()
        except Exception:
            rp.allow_all = True      # nessun robots.txt raggiungibile: si procede
        _ROBOT_CACHE[radice] = rp

    return _ROBOT_CACHE[radice].can_fetch(INTESTAZIONI["User-Agent"], url)


def scarica(url: str, ignora_robots: bool = False) -> str:
    """
    ignora_robots va messo a True SOLO per un sito che ti ha dato
    il permesso esplicito (una mail dell'organizzatore, un accordo).
    Non e' un interruttore da usare per comodita'.
    """
    if not ignora_robots and not robots_permette(url):
        raise AccessoNegato(
            f"{urlsplit(url).netloc} vieta l'accesso automatico nel robots.txt. "
            "Scrivi all'organizzatore e chiedi il permesso o il calendario."
        )
    r = requests.get(url, headers=INTESTAZIONI, timeout=TIMEOUT)
    r.raise_for_status()
    r.encoding = r.encoding or "utf-8"
    return r.text


# --------------------------------------------------------------------------
# A. TABELLA HTML  (il caso più frequente sui siti italiani)
# --------------------------------------------------------------------------

def da_tabella_html(
    html: str,
    registro: RegistroCircuiti,
    organizzatore: str,
    fonte_url: str,
    selettore_riga: str,
    colonne: dict[str, int],
    anno_predefinito: int | None = None,
) -> list[Evento]:
    """
    colonne indica in quale posizione sta ogni informazione, es.:
        {"data": 0, "circuito": 1, "prezzo": 2, "posti": 3}
    Le colonne assenti si omettono e restano None.
    """
    zuppa = BeautifulSoup(html, "lxml")
    eventi: list[Evento] = []

    for riga in zuppa.select(selettore_riga):
        celle = [c.get_text(" ", strip=True) for c in riga.find_all(["td", "th"])]
        if len(celle) < 2:
            continue

        def cella(nome: str) -> str:
            i = colonne.get(nome)
            return celle[i] if i is not None and i < len(celle) else ""

        giorno = leggi_data(cella("data"), anno_predefinito)
        grezzo_circuito = cella("circuito")
        if not giorno or not grezzo_circuito:
            continue  # riga incompleta: si salta, senza inventare

        nome, paese = registro.risolvi(grezzo_circuito)
        collegamento = riga.find("a", href=True)

        eventi.append(
            Evento(
                circuito=nome,
                paese=paese,
                data=giorno,
                organizzatore=organizzatore,
                prezzo=leggi_prezzo(cella("prezzo")),
                posti_liberi=_intero(cella("posti")),
                livelli=_livelli(cella("livelli")),
                url_iscrizione=collegamento["href"] if collegamento else None,
                fonte_url=fonte_url,
            )
        )
    return eventi


# --------------------------------------------------------------------------
# B. CALENDARIO ICS  (chi usa Google Calendar o WordPress Events)
# --------------------------------------------------------------------------

def da_ics(
    testo: str,
    registro: RegistroCircuiti,
    organizzatore: str,
    fonte_url: str,
) -> list[Evento]:
    """Legge un .ics senza dipendenze esterne: il formato è semplice."""
    eventi: list[Evento] = []
    blocchi = re.split(r"BEGIN:VEVENT", testo)[1:]

    for blocco in blocchi:
        titolo = _campo_ics(blocco, "SUMMARY")
        luogo = _campo_ics(blocco, "LOCATION")
        inizio = _campo_ics(blocco, "DTSTART")
        if not inizio:
            continue

        m = re.search(r"(\d{4})(\d{2})(\d{2})", inizio)
        if not m:
            continue
        giorno = date(*map(int, m.groups()))

        nome, paese = registro.risolvi(luogo or titolo)
        eventi.append(
            Evento(
                circuito=nome,
                paese=paese,
                data=giorno,
                organizzatore=organizzatore,
                prezzo=leggi_prezzo(_campo_ics(blocco, "DESCRIPTION")),
                fonte_url=fonte_url,
                note=titolo or None,
            )
        )
    return eventi


def _campo_ics(blocco: str, chiave: str) -> str:
    m = re.search(rf"^{chiave}[^:]*:(.*)$", blocco, re.MULTILINE)
    return m.group(1).strip() if m else ""


# --------------------------------------------------------------------------
# C. CSV MANUALE  (per gli organizzatori che pubblicano solo su Facebook)
# --------------------------------------------------------------------------

def da_csv(percorso: Path, registro: RegistroCircuiti) -> list[Evento]:
    """
    Intestazioni attese:
        data,circuito,organizzatore,prezzo,posti_liberi,posti_totali,livelli,url

    All'inizio molti eventi li inserirai a mano. Va benissimo: è così che
    parte ogni aggregatore. L'automazione viene dopo, quando sai già
    quali fonti valgono la fatica.
    """
    if not percorso.exists():
        return []

    eventi: list[Evento] = []
    with percorso.open(encoding="utf-8") as f:
        for riga in csv.DictReader(f):
            giorno = leggi_data(riga.get("data", ""))
            if not giorno:
                continue
            nome, paese = registro.risolvi(riga.get("circuito", ""))
            eventi.append(
                Evento(
                    circuito=nome,
                    paese=paese,
                    data=giorno,
                    organizzatore=riga.get("organizzatore", "").strip(),
                    prezzo=leggi_prezzo(riga.get("prezzo", "")),
                    posti_liberi=_intero(riga.get("posti_liberi", "")),
                    posti_totali=_intero(riga.get("posti_totali", "")),
                    livelli=_livelli(riga.get("livelli", "")),
                    url_iscrizione=riga.get("url") or None,
                    fonte_url="inserimento manuale",
                )
            )
    return eventi


# --------------------------------------------------------------------------

def _intero(testo: str) -> int | None:
    m = re.search(r"\d+", testo or "")
    return int(m.group()) if m else None


def _livelli(testo: str) -> list[str]:
    if not testo:
        return []
    t = testo.lower()
    trovati = []
    for chiave, etichetta in [
        ("base", "Base"), ("principiant", "Base"), ("verde", "Base"), ("slow", "Base"),
        ("intermedi", "Intermedio"), ("giall", "Intermedio"), ("medium", "Intermedio"),
        ("avanzat", "Avanzato"), ("ross", "Avanzato"), ("fast", "Avanzato"), ("expert", "Avanzato"),
    ]:
        if chiave in t and etichetta not in trovati:
            trovati.append(etichetta)
    return trovati


# --------------------------------------------------------------------------
# D. GRIGLIA DI PULSANTI  (Elementor, WordPress: il secondo formato piu' diffuso)
# --------------------------------------------------------------------------

_GIORNI_SETTIMANA = {
    "lun": 0, "mar": 1, "mer": 2, "gio": 3, "ven": 4, "sab": 5, "dom": 6,
}

_NOMI_MESI = "|".join([
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
])


def da_griglia_pulsanti(
    html: str,
    registro: RegistroCircuiti,
    organizzatore: str,
    fonte_url: str,
    selettore: str,
    anno: int,
) -> tuple[list[Evento], list[str]]:
    """
    Legge un calendario fatto di riquadri cliccabili invece che di tabella.

    Ogni riquadro contiene una riga come:
        LUN. 30 MARZO MISANO
        SAB.11+DOM.12 LUGLIO MAGIONE     <- evento su due giorni

    La regola di lettura: si cerca il nome del mese; i numeri PRIMA di
    esso sono i giorni, il testo DOPO e' il circuito. Regge tutte le
    varianti viste senza dover indovinare le posizioni.

    Gli eventi su piu' giorni vengono spezzati in una data ciascuno,
    altrimenti chi cerca la domenica non trova la giornata.

    Restituisce (eventi, avvisi). Gli avvisi non fermano nulla: servono
    a farti vedere cosa il programma non ha capito, invece di nasconderlo.
    """
    zuppa = BeautifulSoup(html, "lxml")
    eventi: list[Evento] = []
    avvisi: list[str] = []

    for nodo in zuppa.select(selettore):
        testo = " ".join(nodo.get_text(" ", strip=True).split())
        if not testo:
            continue

        m = re.search(rf"\b({_NOMI_MESI})\b", testo, re.IGNORECASE)
        if not m:
            continue                                    # non e' una data: si ignora

        mese = _MESI[m.group(1).lower()]
        giorni = [int(g) for g in re.findall(r"\d{1,2}", testo[: m.start()])]
        grezzo_circuito = testo[m.end():].strip(" .-–—")

        if not giorni or not grezzo_circuito:
            avvisi.append(f"riquadro non interpretabile: {testo!r}")
            continue

        nome, paese = registro.risolvi(grezzo_circuito)
        link = nodo.get("href") or (
            nodo.find("a", href=True)["href"] if nodo.find("a", href=True) else None
        )

        # Il giorno della settimana scritto sul riquadro serve a verificare
        # l'anno: se non coincide, l'anno configurato e' sbagliato.
        sigla = re.match(r"\s*([a-zA-Z]{3})", testo)
        atteso = _GIORNI_SETTIMANA.get(sigla.group(1).lower()) if sigla else None

        for giorno in giorni:
            try:
                quando = date(anno, mese, giorno)
            except ValueError:
                avvisi.append(f"data inesistente: {giorno}/{mese}/{anno} in {testo!r}")
                continue

            if atteso is not None and len(giorni) == 1 and quando.weekday() != atteso:
                avvisi.append(
                    f"{testo!r}: il {quando} non e' {sigla.group(1).lower()} — "
                    f"controlla l'anno configurato ({anno})"
                )

            eventi.append(
                Evento(
                    circuito=nome,
                    paese=paese,
                    data=quando,
                    organizzatore=organizzatore,
                    url_iscrizione=link,
                    fonte_url=fonte_url,
                )
            )

    return eventi, avvisi
