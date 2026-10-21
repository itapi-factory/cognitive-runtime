# LifeAI

Symulacja ucieleśnionych istot w Pythonie i Pygame. Lokalny LLM wybiera cele, interpretuje doświadczenia, rozmawia i przeprowadza retrospekcję. Deterministyczny układ ruchu wykonuje wybrane polecenia w ciągłej przestrzeni 2D.

## Uruchomienie

Python 3.11+, pygame-ce:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m lifeai --agents 2
```

W przygotowanym środowisku:

```bash
.venv/bin/python -m lifeai --agents 2
```

Domyślny endpoint: `http://p94.itapi.pl:8000/v1`. Klient odczytuje `/models` i używa identyfikatora faktycznie serwowanego przez API. Wcześniej serwer opisywał model jako `openai/gpt-oss-120b`, udostępniając identyfikator `openai/gpt-oss-20b`; sam opis nie potwierdza użytych wag.

Konfiguracja: `.env.example` → `.env`, zmienne środowiskowe lub CLI:

```bash
python -m lifeai --check-llm
python -m lifeai --memory-budget 16000 --seed 42
python -m lifeai --base-url http://p94.itapi.pl:8000/v1
python -m lifeai --load data/last_session.json
```

`LIFEAI_API_KEY` jest opcjonalny. `--check-llm` generuje rzeczywisty plan z początkowych zmysłów. Nową geometrię najlepiej badać od nowej sesji; import starej zachowuje również wcześniejsze, potencjalnie błędne przekonania.

## Cele i autonomiczne ciało

**Umysł i ciało działają asynchronicznie.** LLM wybiera zamiar, a ciało samodzielnie wykonuje polecenia, również podczas kolejnej analizy. Model nie liczy kroków ani położenia ust. Otrzymuje opis aktualnej czynności, celu, postępu, kolejki, stanu ciała i bieżących zmysłów. Kontekst jest zdjęciem chwili rozpoczęcia analizy; ciało i świat mogą zmienić się przed odpowiedzią.

Podczas działania kolejna analiza może rozpocząć się po 3 sekundach od poprzedniej odpowiedzi. Odstęp można zmienić przez `--thinking-interval 5` lub `LIFEAI_THINK_INTERVAL=5` (0,1–60 s). Na jedną istotę przypada najwyżej jedno trwające zapytanie poznawcze. Zakończenie planu lub niepowodzenie pozwala wcześniej przeanalizować wynik. Przyjęte polecenia ciała działają także podczas błędu API i automatycznych ponowień.

Refleksja, sen i wypowiedzi są prozą; JSON-em jest wyłącznie decyzja o aktywności:

```json
{
  "goal": "Spróbować widzianego jedzenia",
  "intent": "Podejdę do tego posiłku i zjem go.",
  "expectation": "Sprawdzę, czy po tej czynności zmieni się odczyt mojego ciała.",
  "control": "replace",
  "actions": [{"action": "eat", "target": "food-65"}]
}
```

| Polecenie | Wykonanie |
|---|---|
| `eat`, `target` | Podejście do wybranego jedzenia, ustawienie ust, zjedzenie |
| `go_to`, `target` | Podejście do dostrzeżonego lub zapamiętanego obiektu |
| `go_to`, `position: [x,y]` | Dojście do wskazanego miejsca |
| `explore`, `angle`, `distance` | Wędrówka 0,1–8 m we wskazanym kierunku |
| `look`, `angle` | Płynny obrót do absolutnego kierunku |
| `push`, `target`, `distance` | Podejście i kosztowne pchnięcie kamienia lub ciała o 0,1–1 m |
| `wait`, `seconds` | Obserwacja w miejscu przez 0,1–10 s |
| `sleep` | Retrospekcja |
| `talk` | Wypowiedź do `listener_id` na temat określony przez `speech_intent` |

Pole `control` określa wpływ decyzji na ciało:

- `continue`: zachowaj obecną czynność i kolejkę; `actions: []`.
- `queue`: zachowaj obecną czynność i zastąp kolejkę poleceń po niej.
- `replace`: przerwij czynność i rozpocznij nowy plan.
- `stop`: zatrzymaj ciało i usuń kolejkę; `actions: []`.

