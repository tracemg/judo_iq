# API Contracts

Tu trafia opis sposobu przekazywania wynikow analizy z backendu do frontendu.

Planowany kierunek:
- backend zapisuje wynik analizy jako JSON zgodny z `core/schemas/analysis_result.schema.json`;
- API zwraca sciezki do raportu tekstowego i anotowanego wideo;
- Flutter Web czyta dane z API i renderuje statystyki, zdarzenia oraz podglad wideo.
