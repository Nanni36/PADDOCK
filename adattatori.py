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


# --------------------------------------------------------------------------
# E. SCHEDE CON LINK  (card Bootstrap: il terzo formato diffuso)
# --------------------------------------------------------------------------

# Voci che compaiono nel calendario ma non sono giornate in pista.
_NON_EVENTI = {"buoni regalo", "buono regalo", "promozioni", "promozione",
               "gift card", "voucher", "abbonamento"}


def da_schede_link(
    html: str,
    registro: RegistroCircuiti,
    organizzatore: str,
    fonte_url: str,
    selettore: str,
    anno: int,
    selettore_titolo: str = "h3",
) -> tuple[list[Evento], list[str]]:
    """
    Legge un calendario fatto di schede cliccabili, dove il titolo contiene
    giorno, mese e circuito tutti insieme:

        31 AGOSTO | MUGELLO
        24 SETTEMBRE | MISANO

    Riconosce anche il semaforo della disponibilita' (verde/giallo/rosso)
    quando c'e', e il prezzo "a partire da".

    Le voci che non sono giornate in pista (buoni regalo, promozioni)
    vengono scartate: nel calendario ci stanno, sul portale no.
    """
    zuppa = BeautifulSoup(html, "lxml")
    eventi: list[Evento] = []
    avvisi: list[str] = []

    for scheda in zuppa.select(selettore):
        titolo_nodo = scheda.select_one(selettore_titolo)
        if not titolo_nodo:
            continue
        titolo = " ".join(titolo_nodo.get_text(" ", strip=True).split())

        m = re.search(rf"\b({_NOMI_MESI})\b", titolo, re.IGNORECASE)
        if not m:
            continue

        mese = _MESI[m.group(1).lower()]
        giorni = [int(g) for g in re.findall(r"\d{1,2}", titolo[: m.start()])]
        # dopo il mese resta "| MUGELLO" oppure "| MISANO Italia"
        coda = titolo[m.end():].strip(" |.-–—")
        grezzo_circuito = coda.split("|")[0].strip()

        if not giorni or not grezzo_circuito:
            avvisi.append(f"scheda non interpretabile: {titolo!r}")
            continue

        if _semplifica(grezzo_circuito) in _NON_EVENTI:
            continue                                   # buoni regalo e simili

        nome, paese = registro.risolvi(grezzo_circuito)
        link = scheda.get("href") or (
            scheda.find("a", href=True)["href"] if scheda.find("a", href=True) else None
        )
        if link:
            link = link.split("?")[0]                  # via i parametri di tracciamento
            if link.startswith("/"):
                link = urlsplit(fonte_url)._replace(path=link, query="").geturl()

        testo_scheda = scheda.get_text(" ", strip=True)
        disponibilita = _semaforo(scheda)

        # un intervallo tipo "03-31 DICEMBRE" non e' una giornata singola
        if len(giorni) > 4:
            avvisi.append(f"intervallo troppo largo, saltato: {titolo!r}")
            continue

        for giorno in giorni:
            try:
                quando = date(anno, mese, giorno)
            except ValueError:
                avvisi.append(f"data inesistente in {titolo!r}")
                continue

            eventi.append(
                Evento(
                    circuito=nome,
                    paese=paese,
                    data=quando,
                    organizzatore=organizzatore,
                    prezzo=leggi_prezzo(testo_scheda),
                    disponibilita=disponibilita,
                    url_iscrizione=link,
                    fonte_url=fonte_url,
                )
            )

    return eventi, avvisi


def _semaforo(scheda) -> str | None:
    """
    Rosso Corsa (e altri) non pubblicano quanti posti restano: mostrano
    un semaforo a tre luci. Restituiamo l'etichetta, non un numero.

    Tradurre un colore in "5 posti su 40" sarebbe inventare un dato che
    il lettore poi crede. Su un portale di prenotazioni un numero falso
    e' peggio di nessun numero: chi si fida e trova tutto esaurito non
    torna piu'.
    """
    for classe, etichetta in [("color1", "disponibile"),
                              ("color2", "esaurimento"),
                              ("color3", "esaurito")]:
        if scheda.select_one(f".{classe}.active-color"):
            return etichetta

    testo = _semplifica(scheda.get_text(" ", strip=True))
    if "lista di attesa" in testo or "esaurit" in testo:
        return "esaurito"
    return None