`replace` i `queue` zawierają 1–5 poleceń (limit konfigurowalny), zwykle wystarcza jedno. `queue` wymaga trwającej czynności. Podczas aktywności `control` jest obowiązkowe. Każda decyzja jest związana z czynnością obecną w jej kontekście. Jeżeli w czasie analizy czynność skończyła się, została przerwana, rozpoczęło się kolejne polecenie albo dotarła nowa wypowiedź do istoty, stara decyzja zostaje odrzucona, również dla `queue`. Nowe słowa uruchamiają ponowny namysł z aktualnym kontekstem, pozostawiając rozpoczęty ruch aktywny. Refleksja pozostaje w pamięci, nowe wrażenia nie są przez nią usuwane, a następna analiza dostaje aktualny stan. Spóźniona odpowiedź nie uruchomi ponownie posiłku i nie skasuje nowszej czynności. Sen i rozmowa mogą wystąpić tylko na końcu. Identyfikator celu musi pochodzić ze zmysłów lub zachowanej pamięci; nie można wskazać ukrytego obiektu przez odgadnięcie ID. Samo `talk` wymaga odbiorcy z aktualnej listy w zasięgu głosu. Można też zaplanować `go_to` do widzianej lub zapamiętanej istoty, a następnie `talk` do niej. Kontakt jest sprawdzany ponownie po dojściu, więc pamięć spotkania nie daje zdalnej łączności. `listener_id` i `speech_intent` mogą znajdować się w planie albo wewnątrz polecenia `talk`; sprzeczne wartości są odrzucane. Jawne wskazanie `listener_id` i `speech_intent` przy `replace` lub `queue` oraz pustym `actions` jest akceptowanym skrótem pojedynczego `talk`. `continue` i `stop` nigdy nie uruchamiają rozmowy. `queue` pozwala dopisać rozmowę po trwającym już podejściu do tej samej istoty.

Sterownik zachowuje ostatnio widziany cel przez całe polecenie. Utrata widoku podczas obrotu nie kasuje zamiaru. Ruchome cele aktualizuje tylko podczas obserwacji. Po dotarciu do zapamiętanego miejsca sprawdza dostępność; brak celu daje niepowodzenie. Nie podmienia jedzenia na inne, nie wybiera potrzeb, nie je podczas zwykłego `go_to` i nie przepycha przeszkód bez polecenia. O tym **co i dlaczego** robić, decyduje LLM.

Nawigacja korzysta z grafu widoczności wokół dostrzeżonych przeszkód, lokalnego rozglądania i kontaktu fizycznego. Jej roboczy zbiór do 24 przeszkód istnieje tylko podczas polecenia. Nie otrzymuje pełnej areny. Fizyka kontroluje całą trajektorię przemieszczenia, więc ciało nie przechodzi przez skały ani inne istoty. Przy nieznalezieniu przejścia, powtarzającym się blokowaniu lub przekroczeniu 45 sekund pracy sterownika polecenie kończy się wynikiem niepowodzenia. To ograniczona nawigacja lokalna, nie gwarancja znalezienia każdej istniejącej drogi.

## Ciągły świat

Arena ma domyślnie 25 × 21 metrów. Pozycje są zmiennoprzecinkowe, obrót dowolny: **0° wschód, 90° południe, 180° zachód, 270° północ**. Nie ma siatki komórek ani ruchu skokami o jedno pole. Ciało, kamienie i jedzenie mają promienie; granice areny zatrzymują ciała. Maksymalna prędkość chodzenia wynosi 1,4 m/s, obrotu 180°/s przy zwykłym tempie. Poniżej 20 jednostek energii sprawność ruchu maleje liniowo do 35% przy zerze; zero nadal oznacza śmierć. To właściwość fizyki, nie automatyczne polecenie jedzenia. Istota dostaje odczyt dostępnej szybkości i własne wyniki, bez wzoru ani wyjaśnienia przyczyny. Układ ruchu stosuje stały krok czasu 0,02 s, niezależnie od liczby klatek renderowania.

Wzrok obejmuje stożek 90° do 6 metrów. Skały i ciała zasłaniają obiekty. Pygame pokazuje bieżące pole widzenia, pozycję, kąt, wykonywane polecenie i planowaną trasę. Pełny widok jest wyłącznie widokiem obserwatora. Model otrzymuje tekstowy opis własnych zmysłów.

