import sys; sys.path.insert(0, "..")
from pathlib import Path
from core import RegistroCircuiti, deduplica
from adattatori import da_schede_link

reg = RegistroCircuiti(Path("../dati/circuiti.json"))
html = Path("rossocorsa.html").read_text(encoding="utf-8")
eventi, avvisi = da_schede_link(
    html, reg, "Rosso Corsa", "https://www.rossocorsaonline.com/prove",
    "div.sectionContentItems a.pr", 2026)
print(f"{len(eventi)} eventi\n")
for e in deduplica(eventi):
    posti = f"{e.posti_liberi}/{e.posti_totali}" if e.posti_liberi is not None else "—"
    print(f"  {e.data}  {e.circuito:<24} {e.prezzo:>6}€  posti~{posti:<6} {(e.url_iscrizione or '')[-22:]}")
if avvisi: print("\navvisi:"); [print("  -",a) for a in avvisi]
if reg.sconosciuti: print("\nnon riconosciuti:", reg.sconosciuti)
