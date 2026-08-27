"""Prova dell'adattatore a griglia sull'HTML reale di un organizzatore."""
import sys; sys.path.insert(0, "..")
from pathlib import Path
from core import RegistroCircuiti, deduplica
from adattatori import da_griglia_pulsanti

reg = RegistroCircuiti(Path("../dati/circuiti.json"))
html = Path("warmup.html").read_text(encoding="utf-8")

eventi, avvisi = da_griglia_pulsanti(
    html, reg, "Warm Up Trackdays", "https://www.warmuptrackdays.it/",
    "a.elementor-button-link.elementor-size-xs", 2026)

print(f"letti {len(eventi)} eventi grezzi")
puliti = deduplica(eventi)
print(f"{len(puliti)} dopo la deduplica\n")
for e in puliti:
    print(f"  {e.data}  {e.circuito:<30} {e.paese}  {(e.url_iscrizione or '')[-32:]}")
if avvisi:
    print("\navvisi:"); [print("  -", a) for a in avvisi]
if reg.sconosciuti:
    print("\ncircuiti non riconosciuti:", reg.sconosciuti)
