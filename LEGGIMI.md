# PADDOCK — motore di raccolta calendari

## Cosa fa

Legge i calendari pubblicati dagli organizzatori di track day, li mette
tutti nello stesso formato, elimina i doppioni e produce un unico file
che alimenta il sito.

L'analogia: ogni organizzatore parla un dialetto diverso. Gli adattatori
sono i traduttori. Il resto del sistema sente solo l'italiano.

## Come si usa (il modo semplice)

Doppio clic su **AGGIORNA.command**. Aggiorna il calendario e apre il sito.
La prima volta il Mac potrebbe chiedere conferma: tasto destro sul file →
Apri → Apri.

## Come si usa (dal terminale)

```bash
pip install requests beautifulsoup4 lxml

python3 raccogli.py --prova     # prova sul file di esempio, senza rete
python3 raccogli.py             # raccoglie dalle fonti vere
```

Poi apri il sito:

```bash
cd sito && python3 -m http.server 8000
# vai su http://localhost:8000
```

Se `eventi.json` esiste, il sito mostra i dati veri e in alto compare la
data di aggiornamento. Altrimenti resta sulla demo — mai una pagina bianca.

## Come si aggiunge un organizzatore

1. Apri il suo calendario nel browser, tasto destro → Ispeziona
2. Trova il selettore CSS delle righe della tabella (es. `table.eventi tbody tr`)
3. Conta in che posizione stanno data, circuito, prezzo, posti (si parte da 0)
4. Aggiungi la voce in `FONTI` dentro `raccogli.py` e metti `"attiva": True`
5. Lancia `python3 raccogli.py` e **controlla a mano** che le date lette
   corrispondano a quelle pubblicate

Il punto 5 non è facoltativo. Un aggregatore che mostra una data sbagliata
perde il cliente per sempre: quello si presenta al circuito e trova il
cancello chiuso.

## I file

| File | A cosa serve |
|---|---|
| `core.py` | Modello dati, riconoscimento circuiti e date, doppioni, esportazione |
| `adattatori.py` | Un lettore per ogni formato: tabella HTML, calendario ICS, CSV manuale |
| `raccogli.py` | L'elenco delle fonti e il comando da lanciare |
| `dati/circuiti.json` | I nomi ufficiali dei circuiti e tutti i modi in cui vengono scritti |
| `dati/manuali.csv` | Eventi inseriti a mano, per chi pubblica solo su Facebook |
| `sito/index.html` | Il sito |
| `sito/eventi.json` | Prodotto da `raccogli.py`, letto dal sito |

## Tre cose che ho già risolto per te

**Nomi diversi, stesso posto.** "Rijeka", "Grobnik" e "Automotodrom Grobnik"
diventano un'unica voce. Senza questo, il filtro per circuito è inutilizzabile.

**Date scritte in venti modi.** `04/09/2026`, `4 settembre 2026`, `sab 18 set`,
`2026-09-11` vengono lette tutte. Quello che non è riconosciuto viene
saltato, non inventato.

**Doppioni.** Lo stesso evento pubblicato dal circuito e dall'organizzatore
compare una volta sola, tenendo la versione con più informazioni.

## I formati che sa leggere

| Formato | Quando si usa |
|---|---|
| `tabella_html` | Calendario in una tabella con righe e colonne |
| `griglia_pulsanti` | Calendario fatto di riquadri cliccabili (WordPress/Elementor) |
| `schede_link` | Calendario a schede cliccabili, titolo tipo `31 AGOSTO | MUGELLO` |
| `ics` | Chi pubblica con Google Calendar o un plugin eventi |
| CSV manuale | Chi il calendario lo mette solo su Facebook |

Il secondo e' il piu' comune sui siti italiani. Legge righe come
`LUN. 30 MARZO MISANO` e anche `SAB.11+DOM.12 LUGLIO MAGIONE`, che spezza
in due date separate — altrimenti chi cerca la domenica non trova la giornata.

Sui riquadri l'anno spesso non c'e'. Il programma lo prende dalla
configurazione, poi **verifica** che il giorno della settimana scritto sul
riquadro coincida. Se non torna, te lo dice invece di pubblicare una data
sbagliata.

## Il controllo robots.txt

Prima di leggere qualsiasi sito, il programma controlla il `robots.txt`,
cioe' il cartello all'ingresso che dice ai programmi automatici dove
possono entrare. Se il sito vieta l'accesso, la fonte viene saltata con un
messaggio chiaro.

C'e' un interruttore `"permesso_accordato": True` per i siti che ti hanno
dato il consenso esplicito. Usalo **solo** con una mail dell'organizzatore
in mano, e conservala.

## I posti liberi

Molti organizzatori non pubblicano quanti posti restano: mostrano solo un
semaforo verde/giallo/rosso. In quel caso il portale scrive *Disponibile*,
*In esaurimento* o *Esaurito*, senza numeri.

Non e' pigrizia: tradurre un colore in "5 posti su 40" significa inventare
un dato che il lettore poi crede. Su un portale di prenotazioni un numero
falso e' peggio di nessun numero — chi si fida e trova tutto esaurito non
torna piu'.

## Due cose da fare prima di andare online

**Chiedi, non solo raccogliere.** Date e prezzi sono fatti, e i fatti non
sono protetti da copyright — ma le descrizioni scritte da loro sì, e quelle
non vanno copiate. Soprattutto: la maggior parte degli organizzatori sarà
contenta di essere sul portale, perché gli porti iscritti gratis. Una mail
prima risolve il 90% dei problemi e ti apre la porta per il passo
successivo, cioè la commissione sulle prenotazioni.

**Non martellare i siti.** Una raccolta al giorno basta. Il bot si presenta
già con un nome e un contatto nelle intestazioni: mettici il tuo indirizzo
vero in `adattatori.py`.

## Il prossimo passo

Quando il calendario è vero e qualcuno lo usa, si aggiunge il modulo di
prenotazione. Non prima: prima serve sapere se le persone tornano.