Pchnięcie wymaga miejsca na przesunięcie obu ciał. Nie przesuwa ścian ani łańcucha obiektów i nie zgniata jedzenia. Zwykłe dojście omija przeszkody. Pchnięta istota zachowuje energię i orientację, otrzymuje odczucie wymuszonego ruchu, a jej stary plan i trwający ruch są przerywane. Wynik wcześniejszego zapytania LLM może zachować refleksję, lecz jego plan jest odrzucany. Niewidoczny sprawca nie jest automatycznie ujawniany w pamięci ofiary. Można przesunąć bierne ciało zmarłej istoty.

**Jedzenie powstaje na początku i później wyłącznie po kliknięciu obserwatora. Nie odrasta automatycznie.**

## Energia i śmierć

Energia początkowa 78, pojemność 100, posiłek dodaje 28. Koszty obserwatora:

| Proces | Koszt |
|---|---:|
| Życie | 0,20 / s |
| Myślenie LLM | dodatkowo 0,10 / s |
| Sen | dodatkowo 0,08 / s |
| Rozpoczęcie planowania | 0,60 |
| Rozpoczęcie polecenia ciała | 0,15 |
| Chodzenie | 0,65 / m |
| Obrót | 0,20 / 90° |
| Użycie ust po dojściu | 0,15 |
| Próba pchnięcia | 20 / m, np. 12 za 0,6 m, plus rozpoczęcie i podejście |
| Rozpoczęcie snu | 1,50 |
| Konsolidacja | 0,80 / 1000 szacowanych tokenów |
| Przygotowanie wypowiedzi | 0,35 i dodatkowo 0,08 / s |
| Wypowiedź | 0,15 + 0,015 / słowo |
| Wysłuchanie | 0,005 / słowo |

Koszty zależą od czasu, długości drogi i obrotu, nie od liczby klatek. Nieudane pchnięcie także kosztuje. Energia jest pobierana przed efektem; wyczerpanie uniemożliwia nawet końcowe zjedzenie posiłku. Sen zmniejsza zmęczenie o 72, ale nie dodaje energii. Powyższa tabela ani wyjaśnienie śmierci nie są przekazywane modelowi.

Metabolizm działa podczas oczekiwania na API, snu, rozmowy, ruchu i ponawiania błędów. Przy równoczesnym myśleniu i ruchu sumują się koszt życia, koszt analizy oraz koszt przebytej drogi i obrotu; życie jest naliczane tylko raz. Pauza zatrzymuje życie i ruch; wznowienie nie nadrabia czasu pauzy. Czas poza uruchomioną aplikacją nie jest doliczany. `+ / −` zmienia tempo układu ruchu i odstępy między poleceniami, a nie prędkość LLM czy koszt samego życia na sekundę.

Zero energii usuwa pamięć, wrażenia, kontekst, cel, plan i stan sterownika. Spóźniony wynik LLM nie przywraca umysłu. Pozostaje `Corpse`: pozycja, orientacja, promień, imię i ID; bez pamięci, energii, własnego ruchu, myślenia i przyczyny śmierci. Inni rozpoznają w polu widzenia „martwą istotę Bruno”, która nie działa i nie może odpowiedzieć. Zachowują jej tożsamość i wcześniejsze świadectwa, lecz nie dostają przyczyny śmierci. Zwłoki nie są rozmówcą, także w planie podejścia i rozmowy. Rozpoznanie kończy aktywne kwestie i oczekiwanie, usuwa zaplanowane mówienie do tej istoty oraz kończy związane z rozmową polecenie czekania. Chodzenie i jedzenie mogą trwać dalej. Nieaktualna decyzja jest ponownie rozważana, a przygotowana wypowiedź zostaje pominięta. Poza wzrokiem dostępna jest tylko informacja o utracie kontaktu.

## Przewidywania, doświadczenia i ciągłość zamiaru

Nowy plan LLM (`replace` lub `queue`) zawiera `expectation`: krótkie przewidywanie prozą, do 500 znaków. Brak pola powoduje automatyczną korektę planu. `continue` zachowuje wcześniejszy zamiar i przewidywanie. Przy zmianie model ma wyjaśnić powód w `intent`; przerwana próba otrzymuje zapis przerwania, nie pozorny sukces.

