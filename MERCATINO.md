# Accendere il mercatino

Il mercatino ha bisogno di un posto dove salvare gli annunci che pubblica
la gente. GitHub Pages consegna file ma non li riceve, quindi serve un
servizio esterno: **Supabase**, gratuito e abbondante per un progetto come
questo (500 MB di database, 1 GB di foto).

Sono venti minuti, una volta sola.

---

## 1. Crea il progetto

Vai su **supabase.com**, registrati (va bene l'account GitHub che hai già)
e crea un progetto nuovo. Chiamalo `paddock`.

Ti chiede una password per il database: scegline una e **salvala**, anche
se non ti servirà per il mercatino.

Scegli la regione più vicina — Frankfurt o Zurich.

## 2. Crea la tabella degli annunci

Nel menu a sinistra apri **SQL Editor**, poi **New query**. Incolla tutto
questo blocco e premi **Run**:

```sql
-- la tabella dove finiscono gli annunci
create table annunci (
  id bigint generated always as identity primary key,
  creato timestamptz default now(),
  titolo text not null,
  categoria text not null,
  prezzo numeric,
  condizione text,
  descrizione text,
  zona text not null,
  contatto text not null,
  foto_url text,
  venduto boolean default false,
  codice_gestione text not null,

  -- solo per le giornate in pista cedute
  evento_data date,
  evento_circuito text,
  evento_organizzatore text,
  passaggio_autorizzato text
);

-- chiunque può leggere e pubblicare, nessuno può modificare gli altrui
alter table annunci enable row level security;

create policy "chiunque legge" on annunci
  for select using (true);

create policy "chiunque pubblica" on annunci
  for insert with check (
    length(titolo) between 3 and 80
    and length(zona) between 2 and 60
    and length(contatto) between 5 and 80
    and (descrizione is null or length(descrizione) <= 600)
  );
```

L'ultima parte è importante: dice che chiunque può leggere e pubblicare,
ma **nessuno può modificare o cancellare gli annunci degli altri**. Senza
quelle regole il database sarebbe aperto a chiunque.

## 3. Crea lo spazio per le foto

Menu **Storage** → **New bucket**. Chiamalo esattamente `annunci` e spunta
**Public bucket**.

Poi torna in **SQL Editor** e lancia anche questo:

```sql
create policy "chiunque carica foto" on storage.objects
  for insert with check (bucket_id = 'annunci');

create policy "chiunque vede le foto" on storage.objects
  for select using (bucket_id = 'annunci');
```

## 4. Collega il sito

Menu **Project Settings** (l'ingranaggio in basso) → **API**. Trovi due
valori:

- **Project URL** — qualcosa tipo `https://abcdefgh.supabase.co`
- **anon public** — una chiave lunga

Apri `docs/mercatino.html`, cerca queste due righe in cima allo script e
incolla i valori fra le virgolette:

```javascript
const SUPABASE_URL = "";      // <- Project URL
const SUPABASE_CHIAVE = "";   // <- anon public
```

Quella chiave sta in una pagina pubblica ed è normale che sia visibile:
da sola non permette di fare nulla che le regole del punto 2 non consentano.

## 5. Carica su GitHub e prova

Carica `docs/mercatino.html` e le altre pagine, poi apri il sito e prova a
pubblicare un annuncio finto. Se compare, funziona.

Cancella l'annuncio di prova da Supabase: menu **Table Editor** → `annunci`
→ selezioni la riga → elimina.

---

## Le giornate in pista cedute

È la categoria più delicata, ed è anche quella che porta più gente sul sito:
chi ha prenotato e non può andarci recupera i soldi, chi trova una data
esaurita trova una via d'ingresso.

Chi pubblica sceglie la data **dal calendario**, non la scrive a mano: così
l'annuncio resta agganciato all'evento vero, e accanto compare in automatico
il contatto dell'organizzatore.

**Il punto da non perdere di vista:** quasi nessun organizzatore permette di
cedere liberamente un posto. Alcuni lo consentono avvisando, altri no. La
pagina lo dice in giallo prima della pubblicazione e lo ripete su ogni
annuncio. Se un giorno scopri le regole precise di qualche organizzatore,
vale la pena scriverle nella sua scheda in `dati/organizzatori.json`.

## Gestire il mercatino

**Cancellare un annuncio** (spam, roba fuori posto, venduto): Table Editor,
trovi la riga, la elimini. Chi pubblica riceve un codice, ma per ora la
cancellazione la fai tu a mano — se il mercatino cresce ci mettiamo un
modulo apposta.

**Segnare come venduto**: nella stessa tabella, metti `venduto` su `true`.
L'annuncio resta visibile ma sbiadito.

**Se arriva spam**: le regole del punto 2 bloccano già i campi vuoti o
assurdi. Se dovesse servire di più, si aggiunge un controllo prima della
pubblicazione — ma non prima di averne bisogno davvero.
