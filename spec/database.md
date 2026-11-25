# Práce s databází

## SQLAlchemy a Alembic

- Komunikace s databází probíhá výhradně přes CRUD třídy
- Tyto třídy používají čisté parametrizované SQL, ne SQLAlchemy ORM
- SQLAlchemy použij jen pro databázová schémata, z nichž se generují migrační skripty pro alembic
- Každá změna v databázové struktuře vytvoří alembic migraci

## Databázové připojení

- Použij sqlite3 databázi a adaptér `Database`.
- Vytvoření připojení je zodpovědnost servis. CRUDy přijímají připojení z parametru.
- Nepoužívej v kódu explicitní commit a rollback
- Připojení se vytvoří jen během volání CRUDů. Lze použít jedno připojení, pokud mezi voláním CRUDů je pouze lokální zpracování bez I/O nebo volání externích služeb. Připojení ani transakci nedrž věhem volání externí služby (LLM apod.)
