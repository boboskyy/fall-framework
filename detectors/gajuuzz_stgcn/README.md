# gajuuzz_stgcn - ST-GCN (AlphaPose + TSSTG)

Adapter detektora upadków z repozytorium [GajuuzZ/Human-Falling-Detect-Tracks](https://github.com/GajuuzZ/Human-Falling-Detect-Tracks).

Pipeline: Tiny-YOLO (detekcja osoby) → SPPE FastPose (poza 2D) → tracker SORT
(bufor 30 klatek) → ST-GCN/TSSTG (klasyfikacja akcji). Klatka jest oznaczana jako
upadek, gdy akcja śledzonego obiektu to `Fall Down`; agregacja czasowa odbywa się
wspólnym progiem frameworka (`min_fall_frames`).

## Przygotowanie (przed buildem)

Upstream i wagi nie są wersjonowane w tym repozytorium - katalog `repo/` trzeba
wypełnić lokalnie:

```bash
cd detectors/gajuuzz_stgcn
git clone https://github.com/GajuuzZ/Human-Falling-Detect-Tracks repo
```

Następnie pobierz wagi do `repo/Models/` (linki Google Drive w README upstreamu):
Tiny-YOLO one-class, SPPE FastPose (ResNet50) oraz `tsstg-model.pth` (ST-GCN).
Ścieżki są zaszyte w `DetectorLoader.py` / `PoseEstimateLoader.py` /
`ActionsEstLoader.py` upstreamu.

## Build i uruchomienie

```bash
fallfw build gajuuzz_stgcn     # build z GPU: DEVICE=gpu
fallfw start gajuuzz_stgcn
fallfw detect video.mp4 -d gajuuzz_stgcn --sync
```

Uwaga: klasyfikator działa na oknie ~30 klatek na śledzony obiekt - bardzo
krótkie klipy (< 30 klatek) nie dadzą decyzji.
