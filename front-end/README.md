# JudoIQ Front-End

Flutterowy frontend webowy, przygotowany pod pozniejsze uruchomienie rowniez na mobile.

## Struktura

- `lib/app` - konfiguracja aplikacji i routing.
- `lib/features/analysis` - ekran analizy i podsumowania walki.
- `lib/features/video_player` - przyszly odtwarzacz anotowanego wideo.
- `lib/features/reports` - widoki raportow i listy akcji.
- `lib/core/api` - komunikacja z backendem.
- `lib/core/models` - modele danych zgodne z kontraktami z `../core`.
- `lib/core/theme` - motyw UI.
- `lib/shared` - wspolne widgety.

## Uruchomienie docelowe

```sh
flutter pub get
flutter run -d chrome
```
