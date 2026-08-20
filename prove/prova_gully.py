import sys; sys.path.insert(0, "..")
from pathlib import Path
from core import RegistroCircuiti, deduplica
from adattatori import da_righe_prezzo_multiplo

reg = RegistroCircuiti(Path("../dati/circuiti.json"))
html = Path("gullyracing.html").read_text(encoding="utf-8")
eventi, avvisi = da_righe_prezzo_multiplo(
    html, reg, "Gully Racing", "https://www.gullyracing.it/calendario",
    "div.riga_calendario", 2026)
print(f"{len(eventi)} eventi\n")
for e in deduplica(eventi):
    nota = f"  [{e.note}]" if e.note else ""
    print(f"  {e.data}  {e.circuito:<28} {e.prezzo:>6}€  {e.disponibilita or '—':<12}{nota}")
if avvisi: print("\navvisi:"); [print("  -",a) for a in avvisi]
if reg.sconosciuti: print("\nnon riconosciuti:", reg.sconosciuti)
