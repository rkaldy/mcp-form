# Testy

## Typy testů

| Typ           | Účel                                                                                                    | Závislosti |
|---------------|---------------------------------------------------------------------------------------------------------| --- |
| `unit`        | Funkce, třídy, komponenty, synchronní i nenáročné asynchronní scénáře včetně rychlých databázových testů | Podle potřeby skutečná lokální databáze/Redis; externí API mockovaná |
| `integration` | Skutečné zpracování na pozadí, workery, fronty, plánování a koordinace procesů                          | Skutečná lokální infrastruktura; externí API mockovaná |
| `e2e`         | Kompletní aplikační use-casy z pohledu uživatele                                                       | Skutečné interní komponenty; externí API mockovaná |
| `external`    | Ověření jednotlivých operací providerů a vybraných krátkých návazných scénářů proti živým službám       | Skutečná externí API, vyhrazené testovací účty |
| `smoke`       | Základní ověření nainstalovaného prostředí                                                              | Nasazené služby; kontroly bezpečné pro produkci |

- Testy rozděluj mezi `unit` a `integration` podle rychlosti, ne podle velikosti pokrytí. Příklady:
  - Test velké třídy, který ale pokrývá jen kód, je unit
  - Test třídy, která volá databázi, je unit
  - Test asynchronních metod je také unit
  - Test asynchronního zpracování úloh, kde nastává čekání, fronta zpráv, timeouty a podobně, je již integration, bez ohledu na rychlost. 
- U `e2e` používej realistické mocky providerů a pokud možno testuj co nejvíce usecasů popsaných ve specifikaci. S aplikací interaguj skrze frontend, to platí i pro aserce. Dlouhé scénáře zkracuj řízením času a testovací konfigurací, nikoli libovolným čekáním.
- Testy `external` se musí spouštět pouze po výslovném zapnutí, používat oddělené přihlašovací údaje a syntetická data a kontrolovat placená volání i vedlejší účinky.
- Testy `smoke` musí být bezpečné pro spuštění v produkci; vyhýbej se destruktivním operacím, změnám skutečných zákazníků a odesílání obchodních zpráv.
- Nepiš testy pro každou UI funkci. Piš testy jen pro své vlastní UI kompomenty. Frontend se testuje primárně E2E testy.


## Použití databáze v testech

Tato kapitola platí pro všechny testy kromě smoke testů.
 
- Testovací databáze se vytvoří pomocí fixtury a alembic skriptů pouze jednou, na začátku session.
- Testy použijí databázové spojení z fixtury, které na konci provede rollback, aby po skončení testu nezůstala v databázi testovací data.

## Filozofie testování

- Testuj **pozorovatelné chování a kontrakty**, nikoli soukromé implementační detaily. Mockuj externí hranice, ne logiku, kterou právě testuješ.
- Každou podstatnou změnu chování doprovázej testy. Při opravě chyby přidej pokud možno regresní test, který by před opravou selhával.
- Pokrývej úspěšné scénáře, relevantní okrajové případy, neplatné vstupy a důležité chybové stavy či opakované pokusy. U stavového nebo souběžného chování zahrň konflikty a zotavení po selhání.
- Testy udržuj deterministické, izolované, opakovatelné a nezávislé na pořadí spuštění. Po každém testu ukliď všechna jím vytvořená data.
- Namísto skutečného čekání nebo závislosti na reálném čase používej řízené hodiny, předávané zdroje náhodnosti a synchronizační mechanismy.
- Upřednostňuj realistická testovací data a aserce, které skutečně odhalí regresi chování. Nepiš aserce jen kvůli zvýšení procenta pokrytí.

## Testovací techniky

- Na testování používej funkce `test_XXX`, ne metody. Do docstringu dej popis, co daný test testuje.
- Na mockování použij `mocker.patch` a `mocker.patch.object`.
- Místo copy-paste vytváření struktur pro běh testů používej pytest fixtury. Nepoužívej fixtury místo triviálních konstruktorů s jedním parametrem typu `obj=Class("param")`. Zvaž, zdali u objektů, které přijímají různé parametry v konstruktoru, není lepší factory funkce nežli fixtura.
- Netestuj triviální pydantic validace v samotných modelech. Nevalidní parametry testuj jen u funkcí, které samy validují.
- Nesnaž se za každou cenu o 100% test code coverage. Nepiš testy na triviální kód. Máš-li nějakou jednoduchou metodu třídu nebo strukturu, buď ji netestuj vůbec (testing coverage není relevantní metrika), anebo ji otestuj v rámci testovnání metody, která ji volá.



