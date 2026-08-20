#!/usr/bin/env python3
"""
PADDOCK — raccolta calendari.

    python3 raccogli.py            raccoglie tutte le fonti attive
    python3 raccogli.py --prova    gira sui file di esempio, senza rete

Aggiungere un organizzatore significa aggiungere una voce a FONTI.
Niente altro.
"""

from __future__ import annotations

import argparse
import re
import sys
import traceback
from datetime import date
from pathlib import Path

import adattatori
from core import RegistroCircuiti, deduplica, esporta

BASE = Path(__file__).parent
REGISTRO = RegistroCircuiti(BASE / "dati" / "circuiti.json")


# ==========================================================================
# LE FONTI
# --------------------------------------------------------------------------
# "tipo"         tabella_html | ics
# "selettore"    il selettore CSS delle righe (usa l'ispettore del browser)
# "colonne"      in quale posizione sta ogni dato dentro la riga
#
# Gli indirizzi qui sotto sono SEGNAPOSTO. Vanno sostituiti con i siti
# veri degli organizzatori, uno alla volta, verificando ogni volta che
# le date lette corrispondano a quelle pubblicate.
# ==========================================================================

FONTI = [
    {
        # ATTENZIONE: warmuptrackdays.it vieta l'accesso automatico nel suo
        # robots.txt. La fonte resta spenta finche' non hai il permesso
        # scritto dell'organizzatore. Se te lo danno, metti "attiva": True
        # e "permesso_accordato": True (e conserva la mail).
        "attiva": False,
        "permesso_accordato": False,
        "organizzatore": "Warm Up Trackdays",
        "tipo": "griglia_pulsanti",
        "url": "https://www.warmuptrackdays.it/",
        "selettore": "a.elementor-button-link.elementor-size-xs",
        "anno": 2026,
    },
    {
        # Rosso Corsa (Osteria Grande, BO) — prove libere moto.
        # Il loro robots.txt non vieta la lettura; il programma lo
        # ricontrolla comunque a ogni giro.
        "attiva": True,
        "organizzatore": "Rosso Corsa",
        "tipo": "schede_link",
        "url": "https://www.rossocorsaonline.com/prove",
        "selettore": "div.sectionContentItems a.pr",
        "anno": 2026,
    },
    {
        "attiva": True,
        "organizzatore": "Gully Racing",
        "tipo": "righe_prezzo",
        "url": "https://www.gullyracing.it/calendario",
        "selettore": "div.riga_calendario",
        "anno": 2026,
    },
    {
        "attiva": True,
        "organizzatore": "Promo Racing",
        "tipo": "griglia_disponibilita",
        "url": "https://www.promoracing.it/it/calendario/moto",
        "selettore": "a.event__item",
    },
    {
        "attiva": True,
        "organizzatore": "Motart",
        "tipo": "framer_schede",
        "url": "https://motart.it/attivit%C3%A0/track-day",
        "selettore": ".framer-e09p2j",
        "selettore_data": ".framer-k4aiq0 p",
        "selettore_circuito": ".framer-173r67d p",
        "ancora_prenotazione": "#prenotazione-track-day",
        "anno": 2026,
    },
    {
        "attiva": True,
        "organizzatore": "Giorgio Team Racing",
        "tipo": "giorgioteam",
        "url": "https://www.giorgioteam.com/index.html",
    },
    {
        "attiva": True,
        "organizzatore": "Rehm Race Days",
        "tipo": "eventi_ticket",
        "url": "https://www.rehmracedays.com/it/rehm-race-calendario/",
    },
    {
        "attiva": False,
        "organizzatore": "Nome Organizzatore",
        "tipo": "tabella_html",
        "url": "https://esempio-organizzatore.it/calendario",
        "selettore": "table.calendario tbody tr",
        "colonne": {"data": 0, "circuito": 1, "prezzo": 2, "posti": 3, "livelli": 4},
    },
    {
        "attiva": False,
        "organizzatore": "Organizzatore con Google Calendar",
        "tipo": "ics",
        "url": "https://esempio.it/eventi.ics",
    },
]


# ==========================================================================

def _nome_file_debug(organizzatore: str) -> str:
    """'Giorgio Team Racing' -> 'giorgio-team-racing.html' — solo per salvare
    la pagina scaricata, cosi' si puo' ispezionare senza rilanciare nulla."""
    pulito = re.sub(r"[^a-z0-9]+", "-", organizzatore.lower()).strip("-")
    return f"{pulito}.html"