# --------------------------------------------------------------------------
# F. RIGHE A PIU' PREZZI  (una giornata, piu' tariffe, un semaforo ciascuna)
# --------------------------------------------------------------------------

# Ogni fascia di prezzo ha un suo semaforo: rappresentano quote diverse
# (intero, promozionale, scontato), non lo stesso posto contato due volte.
# Prendiamo come prezzo/disponibilita' ufficiali quello della tariffa
# "intera" — quella che chiunque puo' comprare, non riservata a soci o
# categorie specifiche. Se manca, si scende la scala verso lo sconto.
_PRIORITA_TARIFFA = ["intero", "scontato", "promozionale"]

_PAROLE_NON_EVENTO_RIGHE = ("assicura", "buono", "buoni", "voucher", "gift")


def da_righe_prezzo_multiplo(
    html: str,
    registro: RegistroCircuiti,
    organizzatore: str,
    fonte_url: str,
    selettore_riga: str,
    anno: int,
) -> tuple[list[Evento], list[str]]:
    """
    Legge calendari dove ogni giornata mostra piu' tariffe (intero,
    scontato, promozionale...), ciascuna con il proprio prezzo e il
    proprio semaforo di disponibilita' — perche' spesso sono contingenti
    separati (es. tariffa soci limitata) e non lo stesso posto.

    Gestisce anche i pacchetti di piu' giorni ("dal 4 al 6 settembre"),
    registrati sulla data di inizio con una nota sulla durata.
    """
    zuppa = BeautifulSoup(html, "lxml")
    eventi: list[Evento] = []
    avvisi: list[str] = []

    for riga in zuppa.select(selettore_riga):
        nodo_circuito = riga.select_one(".circuit-name")
        if not nodo_circuito:
            continue
        grezzo_circuito = nodo_circuito.get_text(strip=True)
        if any(p in _semplifica(grezzo_circuito) for p in _PAROLE_NON_EVENTO_RIGHE):
            continue                                   # assicurazioni, buoni: non sono giornate

        quando, fine = _leggi_data_riga(riga, anno)
        if not quando:
            avvisi.append(f"data non letta per {grezzo_circuito!r}")
            continue

        tariffe = _leggi_tariffe(riga)
        if not tariffe:
            avvisi.append(f"nessun prezzo trovato per {grezzo_circuito!r} il {quando}")
            continue

        etichetta, prezzo, disponibilita = _scegli_tariffa(tariffe)
        nome, paese = registro.risolvi(grezzo_circuito)
        link_nodo = riga.select_one("a[href*='/prodotto']")
        link = link_nodo["href"] if link_nodo else None
        if link and link.startswith("/"):
            link = urlsplit(fonte_url)._replace(path=link, query="").geturl()

        giorni_evento = (fine - quando).days + 1 if fine else 1

        eventi.append(
            Evento(
                circuito=nome,
                paese=paese,
                data=quando,
                organizzatore=organizzatore,
                prezzo=prezzo,
                disponibilita=disponibilita,
                url_iscrizione=link,
                fonte_url=fonte_url,
                giorni=giorni_evento,
                data_fine=fine,
            )
        )

    return eventi, avvisi


def _leggi_data_riga(riga, anno: int) -> tuple[date | None, date | None]:
    """
    Un giorno solo, o un intervallo 'dal ... al ...'.
    Restituisce (inizio, fine). fine e' None per un evento di un giorno solo:
    e' il segnale che il resto del programma usa per sapere se e' un
    pacchetto di piu' giorni, senza dover rileggere un testo.
    """
    giorno_solo = riga.select_one(".text-day")
    mese_solo = riga.select_one(".text-month")
    if giorno_solo and mese_solo:
        mese = _MESI.get(_semplifica(mese_solo.get_text()))
        if mese:
            return _costruisci(anno, mese, int(giorno_solo.get_text(strip=True))), None
        return None, None

    giorni_sm = riga.select(".text-day-sm")
    mesi_sm = riga.select(".text-month-sm")
    if len(giorni_sm) >= 2 and len(mesi_sm) >= 2:
        mese_inizio = _MESI.get(_semplifica(mesi_sm[0].get_text()))
        if not mese_inizio:
            return None, None
        inizio = _costruisci(anno, mese_inizio, int(giorni_sm[0].get_text(strip=True)))
        mese_fine = _MESI.get(_semplifica(mesi_sm[1].get_text()))
        fine = None
        if mese_fine and inizio:
            fine = _costruisci(anno, mese_fine, int(giorni_sm[1].get_text(strip=True)))
        return inizio, fine

    return None, None


