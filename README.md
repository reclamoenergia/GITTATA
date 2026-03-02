# Plugin QGIS: WTG Fragment Hit Risk

Plugin Processing per QGIS 3.x che calcola un raster di rischio di impatto da frammento espulso da pale eoliche con **area anello calcolata in modo esatto**.

## Contenuto
Cartella plugin zip-ready:

- `wtg_fragment_hit_risk/metadata.txt`
- `wtg_fragment_hit_risk/__init__.py`
- `wtg_fragment_hit_risk/plugin.py`
- `wtg_fragment_hit_risk/provider.py`
- `wtg_fragment_hit_risk/wtg_fragment_hit_risk_algorithm.py`

## Installazione
1. Comprimere in zip la cartella `wtg_fragment_hit_risk` (non includere file esterni).
2. In QGIS: **Plugin > Gestisci e Installa Plugin > Installa da ZIP**.
3. Abilitare il plugin.
4. Aprire Toolbox Processing, gruppo **Risk**, algoritmo **WTG Fragment Hit Risk Raster**.

## Parametri algoritmo
- `INPUT_WTG`: layer punti WTG.
- `FIELD_HHUB`: campo numerico altezza mozzo (m).
- `FIELD_DROTOR`: campo numerico diametro rotore (m).
- `RPM`: giri/min.
- `LFRAG`: lunghezza frammento (m).
- `A_TARGET`: area bersaglio (m²), default 1.0.
- `MAX_DIST`: distanza massima (m), default 1500.
- `PIXEL_SIZE`: obbligatorio.
- `EXTENT`: obbligatorio.
- `OUTPUT_RASTER`: GeoTIFF float32.

Output secondario automatico: `algorithm_description.md` nella stessa cartella del raster.

## Validazioni implementate
- CRS metrico obbligatorio.
- Valori positivi per `Hhub`, `Drotor`, `RPM`, `LFRAG`, `A_TARGET`, `MAX_DIST`, `PIXEL_SIZE`.
- Gestione cancellazione via `QgsProcessingFeedback`.

## Test/validazione consigliati
1. **Caso base radiale**
   - Una sola turbina al centro dell'extent.
   - `rpm` e geometria plausibili.
   - Osservare pattern a corone concentriche nel raster.
2. **Confronto con foglio Excel (se disponibile)**
   - Per una turbina, confrontare la distribuzione `p_hat(d)` per i primi bin.
3. **Check area anulare a d=0**
   - Verificare che la formula `A_ring_exact(0)=π(5²-0²)` venga usata senza eccezioni.
4. **Massa probabilistica oltre max_dist**
   - Controllare nel file `algorithm_description.md` che per ogni turbina sia riportata la quota oltre soglia.

## Note prestazionali
- Calcolo radiale per turbina con NumPy.
- Rasterizzazione a blocchi (tile 512x512) per contenere l'uso RAM.