def raccogli_fonte(fonte: dict, html: str | None = None) -> list:
    tipo = fonte["tipo"]
    scaricato_ora = html is None
    testo = html if html is not None else adattatori.scarica(
        fonte["url"], ignora_robots=fonte.get("permesso_accordato", False)
    )

    if scaricato_ora:
        # traccia sempre l'ultima pagina ricevuta davvero: se una fonte
        # legge 0 eventi, questo file dice se il programma ha visto
        # qualcosa di diverso da quello che si vede nel browser, senza
        # dover richiedere l'HTML da capo ogni volta
        cartella_debug = BASE / "debug"
        cartella_debug.mkdir(exist_ok=True)
        (cartella_debug / _nome_file_debug(fonte["organizzatore"])).write_text(
            testo, encoding="utf-8"
        )

    if tipo == "tabella_html":
        return adattatori.da_tabella_html(
            html=testo,
            registro=REGISTRO,
            organizzatore=fonte["organizzatore"],
            fonte_url=fonte["url"],
            selettore_riga=fonte["selettore"],
            colonne=fonte["colonne"],
            anno_predefinito=fonte.get("anno", date.today().year),
        )
    if tipo == "griglia_disponibilita":
        eventi, avvisi = adattatori.da_griglia_disponibilita(
            html=testo,
            registro=REGISTRO,
            organizzatore=fonte["organizzatore"],
            fonte_url=fonte["url"],
            selettore=fonte["selettore"],
        )
        for a in avvisi:
            print(f"        avviso: {a}")
        return eventi
    if tipo == "framer_schede":
        eventi, avvisi = adattatori.da_schede_framer(
            html=testo,
            registro=REGISTRO,
            organizzatore=fonte["organizzatore"],
            fonte_url=fonte["url"],
            selettore_scheda=fonte["selettore"],
            selettore_data=fonte["selettore_data"],
            selettore_circuito=fonte["selettore_circuito"],
            anno=fonte.get("anno", date.today().year),
            ancora_prenotazione=fonte.get("ancora_prenotazione"),
        )
        for a in avvisi:
            print(f"        avviso: {a}")
        return eventi
    if tipo == "giorgioteam":
        eventi, avvisi = adattatori.da_pagina_giorgioteam(
            html=testo,
            registro=REGISTRO,
            organizzatore=fonte["organizzatore"],
            fonte_url=fonte["url"],
        )
        for a in avvisi:
            print(f"        avviso: {a}")
        return eventi
    if tipo == "eventi_ticket":
        eventi, avvisi = adattatori.da_pagina_eventi_ticket(
            html=testo,
            registro=REGISTRO,
            organizzatore=fonte["organizzatore"],
            fonte_url=fonte["url"],
        )
        for a in avvisi:
            print(f"        avviso: {a}")
        return eventi
    if tipo == "righe_prezzo":
        eventi, avvisi = adattatori.da_righe_prezzo_multiplo(
            html=testo,
            registro=REGISTRO,
            organizzatore=fonte["organizzatore"],
            fonte_url=fonte["url"],
            selettore_riga=fonte["selettore"],
            anno=fonte.get("anno", date.today().year),
        )
        for a in avvisi:
            print(f"        avviso: {a}")
        return eventi
    if tipo == "schede_link":
        eventi, avvisi = adattatori.da_schede_link(
            html=testo,
            registro=REGISTRO,
            organizzatore=fonte["organizzatore"],
            fonte_url=fonte["url"],
            selettore=fonte["selettore"],
            anno=fonte.get("anno", date.today().year),
            selettore_titolo=fonte.get("titolo", "h3"),
        )
        for a in avvisi:
            print(f"        avviso: {a}")
        return eventi
    if tipo == "griglia_pulsanti":
        eventi, avvisi = adattatori.da_griglia_pulsanti(
            html=testo,
            registro=REGISTRO,
            organizzatore=fonte["organizzatore"],
            fonte_url=fonte["url"],
            selettore=fonte["selettore"],
            anno=fonte.get("anno", date.today().year),
        )
        for a in avvisi:
            print(f"        avviso: {a}")
        return eventi
    if tipo == "ics":
        return adattatori.da_ics(
            testo, REGISTRO, fonte["organizzatore"], fonte["url"]
        )
    raise ValueError(f"tipo fonte sconosciuto: {tipo}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--prova", action="store_true",
                   help="usa i file in prove/ invece della rete")
    args = p.parse_args()

    tutti = []
    problemi = []

    if args.prova:
        # una fonte di prova per ogni formato che il motore conosce,
        # cosi' --prova mostra un sito completo senza toccare la rete
        fonti = [
            {
                "attiva": True, "organizzatore": "Organizzatore di Prova",
                "tipo": "tabella_html", "url": "file://prove/calendario.html",
                "selettore": "table tbody tr",
                "colonne": {"data": 0, "circuito": 1, "prezzo": 2, "posti": 3, "livelli": 4},
            },
            {
                "attiva": True, "organizzatore": "Rosso Corsa",
                "tipo": "schede_link", "url": "https://www.rossocorsaonline.com/prove",
                "selettore": "div.sectionContentItems a.pr", "anno": 2026,
            },
            {
                "attiva": True, "organizzatore": "Gully Racing",
                "tipo": "righe_prezzo", "url": "https://www.gullyracing.it/calendario",
                "selettore": "div.riga_calendario", "anno": 2026,
            },
            {
                "attiva": True, "organizzatore": "Promo Racing",
                "tipo": "griglia_disponibilita",
                "url": "https://www.promoracing.it/it/calendario/moto",
                "selettore": "a.event__item",
            },
            {
                "attiva": True, "organizzatore": "Motart",
                "tipo": "framer_schede", "url": "https://motart.it/attivit%C3%A0/track-day",
                "selettore": ".framer-e09p2j", "selettore_data": ".framer-k4aiq0 p",
                "selettore_circuito": ".framer-173r67d p",
                "ancora_prenotazione": "#prenotazione-track-day", "anno": 2026,
            },
            {
                "attiva": True, "organizzatore": "Giorgio Team Racing",
                "tipo": "giorgioteam", "url": "https://www.giorgioteam.com/index.html",
            },
        ]
        campioni = {
            "Organizzatore di Prova": (BASE / "prove" / "calendario.html").read_text(encoding="utf-8"),
            "Rosso Corsa": (BASE / "prove" / "rossocorsa.html").read_text(encoding="utf-8"),
            "Gully Racing": (BASE / "prove" / "gullyracing.html").read_text(encoding="utf-8"),
            "Promo Racing": (BASE / "prove" / "promoracing.html").read_text(encoding="utf-8"),
            "Motart": (BASE / "prove" / "motart.html").read_text(encoding="utf-8"),
            "Giorgio Team Racing": (BASE / "prove" / "giorgioteam.html").read_text(encoding="utf-8"),
        }
    else:
        fonti = [f for f in FONTI if f.get("attiva")]
        campioni = {}

    if not fonti:
        print("Nessuna fonte attiva. Apri raccogli.py, compila FONTI "
              "e metti \"attiva\": True.")
        return 1

    for fonte in fonti:
        nome = fonte["organizzatore"]
        try:
            eventi = raccogli_fonte(fonte, campioni.get(nome))
            tutti.extend(eventi)
            print(f"  ok    {nome:<34} {len(eventi):>3} eventi")
            if not eventi and not args.prova:
                print(f"        pagina scaricata salvata in "
                      f"debug/{_nome_file_debug(nome)} — aprila per vedere "
                      "cosa ha ricevuto davvero il programma")
        except Exception as e:                      # una fonte rotta non ferma le altre
            problemi.append((nome, e))
            print(f"  ERR   {nome:<34} {type(e).__name__}: {e}")

    # eventi inseriti a mano
    manuali = adattatori.da_csv(BASE / "dati" / "manuali.csv", REGISTRO)
    if manuali:
        tutti.extend(manuali)
        print(f"  ok    {'inserimenti manuali':<34} {len(manuali):>3} eventi")

    puliti = deduplica(tutti)
    riepilogo = esporta(puliti, BASE / "docs" / "eventi.json")

    # i contatti degli organizzatori li mantieni in dati/organizzatori.json:
    # da li' vengono copiati cosi' come sono, il sito li legge da docs/
    fonte_organizzatori = BASE / "dati" / "organizzatori.json"
    if fonte_organizzatori.exists():
        (BASE / "docs" / "organizzatori.json").write_text(
            fonte_organizzatori.read_text(encoding="utf-8"), encoding="utf-8"
        )

    print("\n--- riepilogo ---")
    print(f"  raccolti      {len(tutti)}")
    print(f"  doppioni      {len(tutti) - len(puliti)}")
    print(f"  pubblicati    {riepilogo['scritti']}"
          f"  ({riepilogo['circuiti']} circuiti, "
          f"{riepilogo['organizzatori']} organizzatori)")

    if REGISTRO.sconosciuti:
        print("\n  circuiti non riconosciuti — aggiungili a dati/circuiti.json:")
        for s in sorted(REGISTRO.sconosciuti):
            print(f"    · {s}")

    if problemi:
        print(f"\n  {len(problemi)} fonti da sistemare.")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