Zamiar i przewidywanie trafiają do zwykłego węzła pamięci przed wykonaniem. Układ ciała dopisuje rzeczywiste wyniki poleceń oraz porównanie odczytów: czas, położenie, kierunek oczu, energia, zmęczenie i dostępna szybkość. Zmiana energii obejmuje również życie i równoległą pracę umysłu; nie jest automatycznie przypisywana jednej przyczynie. Polecenia nowej kolejki mają własne przewidywanie, a wynik bieżącego ruchu nadal należy do poprzedniej próby. Wypowiedzenie słów nie oznacza otrzymania odpowiedzi. Późniejsza odpowiedź powiązana z tą wypowiedzią albo dostrzeżenie śmierci rozmówcy uzupełnia zachowaną próbę i ponownie kieruje ją do rozważenia.

Następna refleksja LLM ma porównać przynajmniej jedną zakończoną próbę z jej wcześniejszym przewidywaniem, odwołując się do węzła. Wniosek i jego niepewność formułuje model. Samo ukończenie ruchu nie oznacza potwierdzenia hipotezy. Wynik, który pojawił się dopiero podczas trwającej analizy, czeka na kolejną analizę. Wczytanie sesji oznacza przerwanie niewznowionej czynności; nie dopisuje sukcesu.

Obecne osoby, widok i zamiar przywołują do czterech istniejących węzłów przez tożsamość rozmówców, podobieństwo słów i odnośniki. Przykładowo zobaczenie martwego Bruna może przywołać jego wcześniejsze słowa o głodzie. Mechanizm nie dopisuje wniosku o przyczynie śmierci i nie uznaje skojarzenia za nowy dowód.

Sen skupia się na sprzecznościach, niespełnionych oczekiwaniach i otwartych pytaniach. Zachowuje nieinterpretowane wyniki oraz cztery najnowsze rozważone próby jako konkretne podstawy późniejszych refleksji; starsze rozważone próby może łączyć. Wzmocnienie oznacza łatwiejsze zachowanie wspomnienia, nie większą prawdziwość. Wszystkie próby, odczyty i skojarzenia mieszczą się we wspólnym budżecie; twardy limit może je usunąć, a śmierć usuwa je razem z pamięcią. Nie istnieje dodatkowe, nieograniczone archiwum dostępne istocie.

Zakładka Myśli pokazuje zamiar, przewidywanie, wyniki i stan rozważenia próby. Kontekst pokazuje także przywołane węzły, a Dziennik zachowuje przewidywanie sprzed działania. Mechanika wymusza powrót do doświadczenia, lecz nie gwarantuje trafności interpretacji ani motywacji do przetrwania.

## Pamięć, retrospekcja i rozmowy

Limit pamięci wynosi domyślnie 8000 szacowanych tokenów, konfigurowalny od 600 do 32 000. Szacunek to `ceil(bajty UTF-8 / 3)`; nie jest tokenizerem serwera. Prompt zawiera dodatkowo instrukcje, aktualne zmysły i odczyty ciała.

Wspomnienia są tekstowymi węzłami z powiązaniami i źródłem. **Ostatnio widziane jedzenie i istoty otrzymują ograniczone budżetem, opisowe wspomnienia obserwacji**, zawierające miejsce i identyfikator celu. Istota może do nich wrócić po obrocie. Nie jest to dostęp do bieżącego stanu ukrytego świata. Identyczny widok nie tworzy kolejnego węzła. Zmiana położenia lub wyglądu tworzy nową obserwację, zachowując wcześniejszy tekst i jego odnośniki; tylko ostatnia obserwacja jest aktualnym celem nawigacji. Sprawdzone zjedzenie lub brak celu oznacza jego niedostępność. Wspomnienia obserwacji współdzielą zwykły limit, słabną podczas snu i mogą zostać zapomniane.

LLM zapisuje własną interpretację osobno. Refleksja może odwoływać się do obserwacji, ale nie zastępuje jej automatycznie ogólnikiem. Sen także zachowuje podstawowe obserwacje obok interpretacji, dopóki mieszczą się w budżecie. Wnioski modelu nadal mogą być błędne. Krótki bufor do ośmiu wrażeń zbiera wyniki całych poleceń i odczyty ciała; nie zapisuje każdej klatki chodu.

