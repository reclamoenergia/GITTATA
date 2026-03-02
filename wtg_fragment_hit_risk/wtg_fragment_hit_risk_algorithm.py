# -*- coding: utf-8 -*-
import math
import os
from datetime import datetime

import numpy as np
from osgeo import gdal
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeatureRequest,
    QgsGeometry,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterExtent,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
)


class WtgFragmentHitRiskAlgorithm(QgsProcessingAlgorithm):
    INPUT_WTG = "INPUT_WTG"
    FIELD_HHUB = "FIELD_HHUB"
    FIELD_DROTOR = "FIELD_DROTOR"
    RPM = "RPM"
    LFRAG = "LFRAG"
    A_TARGET = "A_TARGET"
    MAX_DIST = "MAX_DIST"
    PIXEL_SIZE = "PIXEL_SIZE"
    EXTENT = "EXTENT"
    OUTPUT_RASTER = "OUTPUT_RASTER"
    NODATA = "NODATA"

    STEP_ANGLE_DEG = 0.1
    BIN_WIDTH_M = 5.0
    G = 9.81

    def name(self):
        return "wtg_fragment_hit_risk_raster"

    def displayName(self):
        return "WTG Fragment Hit Risk Raster"

    def group(self):
        return "Risk"

    def groupId(self):
        return "risk"

    def shortHelpString(self):
        return (
            "Calcola un raster di probabilità di impatto per evento di distacco "
            "di un frammento da pala eolica, con area anello esatta."
        )

    def createInstance(self):
        return WtgFragmentHitRiskAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_WTG,
                "Layer WTG (punti)",
                [QgsProcessing.TypeVectorPoint],
            )
        )
        self.addParameter(
            QgsProcessingParameterField(
                self.FIELD_HHUB,
                "Campo altezza mozzo (Hhub, m)",
                parentLayerParameterName=self.INPUT_WTG,
                type=QgsProcessingParameterField.Numeric,
            )
        )
        self.addParameter(
            QgsProcessingParameterField(
                self.FIELD_DROTOR,
                "Campo diametro rotore (Drotor, m)",
                parentLayerParameterName=self.INPUT_WTG,
                type=QgsProcessingParameterField.Numeric,
            )
        )
        self.addParameter(QgsProcessingParameterNumber(self.RPM, "RPM", QgsProcessingParameterNumber.Double, 12.0, False, 0.0001))
        self.addParameter(
            QgsProcessingParameterNumber(self.LFRAG, "Lunghezza frammento Lfrag (m)", QgsProcessingParameterNumber.Double, 20.0, False, 0.0001)
        )
        self.addParameter(
            QgsProcessingParameterNumber(self.A_TARGET, "Area bersaglio A_target (m²)", QgsProcessingParameterNumber.Double, 1.0, False, 0.0001)
        )
        self.addParameter(
            QgsProcessingParameterNumber(self.MAX_DIST, "Distanza massima max_dist (m)", QgsProcessingParameterNumber.Double, 1500.0, False, 1.0)
        )
        self.addParameter(
            QgsProcessingParameterNumber(self.PIXEL_SIZE, "Dimensione pixel (unità CRS)", QgsProcessingParameterNumber.Double, None, False, 0.0001)
        )
        self.addParameter(QgsProcessingParameterExtent(self.EXTENT, "Estensione raster (default: extent layer buffer max_dist)", optional=True))
        self.addParameter(
            QgsProcessingParameterNumber(self.NODATA, "Valore NoData", QgsProcessingParameterNumber.Double, -9999.0)
        )
        self.addParameter(QgsProcessingParameterRasterDestination(self.OUTPUT_RASTER, "Raster rischio output"))

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT_WTG, context)
        if source is None:
            raise QgsProcessingException("Layer input WTG non valido.")

        crs = source.sourceCrs()
        self._validate_metric_crs(crs)

        field_hhub = self.parameterAsString(parameters, self.FIELD_HHUB, context)
        field_drotor = self.parameterAsString(parameters, self.FIELD_DROTOR, context)
        rpm = self.parameterAsDouble(parameters, self.RPM, context)
        lfrag = self.parameterAsDouble(parameters, self.LFRAG, context)
        a_target = self.parameterAsDouble(parameters, self.A_TARGET, context)
        max_dist = self.parameterAsDouble(parameters, self.MAX_DIST, context)
        pixel_size = self.parameterAsDouble(parameters, self.PIXEL_SIZE, context)
        extent = self.parameterAsExtent(parameters, self.EXTENT, context, crs)
        nodata = self.parameterAsDouble(parameters, self.NODATA, context)
        output_path = self.parameterAsOutputLayer(parameters, self.OUTPUT_RASTER, context)

        self._validate_positive_inputs(rpm, lfrag, a_target, max_dist, pixel_size)

        if extent.isNull():
            src_extent = source.sourceExtent()
            extent = src_extent.buffered(max_dist)

        features = list(source.getFeatures(QgsFeatureRequest()))
        if not features:
            raise QgsProcessingException("Il layer WTG non contiene feature.")

        wtg_data = []
        alpha_deg = np.arange(0.0, 360.0, self.STEP_ANGLE_DEG, dtype=np.float64)
        alpha_rad = np.deg2rad(alpha_deg)
        sin_a = np.sin(alpha_rad)
        cos_a = np.cos(alpha_rad)
        n_samples = alpha_deg.size
        if n_samples != 3600:
            feedback.pushWarning(f"Campionamento alpha inatteso: {n_samples}.")

        bin_count = int(math.ceil(max_dist / self.BIN_WIDTH_M))
        d_bins = np.arange(0, bin_count, dtype=np.float64) * self.BIN_WIDTH_M
        ring_areas = math.pi * ((d_bins + self.BIN_WIDTH_M) ** 2 - d_bins**2)

        feedback.pushInfo("Precalcolo distribuzioni radiali per turbina...")
        for idx, feat in enumerate(features):
            if feedback.isCanceled():
                return {}
            geom = feat.geometry()
            if geom is None or geom.isEmpty():
                raise QgsProcessingException(f"Feature {feat.id()} senza geometria valida.")

            pt = geom.asPoint()
            hhub = self._to_positive_float(feat[field_hhub], f"Hhub feature {feat.id()}")
            drotor = self._to_positive_float(feat[field_drotor], f"Drotor feature {feat.id()}")
            rb = drotor / 2.0
            tip_speed = (2.0 * math.pi * rpm * rb) / 60.0

            h0 = hhub + rb * sin_a
            vx = -tip_speed * sin_a
            vy = tip_speed * cos_a

            t_flight = (vy + np.sqrt(vy**2 + 2.0 * self.G * h0)) / self.G
            x_range = vx * t_flight
            r_vals = x_range + (2.0 / 3.0) * lfrag
            r_vals = np.where(r_vals < 0.0, 0.0, r_vals)

            in_range_mask = r_vals < max_dist
            counts = np.zeros(bin_count, dtype=np.int32)
            if np.any(in_range_mask):
                valid_r = r_vals[in_range_mask]
                bin_idx = np.floor(valid_r / self.BIN_WIDTH_M).astype(np.int32)
                np.add.at(counts, bin_idx, 1)

            p_hat = counts.astype(np.float64) / float(n_samples)
            p_hit = p_hat * (a_target / ring_areas)
            p_beyond = float(np.count_nonzero(~in_range_mask)) / float(n_samples)

            wtg_data.append(
                {
                    "fid": feat.id(),
                    "x": pt.x(),
                    "y": pt.y(),
                    "hhub": hhub,
                    "rb": rb,
                    "p_hit": p_hit.astype(np.float32),
                    "sum_p_hat": float(np.sum(p_hat)),
                    "p_beyond": p_beyond,
                }
            )

            if idx % 10 == 0:
                feedback.setProgress(int((idx + 1) / len(features) * 30.0))

        x_min = extent.xMinimum()
        y_min = extent.yMinimum()
        x_max = extent.xMaximum()
        y_max = extent.yMaximum()

        width = int(math.ceil((x_max - x_min) / pixel_size))
        height = int(math.ceil((y_max - y_min) / pixel_size))
        if width <= 0 or height <= 0:
            raise QgsProcessingException("Estensione/pixel_size non producono una griglia valida.")

        driver = gdal.GetDriverByName("GTiff")
        ds = driver.Create(output_path, width, height, 1, gdal.GDT_Float32)
        if ds is None:
            raise QgsProcessingException("Impossibile creare il raster di output.")

        gt = (x_min, pixel_size, 0.0, y_max, 0.0, -pixel_size)
        ds.SetGeoTransform(gt)
        ds.SetProjection(crs.toWkt())
        band = ds.GetRasterBand(1)
        band.SetNoDataValue(nodata)

        tile = 512
        total_tiles = math.ceil(width / tile) * math.ceil(height / tile)
        tile_counter = 0

        feedback.pushInfo("Rasterizzazione a blocchi in corso...")
        for y_off in range(0, height, tile):
            if feedback.isCanceled():
                ds = None
                return {}
            rows = min(tile, height - y_off)
            y_centers = y_max - (y_off + np.arange(rows) + 0.5) * pixel_size

            for x_off in range(0, width, tile):
                if feedback.isCanceled():
                    ds = None
                    return {}
                cols = min(tile, width - x_off)
                x_centers = x_min + (x_off + np.arange(cols) + 0.5) * pixel_size

                xx, yy = np.meshgrid(x_centers, y_centers)
                acc = np.zeros((rows, cols), dtype=np.float32)

                for wtg in wtg_data:
                    dx = xx - wtg["x"]
                    dy = yy - wtg["y"]
                    dist = np.hypot(dx, dy)
                    mask = dist < max_dist
                    if not np.any(mask):
                        continue
                    idx_bin = np.floor(dist[mask] / self.BIN_WIDTH_M).astype(np.int32)
                    acc[mask] += wtg["p_hit"][idx_bin]

                band.WriteArray(acc, x_off, y_off)
                tile_counter += 1
                feedback.setProgress(30 + int(tile_counter / total_tiles * 70.0))

        band.FlushCache()
        ds.FlushCache()
        ds = None

        self._write_algorithm_description(output_path, rpm, lfrag, a_target, max_dist, pixel_size, nodata, n_samples, wtg_data)

        feedback.pushInfo("Elaborazione completata.")
        return {self.OUTPUT_RASTER: output_path}

    def _validate_metric_crs(self, crs: QgsCoordinateReferenceSystem):
        if not crs.isValid():
            raise QgsProcessingException("CRS non valido.")
        unit_name = crs.mapUnits().name.lower()
        if "meter" not in unit_name and "metre" not in unit_name:
            raise QgsProcessingException(
                "CRS non metrico: usare un layer in metri (es. UTM) o riproiettare prima dell'esecuzione."
            )

    def _validate_positive_inputs(self, rpm, lfrag, a_target, max_dist, pixel_size):
        values = {
            "RPM": rpm,
            "LFRAG": lfrag,
            "A_TARGET": a_target,
            "MAX_DIST": max_dist,
            "PIXEL_SIZE": pixel_size,
        }
        for name, val in values.items():
            if val <= 0:
                raise QgsProcessingException(f"Parametro {name} deve essere > 0.")

    def _to_positive_float(self, value, label):
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise QgsProcessingException(f"Valore non numerico per {label}.") from exc
        if number <= 0:
            raise QgsProcessingException(f"Valore {label} deve essere > 0.")
        return number

    def _write_algorithm_description(self, output_path, rpm, lfrag, a_target, max_dist, pixel_size, nodata, n_samples, wtg_data):
        folder = os.path.dirname(output_path)
        md_path = os.path.join(folder, "algorithm_description.md")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        table_lines = ["| Feature ID | Hhub [m] | Rb [m] | Somma p_hat entro max_dist | Probabilità oltre max_dist |", "|---:|---:|---:|---:|---:|"]
        for w in wtg_data:
            table_lines.append(
                f"| {w['fid']} | {w['hhub']:.3f} | {w['rb']:.3f} | {w['sum_p_hat']:.6f} | {w['p_beyond']:.6f} |"
            )

        text = f"""# Descrizione algoritmica - WTG Fragment Hit Risk Raster

Data generazione: **{now}**

## 1) Scopo e significato dell'output
Questo algoritmo produce un raster GeoTIFF float32 in cui ogni pixel rappresenta la **probabilità per evento di distacco** che un bersaglio di area reale `A_target` posto nel centro del pixel venga colpito da almeno un frammento proveniente da una turbina del layer input.  
Il valore è una somma dei contributi per turbina (ipotesi di indipendenza tra turbine) e **non** include frequenze annuali di distacco.

## 2) Input e parametri (unità)
- Layer WTG puntuale con campi:
  - `Hhub` [m]: altezza mozzo.
  - `Drotor` [m]: diametro rotore (`Rb = Drotor/2`).
- Parametri globali:
  - `rpm` [giri/min]
  - `Lfrag` [m]
  - `A_target` [m²], usato per scalare la probabilità areale.
  - `step_angle_deg` = {self.STEP_ANGLE_DEG}° (fisso)
  - `bin_width_m` = {self.BIN_WIDTH_M} m (fisso)
  - `max_dist_m` = {max_dist}
  - `pixel_size` = {pixel_size}
- `nodata_value` = {nodata}

## 3) Ipotesi e assunzioni
1. Distacco al tip della pala.
2. Moto parabolico senza resistenza aerodinamica.
3. Gravità costante `g = {self.G} m/s²`.
4. Terreno piano.
5. Angolo di fase pala `α` uniforme in [0°, 360°).
6. Azimut di ricaduta uniforme (isotropia radiale).
7. `rpm` costante per tutte le turbine.
8. Nessun rateo annuo di occorrenza incluso.

## 4) Modello fisico
### 4.1 Velocità tangenziale al tip
Con `Rb = Drotor/2`, il modulo della velocità tangenziale è:

`T = (2π * rpm * Rb) / 60`.

### 4.2 Quota di rilascio
Per ogni fase `α`:

`H0(α) = Hhub + Rb * sin(α)`.

### 4.3 Componenti di velocità tangenziale
La direzione tangenziale è ottenuta ruotando il raggio di ±90°. Nella presente implementazione:

- `Vx = -T * sin(α)`
- `Vy =  T * cos(α)`

(implementazione coerente con logica tangenziale robusta; la distanza finale viene poi resa non-negativa).

### 4.4 Tempo di volo e gittata
Tempo di volo:

`t = (Vy + sqrt(Vy² + 2 g H0)) / g`.

Gittata balistica:

`X = Vx * t`.

Correzione frammento:

`R = X + (2/3) * Lfrag`.

La correzione `(2/3)Lfrag` rappresenta un'approssimazione dell'estensione utile del frammento/baricentro. Se `R < 0`, viene clippata a 0.

## 5) Modello probabilistico
- Campionamento angolare: `α = 0.0, 0.1, ..., 359.9`, quindi `N = {n_samples}`.
- Binning radiale su intervalli da 5 m: `d_j = 0, 5, 10, ...`.
- Stima di probabilità in corona:

`p_hat(d_j) = count_j / N`.

La massa probabilistica oltre `max_dist_m` è tracciata separatamente per turbina.

### 5.1 Area corona anulare esatta
Per ogni bin `[d, d+5)`:

`A_ring_exact(d) = π((d+5)^2 - d^2)`.

Formula valida anche a `d = 0`.

### 5.2 Probabilità di colpire un bersaglio reale

`p_hit(d) = p_hat(d) * (A_target / A_ring_exact(d))`.

## 6) Rasterizzazione
1. Generazione griglia su `extent` e `pixel_size`.
2. Per ogni pixel (centro pixel) e turbina:
   - distanza planimetrica `dist` centro-pixel ↔ WTG;
   - se `dist > max_dist`: contributo nullo;
   - altrimenti `d_j = floor(dist/5)*5` e lookup di `p_hit(d_j)`.
3. Valore finale pixel = somma contributi di tutte le turbine.

## 7) Limitazioni
- Assenza drag e vento.
- Terreno piano.
- RPM costante.
- Nessun occurrence rate annuale.
- Indipendenza tra turbine nella somma contributi.

## 8) Verifiche interne e sanity checks
- `sum(p_hat)` entro il range raster `<= 1`, con quota residua oltre `max_dist`.
- Simmetria radiale del campo per singola turbina (attesa su geometria piana).
- Pattern ad anelli con intensità generalmente decrescente in funzione dell'area anulare.

Tabella diagnostica per turbina:

{os.linesep.join(table_lines)}

## 9) Possibili estensioni future
- Introduzione di drag aerodinamico e vento.
- Rateo di distacco annuo per passare a rischio temporale (annuo/pluriennale).
- Orography-aware con DSM/DTM.
- RPM variabile con curva di potenza e condizioni meteo.
- Distribuzioni non uniformi di fase/azimut basate su dinamica reale.
"""

        with open(md_path, "w", encoding="utf-8") as f:
            f.write(text)
