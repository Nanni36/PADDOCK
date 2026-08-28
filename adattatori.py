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
from core import _MESI, _semplifica, normalizza_organizzatore

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


def scarica(url: str, ignora_robots: bool = False,
            certificato_scaduto: bool = False) -> str:
    """
    ignora_robots va messo a True SOLO per un sito che ti ha dato
    il permesso esplicito (una mail dell'organizzatore, un accordo).
    Non e' un interruttore da usare per comodita'.

    certificato_scaduto serve quando l'organizzatore si e' dimenticato di
    rinnovare il certificato di sicurezza del proprio sito. Succede spesso
    ai siti piccoli. Va usato SOLO per leggere un calendario pubblico:
    significa rinunciare alla verifica dell'identita' del sito, quindi non
    va mai attivato su pagine dove si inseriscono dati o si paga.
    """
    if not ignora_robots and not robots_permette(url):
        raise AccessoNegato(
            f"{urlsplit(url).netloc} vieta l'accesso automatico nel robots.txt. "
            "Scrivi all'organizzatore e chiedi il permesso o il calendario."
        )

    if certificato_scaduto:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    r = requests.get(url, headers=INTESTAZIONI, timeout=TIMEOUT,
                     verify=not certificato_scaduto)
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
    trovati = zuppa.select(selettore)
    if not trovati:
        avvisi.append(
            f"il selettore {selettore!r} non ha trovato nessuna riga: "
            "il sito potrebbe aver cambiato struttura, controlla a mano"
        )

    for nodo in trovati:
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
    trovati = zuppa.select(selettore)
    if not trovati:
        avvisi.append(
            f"il selettore {selettore!r} non ha trovato nessuna scheda: "
            "il sito potrebbe aver cambiato struttura, controlla a mano"
        )

    for scheda in trovati:
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
    trovati = zuppa.select(selettore_riga)
    if not trovati:
        avvisi.append(
            f"il selettore {selettore_riga!r} non ha trovato nessuna riga: "
            "il sito potrebbe aver cambiato struttura, controlla a mano"
        )

    for riga in trovati:
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
    trovati = zuppa.select(selettore)
    if not trovati:
        avvisi.append(
            f"il selettore {selettore!r} non ha trovato nessuna scheda: "
            "il sito potrebbe aver cambiato struttura, controlla a mano"
        )

    for scheda in trovati:
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
    trovati = zuppa.select(selettore_scheda)
    if not trovati:
        avvisi.append(
            f"il selettore {selettore_scheda!r} non ha trovato nessuna scheda: "
            "i siti Framer cambiano le classi ad ogni pubblicazione, "
            "controlla il selettore con l'ispettore del browser"
        )

    senza_data_o_circuito = 0
    for scheda in trovati:
        nodo_data = scheda.select_one(selettore_data)
        nodo_circuito = scheda.select_one(selettore_circuito)
        if not nodo_data or not nodo_circuito:
            senza_data_o_circuito += 1
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

    if senza_data_o_circuito and not eventi:
        avvisi.append(
            f"trovate {senza_data_o_circuito} schede ma nessuna aveva sia data "
            f"che circuito con i selettori {selettore_data!r} / {selettore_circuito!r}: "
            "il sito ha probabilmente cambiato la struttura interna delle schede, "
            "controlla con l'ispettore del browser"
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
    blocchi_ombra = zuppa.select("div.ombra")
    if not blocchi_ombra:
        avvisi.append(
            "nessun div.ombra trovato: il sito potrebbe aver cambiato "
            "struttura, controlla a mano"
        )

    senza_link_modulo = 0
    for blocco in blocchi_ombra:
        link_modulo = blocco.find(
            "a", href=lambda h: h and "moduloiscrizione" in h
        )
        if not link_modulo:
            senza_link_modulo += 1
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

    if senza_link_modulo and not eventi:
        avvisi.append(
            f"trovati {senza_link_modulo} blocchi 'ombra' ma nessuno conteneva "
            "un link 'moduloiscrizione': il sito ha probabilmente cambiato "
            "come pubblica gli eventi, controlla a mano"
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


# --------------------------------------------------------------------------
# L. WEEKEND DI GARA CON PIU' BIGLIETTI  (Rehm Race Days e simili)
# --------------------------------------------------------------------------
#
# Questo adattatore non usa selettori CSS: lavora sul TESTO della pagina.
# Il motivo e' che il sito e' un modulo di acquisto biglietti complesso
# (piu' tariffe, opzioni annidate, JavaScript) dove i nomi delle classi
# contano poco e cambiano spesso, mentre le parole chiave della pagina
# ("Event", "Tickets:", il formato tedesco di data e prezzo) sono la
# parte piu' stabile — sono testo scritto da una persona, non markup
# generato da un framework.
#
# Un limite dichiarato: se il sito cambia la LINGUA dell'interfaccia o
# la struttura delle frasi, questo adattatore si rompe comunque. E' un
# compromesso, non una soluzione definitiva.

_PATTERN_EVENTO_TICKET = re.compile(
    r"Event\s*\n+\s*(\d{2}\.\d{2}\.\d{4})\s*-\s*(\d{2}\.\d{2}\.\d{4})\s*\n+\s*([^\n]+)"
)
_PATTERN_PREZZO_EU = re.compile(r"(\d{1,3}(?:\.\d{3})*,\d{2})\s*€")
_SUFFISSO_EDIZIONE = re.compile(r"\s+(I{1,3}|IV|V)\s*$")


def da_pagina_eventi_ticket(
    html: str,
    registro: RegistroCircuiti,
    organizzatore: str,
    fonte_url: str,
) -> tuple[list[Evento], list[str]]:
    """
    Legge calendari organizzati come 'weekend di gara', dove ogni weekend
    puo' avere piu' biglietti in vendita (un giorno solo, un weekend
    parziale, il pacchetto completo). Pubblica UN evento per weekend,
    con il prezzo del biglietto piu' caro trovato (che rappresenta quasi
    sempre il pacchetto completo) — cosi' il calendario mostra una riga
    per weekend invece di due o tre per le combinazioni acquistabili.

    La nota sull'evento lo dice esplicitamente quando esistono anche
    opzioni piu' economiche, cosi' chi legge sa che il prezzo mostrato
    e' quello del pacchetto pieno, non l'unico disponibile.
    """
    testo = BeautifulSoup(html, "lxml").get_text("\n")
    eventi: list[Evento] = []
    avvisi: list[str] = []

    blocchi = list(_PATTERN_EVENTO_TICKET.finditer(testo))
    if not blocchi:
        avvisi.append(
            "nessun blocco 'Event' trovato con il pattern atteso: "
            "il sito potrebbe aver cambiato struttura o lingua, controlla a mano"
        )
        return eventi, avvisi

    for indice, m in enumerate(blocchi):
        inizio_testo, fine_testo, nome_grezzo = m.groups()
        nome_grezzo = " ".join(nome_grezzo.split())
        fine_blocco = blocchi[indice + 1].start() if indice + 1 < len(blocchi) else len(testo)
        sezione = testo[m.end():fine_blocco]

        inizio = _leggi_ddmmyyyy(inizio_testo)
        fine = _leggi_ddmmyyyy(fine_testo)
        if not inizio:
            avvisi.append(f"data non letta per {nome_grezzo!r}: {inizio_testo!r}")
            continue

        # i numeri prima di "Tickets:" sono regole (decibel, orari), non prezzi
        indice_tickets = sezione.find("Tickets:")
        area_prezzi = sezione[indice_tickets:] if indice_tickets != -1 else sezione

        prezzi_trovati = list(_PATTERN_PREZZO_EU.finditer(area_prezzi))
        if not prezzi_trovati:
            # gli eventi gia' passati o troppo vicini smettono di vendere
            # biglietti: niente prezzo li' e' normale, non un guasto
            if (fine or inizio) < date.today():
                continue
            avvisi.append(f"nessun prezzo trovato per {nome_grezzo!r}, evento futuro")
            continue

        migliore = max(
            prezzi_trovati,
            key=lambda pm: float(pm.group(1).replace(".", "").replace(",", "."))
        )
        prezzo = float(migliore.group(1).replace(".", "").replace(",", "."))
        piu_di_un_biglietto = len(prezzi_trovati) > 1

        intorno = area_prezzi[migliore.end(): migliore.end() + 250]
        if re.search(r"warteliste|lista d.?attesa", intorno, re.IGNORECASE):
            disponibilita = "esaurito"
        elif re.search(r"nur wenige|wenige.{0,20}verf", intorno, re.IGNORECASE):
            disponibilita = "esaurimento"
        else:
            disponibilita = "disponibile"

        nome_circuito = _SUFFISSO_EDIZIONE.sub("", nome_grezzo).strip()
        nome, paese = registro.risolvi(nome_circuito)
        giorni_evento = (fine - inizio).days + 1 if fine and fine > inizio else 1

        nota = None
        if nome_grezzo != nome_circuito:
            nota = f"Edizione: {nome_grezzo}"
        if piu_di_un_biglietto:
            extra = "prezzo del pacchetto completo — questo organizzatore permette di prenotare anche un solo giorno, a un prezzo piu' basso"
            nota = f"{nota} — {extra}" if nota else extra.capitalize()

        eventi.append(
            Evento(
                circuito=nome,
                paese=paese,
                data=inizio,
                organizzatore=organizzatore,
                prezzo=prezzo,
                disponibilita=disponibilita,
                # niente pagina per singolo evento su questo sito (solo
                # login generico): la pagina del calendario resta il link
                # piu' utile e onesto che si puo' dare
                url_iscrizione=fonte_url,
                fonte_url=fonte_url,
                giorni=giorni_evento,
                data_fine=fine if giorni_evento > 1 else None,
                note=nota,
            )
        )

    return eventi, avvisi


def _leggi_ddmmyyyy(testo: str) -> date | None:
    m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", testo.strip())
    if not m:
        return None
    giorno, mese, anno = map(int, m.groups())
    return _costruisci(anno, mese, giorno)


# --------------------------------------------------------------------------
# M. WOOCOMMERCE CON DATA NELLO SLUG  (Eleven Riding Life e simili)
# --------------------------------------------------------------------------
#
# Su questi siti l'informazione piu' affidabile non e' nel markup ma
# nell'indirizzo del prodotto:
#     /prodotto/track-day-circuito-di-magione-30-agosto-2026/
# Circuito e data sono li' dentro, gia' puliti. Le classi CSS dei temi
# WordPress cambiano ad ogni aggiornamento del tema; lo slug no, perche'
# e' un indirizzo pubblico che il sito non puo' cambiare senza rompere
# i propri link.

_PATTERN_SLUG_TRACKDAY = re.compile(
    r"/prodotto/track-day-(.+?)-(\d{1,2})-([a-z]+)-(\d{4})/?$", re.IGNORECASE
)


def da_woocommerce_slug(
    html: str,
    registro: RegistroCircuiti,
    organizzatore: str,
    fonte_url: str,
) -> tuple[list[Evento], list[str]]:
    """
    Legge i track day da un sito WooCommerce dove ogni giornata e' un
    prodotto con circuito e data nell'indirizzo.

    Prezzo e disponibilita' si leggono dalla scheda che contiene il link:
    il prezzo dal testo ("a partire da 129 €"), la disponibilita' dal
    nome del file del semaforo (verde/giallo/rosso).
    """
    zuppa = BeautifulSoup(html, "lxml")
    eventi: list[Evento] = []
    avvisi: list[str] = []

    link_trovati = zuppa.select("a[href*='/prodotto/track-day-']")
    if not link_trovati:
        avvisi.append(
            "nessun link a /prodotto/track-day-... trovato: il sito potrebbe "
            "aver cambiato la struttura degli indirizzi, controlla a mano"
        )
        return eventi, avvisi

    visti = set()
    for link in link_trovati:
        href = link["href"].split("?")[0]
        m = _PATTERN_SLUG_TRACKDAY.search(href)
        if not m:
            continue

        grezzo_circuito, giorno, mese_testo, anno = m.groups()
        mese = _MESI.get(_semplifica(mese_testo))
        if not mese:
            avvisi.append(f"mese non riconosciuto nell'indirizzo: {href!r}")
            continue

        quando = _costruisci(int(anno), mese, int(giorno))
        if not quando:
            avvisi.append(f"data inesistente nell'indirizzo: {href!r}")
            continue

        chiave = (href, quando)
        if chiave in visti:
            continue                       # lo stesso prodotto linkato piu' volte
        visti.add(chiave)

        nome, paese = registro.risolvi(grezzo_circuito.replace("-", " "))
        scheda = _scheda_contenitore(link)
        testo_scheda = scheda.get_text(" ", strip=True) if scheda else ""

        eventi.append(
            Evento(
                circuito=nome,
                paese=paese,
                data=quando,
                organizzatore=organizzatore,
                prezzo=leggi_prezzo(testo_scheda),
                disponibilita=_semaforo_immagine(scheda),
                url_iscrizione=href if href.startswith("http")
                               else urlsplit(fonte_url)._replace(path=href, query="").geturl(),
                fonte_url=fonte_url,
            )
        )

    return eventi, avvisi


def _scheda_contenitore(link):
    """Risale di qualche livello per trovare il riquadro che contiene
    prezzo e semaforo insieme al link."""
    nodo = link
    for _ in range(5):
        nodo = nodo.parent
        if nodo is None:
            return link
        if nodo.find("img", src=lambda s: s and "semaforo" in s.lower()):
            return nodo
        if "€" in nodo.get_text():
            return nodo
    return link


def _semaforo_immagine(scheda) -> str | None:
    """Il semaforo qui e' un'immagine: semaforo_verde.svg, _giallo, _rosso."""
    if not scheda:
        return None
    img = scheda.find("img", src=lambda s: s and "semaforo" in s.lower())
    if not img:
        return None
    src = img["src"].lower()
    if "verde" in src:
        return "disponibile"
    if "giall" in src or "arancio" in src:
        return "esaurimento"
    if "ross" in src:
        return "esaurito"
    return None


# --------------------------------------------------------------------------
# N. CALENDARIO RAGGRUPPATO PER CIRCUITO  (Portami in Pista e simili)
# --------------------------------------------------------------------------
#
# Struttura: un titolo per circuito, e sotto una riga per mese con i
# giorni come singoli link di prenotazione:
#     Cremona Circuit
#       Aprile  24 - 25   195-219€
#       Maggio  4 - 18 - 25   185-195€
#
# Quando il prezzo e' un intervallo ("195-219€") significa che le
# giornate di quel mese costano diversamente, ma la pagina non dice
# quale giorno costa quanto. In quel caso si pubblica il prezzo piu'
# basso e lo si dichiara nella nota: meglio "a partire da" dichiarato
# che un numero preciso attribuito alla giornata sbagliata.

_PATTERN_INTERVALLO_PREZZO = re.compile(r"(\d{2,4})\s*[-–]\s*(\d{2,4})\s*€")


def da_calendario_per_circuito(
    html: str,
    registro: RegistroCircuiti,
    organizzatore: str,
    fonte_url: str,
    anno: int,
    selettore_titolo: str = "h3",
    selettore_link_giorno: str = "a[href*='eventId=']",
) -> tuple[list[Evento], list[str]]:
    zuppa = BeautifulSoup(html, "lxml")
    eventi: list[Evento] = []
    avvisi: list[str] = []

    titoli = [t for t in zuppa.select(selettore_titolo) if t.get_text(strip=True)]
    if not titoli:
        avvisi.append(
            f"nessun titolo {selettore_titolo!r} trovato: il sito potrebbe "
            "aver cambiato struttura, controlla a mano"
        )
        return eventi, avvisi

    for indice, titolo in enumerate(titoli):
        grezzo_circuito = titolo.get_text(" ", strip=True)
        nome, paese = registro.risolvi(grezzo_circuito)

        # tutti gli elementi tra questo titolo e il prossimo
        fine = titoli[indice + 1] if indice + 1 < len(titoli) else None
        blocco = []
        for elemento in titolo.next_elements:
            if fine is not None and elemento is fine:
                break
            if getattr(elemento, "name", None) == "li":
                blocco.append(elemento)

        for riga in blocco:
            testo = " ".join(riga.get_text(" ", strip=True).split())
            m_mese = re.search(rf"\b({_NOMI_MESI})\b", testo, re.IGNORECASE)
            if not m_mese:
                continue
            mese = _MESI[m_mese.group(1).lower()]

            prezzo, nota_prezzo = _prezzo_da_riga(testo)

            for link_giorno in riga.select(selettore_link_giorno):
                etichetta = link_giorno.get_text(strip=True)
                if not etichetta.isdigit():
                    continue
                quando = _costruisci(anno, mese, int(etichetta))
                if not quando:
                    avvisi.append(f"data inesistente: {etichetta}/{mese}/{anno} ({nome})")
                    continue

                href = link_giorno["href"]
                if href.startswith("/"):
                    href = urlsplit(fonte_url)._replace(path=href, query="").geturl()

                eventi.append(
                    Evento(
                        circuito=nome,
                        paese=paese,
                        data=quando,
                        organizzatore=organizzatore,
                        prezzo=prezzo,
                        url_iscrizione=link_giorno["href"] if link_giorno["href"].startswith("http") else href,
                        fonte_url=fonte_url,
                        note=nota_prezzo,
                    )
                )

    return eventi, avvisi


def _prezzo_da_riga(testo: str) -> tuple[float | None, str | None]:
    """Un prezzo solo, oppure un intervallo che vale per piu' giornate."""
    m = _PATTERN_INTERVALLO_PREZZO.search(testo)
    if m:
        basso, alto = float(m.group(1)), float(m.group(2))
        return basso, (f"Prezzo a partire da {basso:.0f}€ (fino a {alto:.0f}€ "
                       "a seconda della giornata: il sito non specifica quale)")
    return leggi_prezzo(testo), None


# --------------------------------------------------------------------------
# O. CALENDARIO DEL CIRCUITO  (il circuito pubblica CHI affitta la pista)
# --------------------------------------------------------------------------
#
# Fonte di tipo diverso dalle altre: qui il circuito e' fisso e a cambiare
# e' l'organizzatore. Serve a due cose:
#   1. coprire organizzatori che non abbiamo ancora come fonte propria
#   2. incrociare i dati di quelli che abbiamo gia'
# I doppioni si risolvono da soli grazie a normalizza_organizzatore().
#
# Non ci sono prezzi: il circuito rimanda all'organizzatore. Restano None.

_PATTERN_DETTAGLIO_EVENTO = re.compile(
    r"/details/(\d{4})-(\d{2})-(\d{2})/\d+-(.+?)-\d+/?$"
)


def da_calendario_circuito(
    html: str,
    registro: RegistroCircuiti,
    circuito: str,
    fonte_url: str,
    selettore_link: str = "a[href*='/details/']",
) -> tuple[list[Evento], list[str]]:
    """
    Legge il calendario di un circuito che elenca le giornate affittate ai
    vari organizzatori. Data e nome dell'organizzatore stanno nell'indirizzo
    della pagina di dettaglio:
        /details/2026-08-31/1786-rossocorsa-1
    """
    zuppa = BeautifulSoup(html, "lxml")
    eventi: list[Evento] = []
    avvisi: list[str] = []
    nome_circuito, paese = registro.risolvi(circuito)

    link_trovati = zuppa.select(selettore_link)
    if not link_trovati:
        avvisi.append(
            f"nessun link {selettore_link!r} trovato: il sito potrebbe aver "
            "cambiato struttura, controlla a mano"
        )
        return eventi, avvisi

    visti = set()
    for link in link_trovati:
        href = link["href"].split("?")[0]
        m = _PATTERN_DETTAGLIO_EVENTO.search(href)
        if not m:
            continue

        anno, mese, giorno, slug = m.groups()
        quando = _costruisci(int(anno), int(mese), int(giorno))
        if not quando:
            avvisi.append(f"data inesistente nell'indirizzo: {href!r}")
            continue

        # il testo del link e' il nome scritto per esteso; lo slug e' il
        # ripiego quando il link e' solo un'icona
        etichetta = link.get_text(" ", strip=True)
        grezzo = etichetta if len(etichetta) > 2 else slug.replace("-", " ")
        organizzatore = normalizza_organizzatore(grezzo)

        chiave = (quando, _semplifica(organizzatore))
        if chiave in visti:
            continue
        visti.add(chiave)

        if href.startswith("/"):
            href = urlsplit(fonte_url)._replace(path=href, query="").geturl()

        eventi.append(
            Evento(
                circuito=nome_circuito,
                paese=paese,
                data=quando,
                organizzatore=organizzatore,
                url_iscrizione=href,
                fonte_url=fonte_url,
                note="Data dal calendario del circuito: prezzo e iscrizione "
                     "vanno chiesti all'organizzatore",
            )
        )

    return eventi, avvisi


# --------------------------------------------------------------------------
# P. CALENDARIO PER MESE CON GIORNO ATTACCATO  (Vallelunga)
# --------------------------------------------------------------------------
#
# Titolo del mese, e sotto voci dove giorno e sigla del giorno della
# settimana sono attaccati al resto del testo: "26DOM3 gruppi APRILIA".
# Il prezzo non e' per singola data: il sito pubblica un listino generale
# (feriale / prefestivo-festivo). Non lo attribuiamo alla giornata — va
# nella nota, cosi' resta un fatto e non un'attribuzione inventata.

_PATTERN_GIORNO_ATTACCATO = re.compile(
    r"^\s*(\d{1,2})\s*(lun|mar|mer|gio|ven|sab|dom)(.*)", re.IGNORECASE
)


def da_calendario_mese_compatto(
    html: str,
    registro: RegistroCircuiti,
    organizzatore: str,
    circuito: str,
    fonte_url: str,
    anno: int,
    nota_prezzi: str | None = None,
    selettore_mese: str = "h3",
) -> tuple[list[Evento], list[str]]:
    zuppa = BeautifulSoup(html, "lxml")
    eventi: list[Evento] = []
    avvisi: list[str] = []
    nome_circuito, paese = registro.risolvi(circuito)

    intestazioni = [h for h in zuppa.select(selettore_mese)
                    if _MESI.get(_semplifica(h.get_text()))]
    if not intestazioni:
        avvisi.append(
            f"nessun titolo di mese trovato con {selettore_mese!r}: "
            "il sito potrebbe aver cambiato struttura, controlla a mano"
        )
        return eventi, avvisi

    for indice, intestazione in enumerate(intestazioni):
        mese = _MESI[_semplifica(intestazione.get_text())]
        fine = intestazioni[indice + 1] if indice + 1 < len(intestazioni) else None

        # raccoglie gli elementi che stanno fra questa intestazione e la
        # prossima, camminando in avanti nel documento
        blocco = []
        for elemento in intestazione.next_elements:
            if fine is not None and elemento is fine:
                break
            if getattr(elemento, "name", None) in ("a", "li", "p"):
                blocco.append(elemento)

        for elemento in blocco:
            testo = " ".join(elemento.get_text(" ", strip=True).split())
            m = _PATTERN_GIORNO_ATTACCATO.match(testo)
            if not m:
                continue

            giorno, sigla, descrizione = m.groups()
            quando = _costruisci(anno, mese, int(giorno))
            if not quando:
                avvisi.append(f"data inesistente: {giorno}/{mese}/{anno}")
                continue

            atteso = _GIORNI_SETTIMANA.get(sigla.lower())
            if atteso is not None and quando.weekday() != atteso:
                avvisi.append(
                    f"{testo[:40]!r}: il {quando} non e' {sigla.lower()} — "
                    f"controlla l'anno configurato ({anno})"
                )
                continue

            descrizione = descrizione.strip(" -–—")
            note = [n for n in (descrizione or None, nota_prezzi) if n]

            eventi.append(
                Evento(
                    circuito=nome_circuito,
                    paese=paese,
                    data=quando,
                    organizzatore=organizzatore,
                    url_iscrizione=fonte_url,
                    fonte_url=fonte_url,
                    note=" — ".join(note) if note else None,
                )
            )

    # la stessa data puo' comparire in piu' elementi annidati
    unici, visti = [], set()
    for e in eventi:
        if e.data in visti:
            continue
        visti.add(e.data)
        unici.append(e)
    return unici, avvisi


# --------------------------------------------------------------------------
# Q. AGENDA EVENTI DEL CIRCUITO  (Tazio Nuvolari: auto e moto insieme)
# --------------------------------------------------------------------------

_PATTERN_AGENDA = re.compile(
    rf"\b(lun|mar|mer|gio|ven|sab|dom)\s*(\d{{1,2}})\s*"
    rf"(gen|feb|mar|apr|mag|giu|lug|ago|set|ott|nov|dic)\b",
    re.IGNORECASE,
)


def da_agenda_circuito(
    html: str,
    registro: RegistroCircuiti,
    organizzatore: str,
    circuito: str,
    fonte_url: str,
    anno: int,
    solo_moto: bool = True,
) -> tuple[list[Evento], list[str]]:
    """
    Agenda che mescola giornate auto e moto. Con solo_moto attivo si
    pubblicano solo quelle moto: un portale di track day moto che mostra
    una giornata auto manda il pilota a sbattere contro un cancello.
    """
    zuppa = BeautifulSoup(html, "lxml")
    eventi: list[Evento] = []
    avvisi: list[str] = []
    nome_circuito, paese = registro.risolvi(circuito)

    schede = zuppa.select("a[href*='/events/']")
    if not schede:
        avvisi.append(
            "nessun link a /events/ trovato: il sito potrebbe aver cambiato "
            "struttura, controlla a mano"
        )
        return eventi, avvisi

    visti = set()
    for scheda in schede:
        contenitore = scheda.parent or scheda
        testo = " ".join(contenitore.get_text(" ", strip=True).split())

        m = _PATTERN_AGENDA.search(testo)
        if not m:
            continue

        sigla, giorno, mese_sigla = m.groups()
        mese = _MESI.get(_semplifica(mese_sigla))
        if not mese:
            continue

        quando = _costruisci(anno, mese, int(giorno))
        if not quando:
            avvisi.append(f"data inesistente in: {testo[:50]!r}")
            continue

        atteso = _GIORNI_SETTIMANA.get(sigla.lower())
        if atteso is not None and quando.weekday() != atteso:
            avvisi.append(
                f"{testo[:40]!r}: il {quando} non e' {sigla.lower()} — "
                f"controlla l'anno configurato ({anno})"
            )
            continue

        semplificato = _semplifica(testo)
        e_moto = "moto" in semplificato
        e_auto = "auto" in semplificato or "kart" in semplificato
        if solo_moto and not e_moto:
            continue
        if solo_moto and e_auto and not e_moto:
            continue

        href = scheda["href"]
        if (quando, href) in visti:
            continue
        visti.add((quando, href))

        # il titolo e' il testo dopo l'orario di fine
        titolo = re.split(r"\d{1,2}:\d{2}", testo)[-1].strip()

        eventi.append(
            Evento(
                circuito=nome_circuito,
                paese=paese,
                data=quando,
                organizzatore=organizzatore,
                url_iscrizione=href,
                fonte_url=fonte_url,
                note=titolo[:120] if titolo else None,
            )
        )

    return eventi, avvisi


# --------------------------------------------------------------------------
# R. SPEER RACING  (elenco eventi con prezzi, disponibilita' e box)
# --------------------------------------------------------------------------
#
# Ogni evento compare due volte nella pagina: una scheda principale
# (con circuito, limite dB e prezzo) e una scheda "On-site services"
# con i costi di box e trasporto. Le uniamo: la seconda porta proprio
# i prezzi dei box, che quasi nessun altro organizzatore pubblica.

_MESI_INGLESI = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

_PATTERN_DATA_SPEER = re.compile(
    r"(\d{1,2})\.\s*(?:-\s*(\d{1,2})\.\s*)?"
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)\s+(\d{4})",
    re.IGNORECASE,
)
_PATTERN_PREZZO_SPEER = re.compile(r"€\s*([\d.]+)")


def _prezzo_speer(testo: str) -> float | None:
    """'€ 1.028.97' -> 1028.97 — le ultime due cifre sono i centesimi."""
    m = _PATTERN_PREZZO_SPEER.search(testo)
    if not m:
        return None
    pezzi = m.group(1).rstrip(".").split(".")
    if len(pezzi) == 1:
        return float(pezzi[0])
    return float("".join(pezzi[:-1]) + "." + pezzi[-1])


def da_elenco_speer(
    html: str,
    registro: RegistroCircuiti,
    organizzatore: str,
    fonte_url: str,
) -> tuple[list[Evento], list[str]]:
    testo = BeautifulSoup(html, "lxml").get_text("\n")
    eventi: list[Evento] = []
    avvisi: list[str] = []

    tagli = list(_PATTERN_DATA_SPEER.finditer(testo))
    if not tagli:
        avvisi.append(
            "nessuna data trovata nel formato atteso: il sito potrebbe aver "
            "cambiato struttura o lingua, controlla a mano"
        )
        return eventi, avvisi

    blocchi = []
    for i, m in enumerate(tagli):
        fine = tagli[i + 1].start() if i + 1 < len(tagli) else len(testo)
        blocchi.append((m, testo[m.end():fine]))

    for indice, (m, corpo) in enumerate(blocchi):
        if "On-site services" in corpo:
            continue                       # e' la scheda dei servizi, non l'evento

        giorno, giorno_fine, mese_testo, anno = m.groups()
        mese = _MESI_INGLESI.get(mese_testo.lower())
        if not mese:
            continue

        inizio = _costruisci(int(anno), mese, int(giorno))
        if not inizio:
            avvisi.append(f"data inesistente: {giorno}/{mese}/{anno}")
            continue
        fine = _costruisci(int(anno), mese, int(giorno_fine)) if giorno_fine else None

        righe = [r.strip() for r in corpo.split("\n") if r.strip()]
        if not righe:
            continue
        titolo = righe[0]

        # il circuito e' la riga con il tracciato: "Mugello - Full Circuit"
        grezzo_circuito = None
        for riga in righe[:8]:
            if re.search(r"-\s*(full circuit|idm|\d\.\d)", riga, re.IGNORECASE):
                grezzo_circuito = re.split(r"\s*-\s*", riga)[0]
                break
        if not grezzo_circuito:
            grezzo_circuito = re.split(r"\s+\d|\s+-\s+", titolo)[0]

        nome, paese = registro.risolvi(grezzo_circuito)

        if re.search(r"waiting\s*list", corpo, re.IGNORECASE):
            disponibilita = "esaurito"
        elif re.search(r"few places", corpo, re.IGNORECASE):
            disponibilita = "esaurimento"
        elif re.search(r"\bavailable\b", corpo, re.IGNORECASE):
            disponibilita = "disponibile"
        else:
            disponibilita = None

        # la scheda successiva, se e' quella dei servizi, porta i box
        note = []
        if indice + 1 < len(blocchi) and "On-site services" in blocchi[indice + 1][1]:
            servizi = blocchi[indice + 1][1]
            for etichetta, chiave in [("Posto box", r"pitbox\s*place"), ("Box intero", r"^pitbox\b")]:
                mm = re.search(chiave + r"\s*\n\s*€\s*([\d.]+)", servizi,
                               re.IGNORECASE | re.MULTILINE)
                if mm:
                    valore = _prezzo_speer("€ " + mm.group(1))
                    if valore:
                        note.append(f"{etichetta} {valore:.0f}€")

        link = None
        for a in BeautifulSoup(html, "lxml").select("a[href*='/booking/event/']"):
            link = a["href"]
            break

        eventi.append(
            Evento(
                circuito=nome,
                paese=paese,
                data=inizio,
                organizzatore=organizzatore,
                prezzo=_prezzo_speer(corpo),
                disponibilita=disponibilita,
                url_iscrizione=fonte_url,
                fonte_url=fonte_url,
                giorni=(fine - inizio).days + 1 if fine and fine > inizio else 1,
                data_fine=fine if fine and fine > inizio else None,
                note=" — ".join([titolo] + note) if note else titolo,
            )
        )

    return eventi, avvisi


# --------------------------------------------------------------------------
# S. GASSS  (weekend con circuito e date nel titolo)
# --------------------------------------------------------------------------

_PATTERN_GASSS = re.compile(
    r"(\d{2})\.([A-Za-z]{3})\.(\d{4})\s*-\s*(\d{2})\.([A-Za-z]{3})\.(\d{4})"
)


def da_elenco_gasss(
    html: str,
    registro: RegistroCircuiti,
    organizzatore: str,
    fonte_url: str,
) -> tuple[list[Evento], list[str]]:
    """
    Ogni evento e' un weekend: '05.Set.2026 - 07.Set.2026' e sotto il
    titolo 'Cremona 05.09.-07.09.2026'. Il circuito e' la parte del
    titolo prima della data.
    """
    zuppa = BeautifulSoup(html, "lxml")
    eventi: list[Evento] = []
    avvisi: list[str] = []

    link_evento = zuppa.select("a[href*='/event/']")
    if not link_evento:
        avvisi.append(
            "nessun link a /event/ trovato: il sito potrebbe aver cambiato "
            "struttura, controlla a mano"
        )
        return eventi, avvisi

    visti = set()
    for link in link_evento:
        titolo = link.get_text(" ", strip=True)
        # sulla pagina ogni evento ha piu' link: l'immagine (senza testo),
        # il titolo vero, e un pulsante "DETTAGLI". Solo il titolo contiene
        # il nome del circuito, quindi gli altri vanno scartati.
        if not titolo or _semplifica(titolo) in {"dettagli", "details", "mehr", "info"}:
            continue

        contenitore = link.parent
        for _ in range(3):
            if contenitore is None:
                break
            if _PATTERN_GASSS.search(contenitore.get_text(" ", strip=True)):
                break
            contenitore = contenitore.parent
        if contenitore is None:
            continue

        m = _PATTERN_GASSS.search(" ".join(contenitore.get_text(" ", strip=True).split()))
        if not m:
            continue

        g1, m1, a1, g2, m2, a2 = m.groups()
        mese1 = _MESI.get(_semplifica(m1))
        mese2 = _MESI.get(_semplifica(m2))
        if not mese1:
            avvisi.append(f"mese non riconosciuto: {m1!r}")
            continue

        inizio = _costruisci(int(a1), mese1, int(g1))
        fine = _costruisci(int(a2), mese2, int(g2)) if mese2 else None
        if not inizio:
            continue

        grezzo_circuito = re.split(r"\s*\d", titolo)[0].strip()
        if not grezzo_circuito:
            continue
        nome, paese = registro.risolvi(grezzo_circuito)

        href = link["href"]
        if (inizio, nome) in visti:
            continue
        visti.add((inizio, nome))

        eventi.append(
            Evento(
                circuito=nome,
                paese=paese,
                data=inizio,
                organizzatore=organizzatore,
                url_iscrizione=href,
                fonte_url=fonte_url,
                giorni=(fine - inizio).days + 1 if fine and fine > inizio else 1,
                data_fine=fine if fine and fine > inizio else None,
            )
        )

    return eventi, avvisi
