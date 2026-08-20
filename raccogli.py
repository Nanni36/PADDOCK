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

def raccogli_fonte(fonte: dict, html: str | None = None) -> list:
    tipo = fonte["tipo"]
    testo = html if html is not None else adattatori.scarica(
        fonte["url"], ignora_robots=fonte.get("permesso_accordato", False)
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
        fonti = [{
            "attiva": True,
            "organizzatore": "Organizzatore di Prova",
            "tipo": "tabella_html",
            "url": "file://prove/calendario.html",
            "selettore": "table tbody tr",
            "colonne": {"data": 0, "circuito": 1, "prezzo": 2, "posti": 3, "livelli": 4},
        }]
        campioni = {"Organizzatore di Prova":
                    (BASE / "prove" / "calendario.html").read_text(encoding="utf-8")}
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
