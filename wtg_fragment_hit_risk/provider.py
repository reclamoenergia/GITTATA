# -*- coding: utf-8 -*-
from qgis.core import QgsProcessingProvider

from .wtg_fragment_hit_risk_algorithm import WtgFragmentHitRiskAlgorithm


class WtgRiskProvider(QgsProcessingProvider):
    def loadAlgorithms(self):
        self.addAlgorithm(WtgFragmentHitRiskAlgorithm())

    def id(self):
        return "wtg_risk"

    def name(self):
        return "Risk"

    def longName(self):
        return self.name()
