# -*- coding: utf-8 -*-

# Copyright (C) 2026 data8bim (d8b)
#
# This file is part of py-NM-BATII.
#
# py-NM-BATII is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# py-NM-BATII is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with py-NM-BATII. If not, see <https://www.gnu.org/licenses/>.

"""
NM-BATII — Onglet personnalisé

Regroupe dans un onglet ruban dédié des panneaux pris dans d'autres onglets
(natifs Revit ou add-ins tiers), et permet de masquer des onglets devenus
vides. Équivalent NM-BATII de "AG Custom Ribbon Tab Builder".
"""

import os
import sys

from pyrevit import forms

_lib = os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'lib')
if _lib not in sys.path:
    sys.path.insert(0, _lib)

try:
    from nm_ribbon import ui
except Exception as e:
    forms.alert(u"Erreur NM-BATII : {0}".format(str(e)), exitscript=True)

_xaml = os.path.join(os.path.dirname(__file__), 'WPFWindow.xaml')

try:
    ui.ouvrir(_xaml)
except Exception as e:
    forms.alert(u"Erreur NM-BATII : {0}".format(str(e)), exitscript=True)