Sen następuje na życzenie istoty lub obserwatora, a automatycznie przy zmęczeniu 94 lub presji pamięci. Automatyczny sen czeka na zakończenie przyjętego planu, w tym całego dojścia i jedzenia; sen z powodu pamięci wymaga co najmniej 12 zakończonych działań od poprzedniego snu. Sen zatrzymuje aktywność ciała. Ręczny sen przerywa ruch od razu; jeśli analiza LLM już trwa, retrospekcja czeka na jej zakończenie, a wynik nie wznawia ruchu. Model wybiera 1–4 wątki i scala wskazane interpretacje, zachowując autorów cudzych relacji. Niewskazane węzły słabną nieznacznie, a twardy limit usuwa najsłabsze w razie potrzeby.

Rozmowa ma kolejność wypowiedzi. Każda usłyszana kwestia trafia do zwykłego węzła pamięci z autorem i stanem „nowa / rozważona / odpowiedziano”. Wywołuje szybki namysł; jeśli wcześniejsza analiza jeszcze trwa, jej refleksja zostaje zachowana, a decyzja jest ponownie rozważana z nowymi słowami. Ciało nadal może wykonywać przyjęte polecenie. LLM decyduje, czy odpowiedzieć, odłożyć odpowiedź, odmówić lub odejść. Nie ma automatycznie generowanej zgody ani wymuszonego zatrzymania w celu rozmowy.

Przy generowaniu odpowiedzi model dostaje dokładną kwestię rozmówcy oraz ostatnie sześć zachowanych wypowiedzi z tej relacji. Odpowiedź zostaje powiązana z konkretną usłyszaną wiadomością; nie można przypisać wypowiedzi przygotowanej wcześniej do pytania, które przyszło później. Jednoczesne zamiary mówienia do siebie są wykonywane kolejno. Oczekiwanie na swoją kolej nie blokuje namysłu.

Po wysłaniu słów nadawca oddaje kolej rozmówcy. Przez maksymalnie 30 sekund czasu życia nie wysyła kolejnej wypowiedzi do tej samej istoty bez jej reakcji; może w tym czasie poruszać się i realizować inne zamiary. Po utracie kontaktu lub upływie tego czasu zapis mówi tylko, że odpowiedzi dotąd nie usłyszano. Nie ujawnia cudzych zamiarów ani przyczyny milczenia. Powtórzenia identyczne i bardzo zbliżone tekstowo są wykrywane; LLM ma jedną próbę poprawienia wypowiedzi, a ponowne powtórzenie jest pomijane bez pętli błędów API. Ocena sensu i dalszego kierunku rozmowy należy do LLM.

Rozpoczęcie rozmowy wymaga widocznej istoty w promieniu 3 m. Rozmówcy aktywnej wymiany lub niedawno usłyszanemu rozmówcy można odpowiedzieć w tym samym zasięgu także poza polem widzenia; ściany, kamienie i inne przeszkody nadal blokują kanał. Nie daje to wiedzy o wcześniej niesłyszanych istotach za plecami. Kontakt jest sprawdzany ponownie przy dostarczeniu słów.

Pierwsza wypowiedź ma 40–900 znaków / 8–140 słów. Odpowiedź może być krótka, np. „Nie wiem.” (minimum 3 znaki / 1 słowo), z tym samym limitem maksymalnym. Dumpy, JSON, listy i zakodowane pamięci są odrzucane. Odbiorca dostaje wyłącznie wypowiedziany tekst, bez przejmowania cudzej pamięci. Obie strony płacą energią.

Stan rozmowy odwołuje się wyłącznie do węzłów współdzielących zwykły budżet pamięci; nie istnieje druga, nieograniczona historia. Sen zachowuje dokładne brzmienie aktywnych kwestii obok interpretacji, lecz twardy limit nadal może je usunąć. Zapomnienie węzła usuwa jego stan dialogu. Śmierć czyści całą perspektywę rozmowy danej istoty, pozostawiając dziennik obserwatora i wypowiedzi zapamiętane przez żyjących odbiorców.

## Okno i sterowanie

- **Spacja**: pauza; **D**: sen; **S**: zapis; **R**: nowa arena i istota.
- **N**: nowa istota (do ośmiu); **Tab / klik istoty**: wybór obserwowanej.
- **G**: pełny świat / tylko bieżący wzrok.
- **+ / −**: tempo ciała; **B**: przyspiesz ponowienie LLM.
- **Lewy klik** na wolnym miejscu: jedzenie; **prawy klik**: usuń jedzenie.
- **Kółko myszy** nad pamięcią: przewijanie.

