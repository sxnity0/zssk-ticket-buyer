# zssk-ticket-buyer

Lokálna webová aplikácia pre Termux na Androide. Nakupuje cestovné lístky ZSSK za 0 € pre cestujúceho s platným nárokom na 100 % zľavu.

Vyberieš trasu, dni v kalendári a časy odchodov. Aplikácia prejde nákup na ZSSK, skontroluje spoj a nulovú cenu, potvrdí obchodné podmienky a vystaví lístok. Doklady posiela ZSSK na zadaný e-mail. Pri nejasnom výsledku sa beh zastaví na overenie.

## Inštalácia

Potrebuješ Termux, internet a miesto na Debian a Chromium. Inštalátor vytvorí kontajner `zssk-mobile`. Prvá inštalácia sťahuje aj prehliadač, takže môže trvať niekoľko minút.

V Termuxe:

```bash
pkg install -y git
git clone https://github.com/sxnity0/zssk-ticket-buyer.git
cd zssk-ticket-buyer
bash setup.sh
zssk
```

Stránka sa otvorí automaticky a prihlási ťa. Pri ďalšom použití stačí:

```bash
zssk
```

Termux nechaj bežať počas nákupu. `Ctrl+C` ukončí službu. Ak sa stránka neotvorí, otvor `http://127.0.0.1:8765` a použi aktuálny PIN vypísaný v Termuxe.

## Použitie

1. V časti **Údaje cestujúceho** ulož meno, priezvisko, e-mail, číslo zľavy ZSSK a vekovú kategóriu. Číslo ISIC nemusí byť číslom zľavy ZSSK.
2. V hornom paneli vyber **Odkiaľ** a **Kam**, potom ulož trasu. Zoznam obsahuje základné návrhy; inú stanicu môžeš napísať presným názvom.
3. Cez **Upraviť dni a časy** zapni dni, keď cestuješ, a nastav každému jeden čas odchodu. Predvolené sú Po–St 14:35 a Št–Pi 13:35. Víkendy sú vypnuté, ale môžeš ich zapnúť.
4. V kalendári klikni na prvý a posledný deň rozsahu. Oba krajné dni sú zahrnuté. Prázdniny alebo jednotlivé voľné dni môžeš pridať do vynechaných dátumov.
5. Spusti **Test bez nákupu** alebo **Kúpiť vybraný rozsah**.

**Test bez nákupu** nájde jeden vhodný deň od dátumu o týždeň neskôr. Prejde až po finálny súhrn a skontroluje trasu, dátum, čas a cenu. Na záverečnú platbu neklikne. Súhrn ostane otvorený cez **Zobraziť ZSSK**; test ukončíš tlačidlom **Zastaviť**.

**Kúpiť vybraný rozsah** vystavuje skutočné lístky. Kupuje iba priamy spoj s presným nastaveným odchodom a cenou 0 €. Ak taký spoj nenájde, údaje neprejdú overením alebo je ponuka vypredaná, beh zastaví. Iný čas ani platený lístok nevyberá.

Potvrdené lístky na rovnakú trasu, dátum a čas preskočí. Lístky kúpené mimo aplikácie nepozná. Po prerušení skontroluj e-mail alebo potvrdenie ZSSK a vyrieš záznam v časti **Overenie** pred ďalším nákupom.

## Vzhľad

Farebný kruh vľavo hore otvorí paletu. Predvolená farba je tmavomodrá `#000f5c`. Môžeš vybrať pripravený odtieň alebo vlastnú farbu. Výber sa uloží v prehliadači a používa sa aj na prihlasovacej stránke.

Indikátor vpravo sleduje dostupnosť lokálnej služby. Pri strate spojenia ukáže **Odpojené**; nesleduje samostatne stav aplikácie Android.

## Aktualizácia

Najprv dokonči alebo zastav aktuálny nákup. Potom:

```bash
cd ~/zssk-ticket-buyer
git pull --ff-only
bash setup.sh
zssk restart
```

Prechod zo starého ZIP balíka zachová konfiguráciu a históriu, ak už máš kontajner `zssk-mobile`. `setup.sh` nastaví príkaz `zssk` na tento nový priečinok.

## Keď niečo nefunguje

- **Stránka žiada PIN:** spusti `zssk`; otvorí sa s automatickým prihlásením.
- **Služba už beží alebo je obsadený port:** použi `zssk restart`. Ak stará služba zostane bežať, ukonči ju cez `Ctrl+C` v jej okne Termuxu.
- **Nákup sa zastavil:** pozri dôvod na stránke a otvor **Zobraziť ZSSK**. Po neistom výsledku najprv over, či lístok už nebol vystavený.
- **Neotvorí sa prehliadač ZSSK:** v druhom okne Termuxu vypíš log:

```bash
proot-distro login zssk-mobile --no-sysvipc -- \
  tail -n 60 /root/.local/share/zssk-helper/display.log
```

## Súbory a údaje

`mobile.py` poskytuje lokálnu stránku, `zssk.py` vykonáva nákup cez Playwright. `templates/` obsahuje rozhranie, `static/` spoločnú farebnú tému. `setup.sh` nainštaluje závislosti a príkaz `zssk`; `start.sh` spúšťa službu.

Konfigurácia a história sú v kontajneri v `/root/.local/share/zssk-helper/`. Osobné údaje zadávaš až v aplikácii. Projekt ich neobsahuje. Pri nákupe sa odošlú ZSSK. Do GitHuba nepridávaj konfiguráciu, históriu, PIN ani logy.

Aplikácia počúva iba na `127.0.0.1`. Nie je oficiálnou aplikáciou ZSSK. Zmena predajného webu môže vyžadovať úpravu automatizácie.

## Kontroly kódu

Na počítači s Pythonom 3.10 alebo novším:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests
bash -n setup.sh start.sh install.sh
```

Tieto kontroly nekupujú lístky a nenahrádzajú test na telefóne.