def _leggi_tariffe(riga) -> list[tuple[str, float | None, str | None]]:
    """Restituisce (etichetta, prezzo, disponibilita') per ogni fascia trovata."""
    tariffe = []
    for sotto_riga in riga.select(".flex-item.flex-product"):
        etichetta_nodo = sotto_riga.select_one(".text-product")
        if not etichetta_nodo:
            continue
        etichetta = etichetta_nodo.get_text(" ", strip=True).rstrip(":")

        contenitore = sotto_riga.find_parent(
            "div", class_=lambda c: c and "justify-content-between" in c
        )
        if not contenitore:
            continue

        prezzo_nodo = contenitore.select_one(".text-price")
        prezzo = leggi_prezzo(prezzo_nodo.get_text()) if prezzo_nodo else None

        disponibilita = None
        for classe, etich in [("green", "disponibile"), ("yellow", "esaurimento"), ("red", "esaurito")]:
            if contenitore.select_one(f".light.{classe}"):
                disponibilita = etich
                break

        tariffe.append((etichetta, prezzo, disponibilita))
    return tariffe


def _scegli_tariffa(tariffe: list[tuple[str, float | None, str | None]]):
    """
    Sceglie la tariffa da mostrare come prezzo principale del portale.
    Scarta i pacchetti multi-giorno facoltativi tipo "(SAB+DOM)": quelli
    sono un extra opzionale, non la tariffa base della giornata.
    """
    candidate = [t for t in tariffe if "(" not in t[0]]
    if not candidate:
        candidate = tariffe

    for chiave in _PRIORITA_TARIFFA:
        for etichetta, prezzo, disp in candidate:
            if chiave in _semplifica(etichetta):
                return etichetta, prezzo, disp

    return candidate[0]


# --------------------------------------------------------------------------
# G. GRIGLIA CON DISPONIBILITA' ESPLICITA  (l'anno sta nella classe del link)
# --------------------------------------------------------------------------

_STATO_TESTO = {
    "disponibile": "disponibile",
    "disponibilita limitata": "esaurimento",
    "esaurito": "esaurito",
}


def da_griglia_disponibilita(
    html: str,
    registro: RegistroCircuiti,
    organizzatore: str,
    fonte_url: str,
    selettore: str,
    selettore_data: str = ".event__date",
    selettore_circuito: str = ".event__type",
    selettore_titolo: str = ".event__place",
    selettore_stato: str = ".event__available",
) -> tuple[list[Evento], list[str]]:
    """
    Legge calendari dove ogni scheda porta l'anno e il mese scritti in una
    classe CSS (es. "mnt202608") e la disponibilita' come parola scritta
    per intero ("Disponibile", "Disponibilita' limitata", "Esaurito")
    invece che come colore. L'anno preso dalla classe e' un fatto, non
    una supposizione: niente da verificare contro il giorno della
    settimana come nella griglia a pulsanti.

    Non pubblica prezzi in questa pagina: restano None, non inventati.
    """
    zuppa = BeautifulSoup(html, "lxml")
    eventi: list[Evento] = []
    avvisi: list[str] = []

    for scheda in zuppa.select(selettore):
        classi = " ".join(scheda.get("class", []))
        m_mese = re.search(r"mnt(\d{4})(\d{2})", classi)
        nodo_data = scheda.select_one(selettore_data)
        if not m_mese or not nodo_data:
            continue

        m_giorno = re.search(r"\d{1,2}", nodo_data.get_text())
        if not m_giorno:
            avvisi.append(f"giorno non letto nella scheda: {nodo_data.get_text()!r}")
            continue

        anno, mese = int(m_mese.group(1)), int(m_mese.group(2))
        quando = _costruisci(anno, mese, int(m_giorno.group()))
        if not quando:
            avvisi.append(f"data inesistente: {m_giorno.group()}/{mese}/{anno}")
            continue

        nodo_circuito = scheda.select_one(selettore_circuito)
        if not nodo_circuito:
            continue
        nome, paese = registro.risolvi(nodo_circuito.get_text(strip=True))

        nodo_stato = scheda.select_one(selettore_stato)
        disponibilita = None
        if nodo_stato:
            disponibilita = _STATO_TESTO.get(_semplifica(nodo_stato.get_text()))

        nodo_titolo = scheda.select_one(selettore_titolo)
        titolo = nodo_titolo.get_text(strip=True) if nodo_titolo else ""
        # "Prove moto" e' il turno generico: non aggiunge nulla come nota.
        # Un titolo diverso (evento speciale, giornata a tema) merita di
        # comparire, perche' cambia cosa il pilota trova quel giorno.
        nota = titolo if titolo and _semplifica(titolo) != "prove moto" else None

        link = scheda.get("href")
        if link and link.startswith("/"):
            link = urlsplit(fonte_url)._replace(path=link, query="", fragment="").geturl()

        eventi.append(
            Evento(
                circuito=nome,
                paese=paese,
                data=quando,
                organizzatore=organizzatore,
                disponibilita=disponibilita,
                url_iscrizione=link,
                fonte_url=fonte_url,
                note=nota,
            )
        )

    return eventi, avvisi


