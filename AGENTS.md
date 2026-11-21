# Pravidla vývoje

Tento soubor stanovuje pravidla psaní kódu a požadavky na jeho kvalitu v repozitáři Salesman. Záměrně **neurčuje** technologický stack, architekturu, produktové požadavky, vývojové nástroje ani backlog. V těchto oblastech se řiď příslušnými projektovými dokumenty; nevymýšlej ani tiše neměň požadavky.

Základní architektura projektu, technologie a tooling jsou popsány ve `spec/tech.md`.

High level popis celého epicu je popsán v `spec/prds/01-LLM_core.md`.

## Obecné zásady

- Upřednostňuj nejjednodušší správné a udržovatelné řešení. Vyhýbej se spekulativním abstrakcím, obecným frameworkům a předčasné optimalizaci.
- Udržuj změny malé a zaměřené na jeden účel. Nespojuj nesouvisející refaktoring s implementací nové funkcionality.
- Zachovávej stávající chování, pokud požadavek výslovně nestanoví změnu. Pokud je požadavek nejednoznačný nebo odporuje jinému dokumentu, upozorni na rozpor místo odhadování.
- Dávej přednost zavedeným konvencím projektu před zaváděním konkurenčního přístupu. Nové závislosti přidávej jen tehdy, když existuje konkrétní potřeba.
- Vyhýbej se skrytým vedlejším účinkům a měnitelnému globálnímu stavu. Netriviální předpoklady uváděj explicitně.
- Nepiš duplicitní kód. Píšeš-li kód, který je na jiném místě velmi podobný, zvaž použití sdílené třídy nebo funkce pro oba případy.

## Coding style

- Piš čitelný, idiomatický Python. Dodržuj formátovací a lintovací pravidla nastavená v repozitáři.
- Používej výstižné anglické identifikátory. Funkce udržuj úzce zaměřené a pojmenovávej je podle jejich skutečného chování.
- Všechny funkce a metody opatřuj typovými anotacemi. Upřednostňuj přesné typy před `Any`; vyhýbej se zbytečnému přetypování a potlačování kontrol. U metod s návratovou hodnotou `None` ji explicitně neuváděj.
- Na hranicích modulů a služeb používej explicitní datové kontrakty. Validuj nedůvěryhodné uživatelské vstupy a odpovědi externích služeb.
- Veřejná rozhraní opatřuj docstringy tam, kde nejsou zřejmé jejich kontrakty, invarianty, výjimky nebo vedlejší účinky. Komentáře mají vysvětlovat **proč**, nikoli popisovat **co** kód dělá.
- Nenechávej v kódu mrtvé části, nepoužité importy, ladicí výpisy ani nevysvětlené `TODO`. Nepotlačuj diagnostická hlášení bez konkrétního odůvodnění u daného místa.
- V asynchronních cestách provádění nepoužívej blokující operace.

## Chyby, spolehlivost a bezpečnost

- Zachytávej konkrétní výjimky na vrstvě, která je dokáže vyřešit. Při překladu výjimek zachovej původní příčinu a vyhýbej se duplicitnímu logování na každé vrstvě.
- Validaci parametrů dělej jen u HTTP endpointů a u metod volaných z frontendu.
- Každá chyba by se měla logovat na té úrovni, na které je zachycená a zpracovaná. Pokud jde jen o překlad, který vyhazuje jinou výjimku, pak neloguj.  Pokud překládáš chybu, dbej ať výsledná chyba obsahuje buď zdrojovou chybu jako celek nebo její chybovou hlášku.
- Opakuj pouze volání externích služeb a stahování vzdálených URL, které selhaly z přechodných příčin. Používej omezený počet pokusů a prodlevy mezi nimi; neopakuj deterministická validační selhání.
- Operace s externími vedlejšími účinky považuj za potenciálně neidempotentní. Neopakuj je naslepo, pokud není jistý výsledek předchozího pokusu.
- Nikdy nevkládej přihlašovací údaje přímo do kódu ani nevystavuj tajné údaje, osobní údaje, celé prompty nebo dokumenty zákazníků v logách, chybách, testovacích datech či telemetrii. Zaznamenávej pouze metadata potřebná k diagnostice.

## Dokumentace

Dokumentace a coding conventions pro různé domény:
- `spec/project.md` - adresářová struktura, tooling a použité technologie v tomto projektu
- `spec/database.md` - konvence pro komunikaci s databází
- `spec/tests.md` - konvence pro psaní testů

## Správa ticketů

Pro správu ticketů slouží systém `issy`. Veškeré instrukce, jak jej použítat získáš pomocí `issy learn`. 

## Postup hlavního agenta

1. Převezmi ID ticketu z promptu
2. Spusť subagenta `worker` a předej mu ID ticketu.
3. Počkej na dokončení implementace.
4. Spusť nového subagenta `reviewer` a předej mu stejné ID ticketu.
5. Pokud reviewer najde problémy, předej je původnímu subagentovi `worker` k opravě.
6. Po opravách spusť nové nezávislé review.
7. Po úspěšném review proveď git commit a uzavři ticket.
