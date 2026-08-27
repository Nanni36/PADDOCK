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
| `righe_prezzo` | Una giornata, piu' tariffe (intero/scontato/promo), ognuna col suo semaforo |
| `eventi_ticket` | Weekend di gara con piu' biglietti (giorno singolo/weekend parziale/completo); legge il TESTO della pagina, non le classi CSS |
| `griglia_disponibilita` | Scheda con anno/mese nella classe CSS e disponibilita' scritta per intero |
| `framer_schede` | Siti Framer/Webflow: data e circuito in elementi separati, un solo link generico |
| `giorgioteam` | Su misura per un sito specifico senza struttura riconoscibile |
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

## Quando una fonte legge zero eventi

Ogni volta che il programma scarica davvero una pagina (non in `--prova`),
salva una copia in `debug/<organizzatore>.html` — cosi' com'e' arrivata,
prima che l'adattatore provi a leggerla.

Se una fonte legge 0 eventi, il programma te lo ricorda subito con il
percorso esatto. Apri quel file (doppio clic, si apre nel browser) e
confrontalo con quello che vedi tu navigando il sito vero:

- **Se il file di debug assomiglia a quello che vedi tu**, ma il
  programma non trova niente lo stesso, il problema e' nel selettore:
  mandami il file e lo sistemo.
- **Se il file di debug e' diverso, vuoto, o piu' corto** di quello che
  vedi tu, il sito sta trattando il programma diversamente da una
  persona vera — capita, alcuni siti filtrano in base a chi si connette.
  In questo caso serve una soluzione diversa (a volte non c'e', e quella
  fonte resta da aggiornare a mano).

La cartella `debug/` resta solo sul tuo Mac: non serve caricarla su
GitHub, e il programma la riscrive ad ogni lancio.

## Le icone dei circuiti

Ogni evento mostra una piccola sagoma del circuito vista dall'alto, sia
nella lista sia nel dettaglio. **Sono icone decorative, non mappe
tecniche**: non c'e' nessun dato GPS reale dietro, quindi non sono a
scala e non pretendono di essere accurate.

Per otto circuiti piu' noti (Mugello, Misano, Jerez, Barcellona-Catalunya,
Red Bull Ring, Cremona, Magione, Imola) la forma e' scelta per evocare
vagamente il loro carattere generale. Tutti gli altri circuiti ricevono
una di quattro forme generiche, sempre la stessa per lo stesso nome, cosi'
restano riconoscibili nel tempo anche senza un profilo dedicato.

Per aggiungere un profilo dedicato a un altro circuito, cerca
`SAGOME_PISTA` e `CIRCUITO_SAGOMA_DEDICATA` dentro `docs/index.html`.

## Il dettaglio evento

Cliccando su una data si apre una scheda con tutto quello che serve per
prenotare, costruita solo con dati veri:

- **prezzo, disponibilita', livelli**
- **box**, se l'organizzatore pubblica un prezzo (posto normale, esclusiva
  piccolo/grande) — presi da `dati/organizzatori.json`, non dall'evento
- **come prenotare**: se l'organizzatore vende online, un bottone porta
  dritto al pagamento; altrimenti una mail gia' pronta (oggetto e testo
  compilati con la data e il circuito) o un messaggio WhatsApp pronto,
  usando i contatti in `dati/organizzatori.json`
- se non ho ancora i contatti di un organizzatore, la scheda lo dice
  chiaramente invece di lasciare un bottone vuoto o inventare un numero

Per aggiungere o correggere i contatti di un organizzatore, apri
`dati/organizzatori.json` e modifica la voce corrispondente. I campi:

| Campo | Cosa metterci |
|---|---|
| `email` | Se pubblicano una mail per le iscrizioni |
| `telefono_prenotazioni` | Il numero da chiamare per prenotare (non quello generico) |
| `whatsapp` | Solo se hanno un numero WhatsApp dedicato |
| `pagamento_online` | `true` solo se hai visto un vero carrello/checkout sul sito |
| `box_normale`, `box_esclusiva_piccolo`, `box_esclusiva_grande` | Prezzi in euro, solo quelli che esistono |

Lascia `null` tutto cio' che non hai verificato. Un campo vuoto nella
scheda e' onesto; un numero sbagliato manda qualcuno a chiamare il posto
sbagliato.

## I pacchetti di piu' giorni

Un evento come Jerez o Barcellona, venduto come pacchetto di 2-3 giorni,
porta un'etichetta gialla ("3 giorni") sia nella lista sia nel dettaglio,
e la data mostrata e' l'intervallo completo ("dal 13 al 15 novembre"), non
solo il primo giorno. Il dato viene dall'adattatore che legge le date
"dal... al..." (Gully Racing per ora); se un altro organizzatore pubblica
pacchetti multi-giorno in un formato diverso, va insegnato al suo
adattatore lo stesso trucco.

## Quando il circuito non e' certo

Il caso di Giorgio Team: la sua pagina non ha nessuna struttura che leghi
una data al circuito giusto. Il programma prende la prima immagine trovata
subito dopo l'evento come indicazione, e aggiunge sempre una nota
*"Controlla circuito e dettagli sul modulo di iscrizione"*.

Non e' una scappatoia: e' la scelta onesta quando il dato non e'
verificabile. Meglio un'indicazione dichiarata debole che una certezza
finta. Controlla questi eventi a mano ogni tanto.

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
