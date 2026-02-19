# FallFW - Framework do detekcji upadkow

Framework mikroserwisowy opakowujacy rozne algorytmy detekcji upadkow jako kontenery Docker z ustandaryzowanym REST API. Umozliwia uruchomienie roznych detektorow na tym samym nagraniu wideo i porownanie ich wynikow.

Autor: Karol Bobowski.

## Wymagania

- **Docker** (z Docker Compose)
- **Git**
- **Python 3.10+** (tylko dla CLI)

## Start

```bash
git clone https://github.com/boboskyy/fall-framework.git
cd fall-framework
```

### 1. Uruchomienie frameworka

```bash
python3 launch.py
```

Buduje i uruchamia **Gateway** (port 3000) oraz **Frontend** (port 2999). Otworz http://localhost:2999 w przegladarce.

### 2. Instalacja CLI (opcjonalnie)

```bash
pip install click requests rich simple-term-menu
```

### 3. Tryb interaktywny

CLI posiada tryb interaktywny z nawigacja strzalkami - wystarczy uruchomic bez argumentow:

```bash
python -m cli
```

### 4. Pobranie repozytoriow detektorow

```bash
python -m cli download --all
```

### 5. Budowanie obrazow Docker

```bash
python -m cli build --all
```

### 6. Uruchomienie detektora i detekcja

```bash
python -m cli start dzungvpham_twostream_cnn
python -m cli detect video.mp4 -d dzungvpham_twostream_cnn --sync
```

### 7. Porownanie wielu detektorow

```bash
python -m cli start --all
python -m cli compare video.mp4 -d dzungvpham_twostream_cnn,taufeeque_human_fall,cwlroda_openpifpaf,boboskyy_fall_detect
```

## Detektory

| Detektor | Kategoria | Technologia | Oryginalne repozytorium |
|----------|-----------|-------------|------------------------|
| dzungvpham_twostream_cnn | Hybrydowy | MobileNetV2 + Motion History Image (TensorFlow/Keras) | [dzungvpham/fall-detection-two-stream-cnn](https://github.com/dzungvpham/fall-detection-two-stream-cnn) |
| taufeeque_human_fall | Estymacja pozy | OpenPifPaf 0.13.6 + LSTM (PyTorch) | [taufeeque9/HumanFallDetection](https://github.com/taufeeque9/HumanFallDetection) |
| cwlroda_openpifpaf | Estymacja pozy | OpenPifPaf 0.11.8 + tracker centroidowy (PyTorch) | [cwlroda/falldetection_openpifpaf](https://github.com/cwlroda/falldetection_openpifpaf) |
| boboskyy_fall_detect | Estymacja pozy | MediaPipe + LSTM (TensorFlow/Keras) | - |

## Porty

| Serwis | Port |
|--------|------|
| Frontend | 2999 |
| Gateway API | 3000 |
| dzungvpham_twostream_cnn | 3001 |
| taufeeque_human_fall | 3002 |
| cwlroda_openpifpaf | 3003 |
| boboskyy_fall_detect | 3004 |

## Struktura projektu

```
fall-framework/
├── core/           Biblioteka wspoldzielona (modele, klasa bazowa, fabryka Flask)
├── gateway/        Brama REST API + orkiestracja (port 3000)
├── cli/            Interfejs wiersza polecen (Click)
├── detectors/      Katalog detektorow + szablon
├── frontend/       Frontend Next.js (oddzielny build)
├── shared/         Wspoldzielony wolumin Docker (uploady, stan)
├── launch.py       Launcher
└── docker-compose.yml
```
