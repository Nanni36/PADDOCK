#!/bin/bash
# ══════════════════════════════════════════════════════════════
#  PADDOCK — aggiorna e apri
#
#  Doppio clic. Fa tre cose, in quest'ordine:
#    1. scarica da GitHub l'ultima versione del programma
#    2. rilegge i calendari degli organizzatori
#    3. apre il sito
#
#  Questo file non va mai sostituito: aggiorna da solo tutto il
#  resto. Tienilo sul Desktop e dimenticatene.
# ══════════════════════════════════════════════════════════════

REPO="Nanni36/PADDOCK"
CARTELLA="$HOME/paddock"

echo ""
echo "  ╔══════════════════════════════════════════╗"
echo "  ║   PADDOCK                                ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""

# ── 1. librerie (solo la prima volta) ─────────────────────────
python3 -c "import requests, bs4, lxml" 2>/dev/null || {
    echo "  Prima installazione: preparo le librerie, un minuto..."
    python3 -m pip install --quiet requests beautifulsoup4 lxml 2>/dev/null \
      || python3 -m pip install --quiet --user requests beautifulsoup4 lxml 2>/dev/null
    echo ""
}

# ── 2. ultima versione del programma ──────────────────────────
echo "  Controllo se c'e' una versione nuova del programma..."
TEMP=$(mktemp -d)

if curl -sfL "https://github.com/$REPO/archive/refs/heads/main.tar.gz" \
     | tar -xz -C "$TEMP" 2>/dev/null; then

    SORGENTE="$TEMP/PADDOCK-main"
    mkdir -p "$CARTELLA/dati" "$CARTELLA/docs"

    for f in core.py adattatori.py raccogli.py LEGGIMI.md; do
        [ -f "$SORGENTE/$f" ] && cp "$SORGENTE/$f" "$CARTELLA/$f"
    done
    [ -f "$SORGENTE/dati/circuiti.json" ] && cp "$SORGENTE/dati/circuiti.json" "$CARTELLA/dati/"
    [ -f "$SORGENTE/dati/organizzatori.json" ] && cp "$SORGENTE/dati/organizzatori.json" "$CARTELLA/dati/"
    [ -f "$SORGENTE/dati/aziende.json" ] && cp "$SORGENTE/dati/aziende.json" "$CARTELLA/dati/"
    # tutte le pagine e il foglio di stile del sito
    for pagina in "$SORGENTE"/docs/*.html "$SORGENTE"/docs/*.css; do
        [ -f "$pagina" ] && cp "$pagina" "$CARTELLA/docs/"
    done
    # immagini del sito (sfondi, foto): copia tutto quello che trova, non
    # solo nomi fissi, cosi' funziona anche quando se ne aggiungono di nuove
    for immagine in "$SORGENTE"/docs/*.jpg "$SORGENTE"/docs/*.jpeg "$SORGENTE"/docs/*.png; do
        [ -f "$immagine" ] && cp "$immagine" "$CARTELLA/docs/"
    done

    # manuali.csv NON si tocca mai: le date scritte a mano sono tue
    [ -f "$CARTELLA/dati/manuali.csv" ] || \
        echo "data,circuito,organizzatore,prezzo,posti_liberi,posti_totali,livelli,url" \
        > "$CARTELLA/dati/manuali.csv"

    echo "  Programma aggiornato."
else
    echo "  Non riesco a raggiungere GitHub: uso la versione che ho gia'."
    if [ ! -f "$CARTELLA/raccogli.py" ]; then
        echo ""
        echo "  Ma e' la prima installazione e senza rete non posso partire."
        echo "  Controlla la connessione e riprova."
        echo ""
        read -n 1 -s -r -p "  Premi un tasto per chiudere."
        exit 1
    fi
fi
rm -rf "$TEMP"
echo ""

# ── 3. calendari ──────────────────────────────────────────────
cd "$CARTELLA" || exit 1
python3 raccogli.py
ESITO=$?

echo ""
if [ $ESITO -ne 0 ]; then
    echo "  ────────────────────────────────────────────────"
    echo "  Qualche fonte non ha risposto (vedi sopra)."
    echo "  Le altre sono state comunque aggiornate."
    echo "  Se una fonte legge 0 eventi, l'organizzatore ha"
    echo "  probabilmente rifatto il sito: segnalamelo."
    echo "  ────────────────────────────────────────────────"
    echo ""
fi

# ── 4. sito ───────────────────────────────────────────────────
lsof -ti :8000 2>/dev/null | xargs kill 2>/dev/null

echo "  Sito su http://localhost:8000"
echo "  Per chiudere: Ctrl + C, poi chiudi la finestra."
echo ""

cd docs || exit 1
sleep 1 && open "http://localhost:8000" &
python3 -m http.server 8000 --bind 127.0.0.1 2>/dev/null