Panele pokazują energię, zmęczenie, pamięć, cel, jednoczesną analizę i aktywność ciała oraz zakładki Myśli, Wrażenia, Rozmowy, Kontekst i Dziennik. Zakładka Rozmowy pokazuje kwestie czekające na rozważenie, oczekiwanie na reakcję i otrzymane odpowiedzi. Dziennik pozostaje dostępny po śmierci. Okno obsługuje zmianę rozmiaru.

## Zapis i dzienniki

Zapis wersji **5** obejmuje ciągłą geometrię, wszystkie ciała, pamięci żyjących istot i osobną historię obserwatora. Odczyt wersji 1–4 przekształca stare pozycje, kierunki i elementy siatki w obiekty ciągłe; nie zmienia pliku źródłowego. Stare plany ruchu nie są wykonywane. Każde wczytanie rozpoczyna nowy cykl decyzji, również jeśli zapis wykonano podczas ruchu; nie odtwarza otwartego zapytania HTTP. Nie ożywia zmarłych.

Przy normalnym uruchomieniu zdarzenia dopisywane są do osobnego JSONL w `data/journals/` lub `journals` obok `--save`. Pierwszy wiersz zawiera stan początkowy. Kolejne zapisują konteksty, myśli, plany (także odrzucone wraz z powodem), rozpoczęcie polecenia, przebieg ruchu co około 0,5 s, wynik, rozmowy, sen, błędy, interwencje i śmierć. Każde zdarzenie ma globalną kolejność, czas UTC i stan ciała. Wypowiedzi zawierają także identyfikator wiadomości oraz wskazanie wiadomości, na którą odpowiadają (`in_reply_to`). Pchnięcie zapisuje również sprawcę w archiwum obserwatora. Decyzje zapisują sposób sterowania ciałem, informację o zastosowaniu lub odrzuceniu i stan aktywności; konteksty pokazują, co model wiedział na początku analizy.

Dzienniki **nie są usuwane po śmierci** i nie są dostępne dla LLM. Wznowienie tworzy nowy plik, zachowując stare archiwa. Starsze niepełne historie są oznaczone jako niepełne. Błąd dysku pozostawia zdarzenia w pamięci aplikacji i powoduje ponowienie zapisu.

## Kontrakty i testy

Klient wymaga API `/models`, `/chat/completions`, JSON mode dla planu i `reasoning_effort` low/medium. Parametry poleceń, zakresy liczb, ID celów i odnośniki pamięci są walidowane. Kod modelu nigdy nie jest wykonywany. Błędy żądania do API automatycznie ponawiają bieżący etap po 1, 2, 4, 8, 16, następnie 30 sekundach. Niepoprawny plan jest osobnym przypadkiem: po jednej korekcie w tym samym kontekście kolejna analiza rusza po 0,1 s z odświeżonym stanem świata i zachowanym powodem odrzucenia. Poprawna refleksja z odrzuconego planu zostaje w ograniczonej pamięci. Pustej listy rozmówców nie traktuje się jako awarii połączenia; model otrzymuje wyraźną informację, że samo `talk` jest teraz niewykonalne. Trwający ruch i wcześniej przyjęta kolejka pozostają aktywne. W tym czasie życie trwa. Nie ma zastępczego decydenta wybierającego cele za model.

```bash
.venv/bin/python -m unittest discover -v
.venv/bin/python -m lifeai --headless --steps 12 --agents 2 \
  --save /tmp/lifeai-continuous/session.json --screenshot /tmp/lifeai-continuous/preview.png
```

`--steps` oznacza zakończone polecenia, wypowiedzi i sny, nie klatki fizyki. Headless przyspiesza wykonanie ciała, rozliczając upływ czasu symulacji i energię; oczekiwanie na LLM nadal kosztuje rzeczywisty czas. Sam podgląd bez zapytań:

```bash
.venv/bin/python -m lifeai --headless --steps 0 --load data/last_session.json \
  --save /tmp/lifeai-preview/session.json --screenshot /tmp/lifeai-preview/preview.png
```

Moduły: `world.py` — geometria i zmysły; `motor.py` — polecenia i nawigacja; `agent.py` — ciało i własna pamięć; `brain.py` — LLM; `simulation.py` — cykle i zapis; `memory.py` — węzły i sen; `energy.py` — koszty; `conversation.py` — opowieści; `journal.py` — archiwum; `ui.py` — Pygame.
