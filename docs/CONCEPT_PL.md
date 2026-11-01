# V/COMMAND — pełna koncepcja produktu (PL)

## 1. Jedno zdanie

**V/COMMAND to darmowa, niezależna od dostawcy warstwa kontroli wykonania zadań przez agentów kodujących: uruchom, sprawdź, udokumentuj i — docelowo — przełącz model bez gubienia istotnego stanu.**

Tagline: **Your agents. Under control.**

Nie sprzedajemy kolejnego edytora, drugiego Claude Code ani „supermodelu”. Problemem jest brak zaufanego, wspólnego rejestru wykonania pracy przez różne narzędzia i modeli.

## 2. Dla kogo

- Solo developer używający Claude Code, Codex, OpenCode albo innych agentów i chcący automatycznej weryfikacji.
- Maintainer open source niechcący przyjmować zmian „bo AI twierdzi, że gotowe”.
- Mały software house, który potrzebuje śladu zmian i czasu pracy bez kupowania platformy enterprise.
- Programista z ograniczonym budżetem API / lokalnym modelem, który chce świadomie dobierać koszt i jakość.

## 3. Główna pętla produktu

1. Użytkownik uruchamia sesję / polecenie istniejącego agenta z `vcmd run -- ...`.
2. V/ uruchamia polecenie bez angażowania powłoki i nie zapisuje standardowego wyjścia.
3. Po pomyślnym wykonaniu uruchamia skonfigurowane kontrole (testy, build, lint, typecheck).
4. Raportuje precyzyjny stan: brak kontroli = UNVERIFIED; wszystkie zaliczone = VERIFIED_BY_CONFIGURED_CHECKS; niezaliczone = FAILED_VERIFICATION; nieudane wykonanie = FAILED.
5. Zapisuje lokalny Evidence Report w JSON. Wszystkie niewiadome pozostają `null`.
6. Programista otwiera raport w terminalu lub wysyła zredagowany JSON do raportu CI/PR.

**Demo marketingowe:** agent mówi „Done”. V/ pokazuje „Not verified — 1 check failed”. Po poprawce: „Checks passed — Evidence available”. Nie pokazujemy fałszywych wskaźników.

## 4. Docelowe moduły

### V/ Verify

Zestaw check profiles dla JS/TS, Python, Rust i Go. Dwa poziomy kontroli: szybki (lint, build) i wymagający (testy, integracja). Dopiero później dodajemy agent-as-judge jako sygnał pomocniczy, nigdy jedyny dowód.

### V/ Evidence

Kontrakt danych zawierający: uruchomiony proces, jego kod wyjścia, czas, listę testów i checków, odpowiedzi adapterów, przybliżoną zmianę w repozytorium, stempel wersji, źródło danych o cenie, informację o niepewności. W przyszłości możliwa sygnatura raportu i załączniki z CI.

### V/ Switch

Przenoszenie *stanu pracy* (cel, decyzje, pliki, wynik testów, znane blokery), a nie kopiowanie chaotycznej historii chatu. Docelowo adaptery dla Claude Code / Codex CLI / OpenCode, bez obchodzenia ich uwierzytelnienia czy ograniczeń. Każdy handoff wymaga walidacji na tych samych checkach; brak obietnic „4 mniejsze modele = 1 duży”.

### V/ Cost

Zbiera token usage z rzeczywistych adapterów i oficjalnych metadanych. Rozdziela koszt zgłoszony przez dostawcę i estymowany (cennik, cache, kurs walut, data cennika). Do limitów potrzebny jest rzeczywisty punkt egzekwowania przed żądaniem; samo raportowanie po wykonaniu nie jest ograniczaniem kosztu.

### V/ Memory

Lokalny zapis krótkich decyzji, hashy plików, checków, artefaktów i problemów. Założenie: nic nie opuszcza urządzenia bez zgody. Wymaga opt-in, narzędzi do usuwania wpisów, wygaszania, filtrowania sekretów i mierzalnego benchmarku względem uruchomienia bez pamięci.

### V/ Pulse (opcjonalny companion)

Cichy sygnał w tray/menu bar/notch, wyświetlany tylko gdy agent potrzebuje decyzji lub gdy wynik został zweryfikowany. Niepotrzebny do uruchomienia CLI. Priorytet: Windows/macOS, możliwy Linux tray. Bez maskotki zasłaniającej edytor.

## 5. Trzy tryby pracy

- **Speed:** wybór niskolatencyjnych tras i równoległa praca tam, gdzie dane są niezależne (w przyszłości).
- **Balanced:** próba minimalizacji kosztu przy wymaganym poziomie zaliczania testów i limitach czasu (w przyszłości).
- **Offline:** wymuszenie adapterów lokalnych i odcięcie ruchu zarządzanego przez V/ (w przyszłości). Pełna izolacja procesu wymaga sandboksa/kontroli sieci hosta.

W obecnej alphie komenda `vcmd mode` zapisuje **wyłącznie preferencję**. Nie wolno reklamować tego jako działającego routera, izolacji offline ani gwarancji kosztu.

## 6. Co nas wyróżnia

- Nie konkurujemy z agentami o liczbę opcji generowania kodu. Dostarczamy jednolity format dowodów *po* wykonaniu, niezależny od modelu.
- Status `UNVERIFIED` jest pełnoprawnym wynikiem, a nie ukrywanym błędem.
- Widoczny koszt w API jest oddzielny od kosztu lokalnego sprzętu i opóźnienia.
- Cel produktu: **„Done” ≠ „Verified”**. To rozpoznawalne, konkretne przesłanie.
- Raport ma nadawać się do automatyzacji GitHub Actions / PR; nie tylko do kolorowego panelu.

## 7. UX i branding

Słowo marki: `V/COMMAND`. Znak: `V/` (projekt graficzny do dopracowania i zbadania prawnego). Komenda powłoki: `vcmd` (potwierdzić kolizje nazw przy publikacji). Język: oszczędny, monospaced, niewiele animacji, jeden wyróżniający akcent sygnalizujący stan, nie cała aplikacja w neonach. Wersja dla terminala jako główny interfejs; panel IDE i companion nie mogą być wymagane.

Zachowanie po wykonaniu: mały, dobrze wyrównany raport, który można rozwinąć `vcmd evidence`. Przy błędzie jeden powód, jeden następny krok.

## 8. Licencja i darmowy model

MIT; repo publiczne; brak subskrypcji, płatnego konta i telemetrii w darmowym core. Użytkownicy płacą tylko swoim dostawcom modeli, jeżeli korzystają z ich płatnych API. Opcjonalne GitHub Sponsors / granty nie mogą osłabiać open-source core.

## 9. Co mierzymy

- Percentage of runs with configured checks.
- Check pass rate per task category (nie „odsetek kodu bez błędów”).
- p50/p95 overhead V/ dla sprawdzania i zapisu raportu.
- Reproducibility of report from raw checks.
- With adapters: cost per independently verified task, not only cost per model output.
- With memory: change in provider tokens / koszt per task on paired benchmarks, taking variance into account.

## 10. Kryterium sukcesu MVP

Programista instaluje CLI, dodaje jedną komendę weryfikacji, uruchamia istniejącego agenta przez V/, otrzymuje lokalny raport, rozumie jego ograniczenia i może użyć raportu do review. Instalacja nie wymaga API key.