# --------------------------------------------------------------------------
# H. SCHEDE CON GIORNO DELLA SETTIMANA  (siti Framer/Webflow: data e
#    circuito in due elementi separati, nessun link per singola data)
# --------------------------------------------------------------------------

def da_schede_framer(
    html: str,
    registro: RegistroCircuiti,
    organizzatore: str,
    fonte_url: str,
    selettore_scheda: str,
    selettore_data: str,
    selettore_circuito: str,
    anno: int,
    ancora_prenotazione: str | None = None,
) -> tuple[list[Evento], list[str]]:
    """
    Legge calendari costruiti con siti tipo Framer o Webflow, dove ogni
    scheda ha la data ("SAB 24 OTTOBRE") e il circuito ("MAGIONE") in
    due elementi separati invece che nello stesso testo, e non c'e' un
    link di iscrizione per ogni singola data — solo un modulo generico.

    Salta le date segnate come annullate invece di pubblicarle. Verifica
    il giorno della settimana contro l'anno configurato, come per la
    griglia a pulsanti: qui l'anno va indovinato, quindi la verifica
    conta.
    """
    zuppa = BeautifulSoup(html, "lxml")
    eventi: list[Evento] = []
    avvisi: list[str] = []

    for scheda in zuppa.select(selettore_scheda):
        nodo_data = scheda.select_one(selettore_data)
        nodo_circuito = scheda.select_one(selettore_circuito)
        if not nodo_data or not nodo_circuito:
            continue

        testo_data = " ".join(nodo_data.get_text(" ", strip=True).split())
        if not testo_data:
            continue

        if "annullat" in _semplifica(testo_data):
            avvisi.append(f"data annullata, saltata: {testo_data!r}")
            continue

        sigla = re.match(r"([a-zA-Z]{3})\.?\s+(\d{1,2})\s+([a-zA-Z]+)", testo_data)
        if not sigla:
            avvisi.append(f"data non interpretabile: {testo_data!r}")
            continue

        atteso = _GIORNI_SETTIMANA.get(sigla.group(1).lower())
        mese = _MESI.get(_semplifica(sigla.group(3)))
        if not mese:
            avvisi.append(f"mese non riconosciuto in: {testo_data!r}")
            continue

        quando = _costruisci(anno, mese, int(sigla.group(2)))
        if not quando:
            avvisi.append(f"data inesistente: {testo_data!r}")
            continue
        if atteso is not None and quando.weekday() != atteso:
            avvisi.append(
                f"{testo_data!r}: il {quando} non e' {sigla.group(1).lower()} — "
                f"controlla l'anno configurato ({anno})"
            )

        nome, paese = registro.risolvi(nodo_circuito.get_text(strip=True))

        # niente pagina di dettaglio per singola data: il link porta al
        # modulo di prenotazione generico, che e' comunque dove si arriva
        link = f"{fonte_url}{ancora_prenotazione}" if ancora_prenotazione else fonte_url

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


