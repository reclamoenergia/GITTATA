# -*- coding: utf-8 -*-
"""Entry point del plugin QGIS."""


def classFactory(iface):
    from .plugin import WtgFragmentHitRiskPlugin

    return WtgFragmentHitRiskPlugin(iface)