# --------------------------------------------------------------------------
# I. GIORGIOTEAM  (pagina non strutturata: adattatore su misura)
# --------------------------------------------------------------------------

_PAROLE_CIRCUITO_FILLER = {
    "logo", "pista", "autodromo", "di", "dell", "dell'umbria", "internazionale",
}


def da_pagina_giorgioteam(
    html: str,
    registro: RegistroCircuiti,
    organizzatore: str,
    fonte_url: str,
) -> tuple[list[Evento], list[str]]:
    """
    Adattatore su misura per giorgioteam.com: la pagina non ha classi
    che distinguono un evento vero da un avviso qualsiasi (assicurazione,
    regole del circuito...) — sono tutti dentro lo stesso <div class="ombra">.

    L'unico segnale affidabile e' il link al modulo di iscrizione, che
    contiene la data per intero nell'indirizzo:
        moduloiscrizione_02_11_2026.html
    Quello si prende come fonte della data, non il testo scritto sopra,
    che non ha l'anno.

    Il circuito NON si puo' dedurre con sicurezza: le immagini dei loghi
    stanno vicine agli eventi ma non sono legate a una data specifica in
    nessun modo verificabile. Si prende la prima immagine trovata dopo
    il blocco come indicazione, ma si segnala sempre di controllare —
    e' una supposizione dichiarata, non un fatto.
    """
    zuppa = BeautifulSoup(html, "lxml")
    eventi: list[Evento] = []
    avvisi: list[str] = []

    for blocco in zuppa.select("div.ombra"):
        link_modulo = blocco.find(
            "a", href=lambda h: h and "moduloiscrizione" in h
        )
        if not link_modulo:
            continue                                       # avviso generico, non un evento

        m = re.search(r"moduloiscrizione_(\d{2})_(\d{2})_(\d{4})", link_modulo["href"])
        if not m:
            avvisi.append(f"link al modulo senza data leggibile: {link_modulo['href']!r}")
            continue
        giorno, mese, anno = map(int, m.groups())
        quando = _costruisci(anno, mese, giorno)
        if not quando:
            avvisi.append(f"data inesistente nel link: {link_modulo['href']!r}")
            continue

        testo = blocco.get_text(" ", strip=True)
        importi = [float(x.replace(",", ".")) for x in re.findall(r"(\d{1,3}(?:,\d{2})?)\s*Euro", testo)]
        prezzo = max(importi) if importi else None

        grezzo_circuito = _cerca_circuito_vicino(blocco)
        if grezzo_circuito:
            nome, paese = registro.risolvi(grezzo_circuito)
        else:
            nome, paese = "Giorgio Team — circuito da verificare", "??"
            avvisi.append(f"circuito non identificato per la data {quando}")

        eventi.append(
            Evento(
                circuito=nome,
                paese=paese,
                data=quando,
                organizzatore=organizzatore,
                prezzo=prezzo,
                url_iscrizione=link_modulo["href"],
                fonte_url=fonte_url,
                note="Controlla circuito e dettagli sul modulo di iscrizione",
            )
        )

    return eventi, avvisi


def _cerca_circuito_vicino(blocco) -> str | None:
    """
    Guarda gli elementi immediatamente successivi al blocco dell'evento
    finche' non trova un'immagine con testo alternativo descrittivo, o
    finche' non incontra il prossimo blocco evento (altro modulo di
    iscrizione) — a quel punto si ferma, per non rubare il logo
    dell'evento successivo.
    """
    nodo = blocco
    for _ in range(25):
        nodo = nodo.find_next(["img", "div"])
        if nodo is None:
            return None
        if nodo.name == "div" and nodo.find(
            "a", href=lambda h: h and "moduloiscrizione" in h
        ):
            return None                                     # e' gia' il prossimo evento
        if nodo.name == "img" and nodo.get("alt"):
            parole = [
                p for p in _semplifica(nodo["alt"]).split()
                if p not in _PAROLE_CIRCUITO_FILLER
            ]
            if parole:
                return " ".join(parole).title()
    return None
