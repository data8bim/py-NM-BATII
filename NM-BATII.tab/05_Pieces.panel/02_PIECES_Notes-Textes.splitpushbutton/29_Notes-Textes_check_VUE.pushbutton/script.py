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


#__title__ = "Réinitialiser ✔✘"
#__doc__ = """Réinitialiser les checks ✔ et ✘
#Description : Réinitialiser les checks ✔ et ✘ des notes textuelles de la sélection ou de la vue active (si aucune sélection préalable).

#Auteur : data8bim (d8b)
#"""


import os
import sys
from pyrevit import revit, script
from Autodesk.Revit.DB import TextNote, FilteredElementCollector
from Autodesk.Revit.UI.Selection import ISelectionFilter

# -------------------------------------------------------------------------
# 1) Chargement des styles WPF
# -------------------------------------------------------------------------
script_dir = os.path.dirname(__file__)
lib_dir    = os.path.abspath(os.path.join(script_dir, "..", "..", "..", "lib"))
if lib_dir not in sys.path:
    sys.path.append(lib_dir)

from dialogs.dialogs_styles_loader import load as load_styles
load_styles(lib_dir=lib_dir)

# -------------------------------------------------------------------------
# 2) Chargement de la fenêtre XAML
# -------------------------------------------------------------------------
from pyrevit.forms import WPFWindow

xaml_path = os.path.join(script_dir, "ResultWindow.xaml")

class ResultWindow(WPFWindow):
    def __init__(self, message):
        super(ResultWindow, self).__init__(xaml_path)
        self.txtMessage.Text = message
        self.btnClose.Click += self.close

    def close(self, sender, e):
        self.Close()

# -------------------------------------------------------------------------
# 3) Nettoyage des notes
# -------------------------------------------------------------------------
doc   = revit.doc
uidoc = revit.uidoc

# Supprimer à la fois "✔ " et "✘ "
MARKS = (u"✔ ", u"✘ ")

selected_ids = uidoc.Selection.GetElementIds()
notes_to_clean = []

if selected_ids:
    for eid in selected_ids:
        el = doc.GetElement(eid)
        if isinstance(el, TextNote):
            notes_to_clean.append(el)
else:
    active_view = doc.ActiveView
    notes_to_clean = list(
        FilteredElementCollector(doc, active_view.Id)
        .OfClass(TextNote)
        .ToElements()
    )

if not notes_to_clean:
    ResultWindow("❌ Aucune note textuelle trouvée.").ShowDialog()
    script.exit()

count = 0
with revit.Transaction("Nettoyer ✔✘ dans Notes"):
    for note in notes_to_clean:
        text = note.Text
        for mark in MARKS:
            if text.startswith(mark):
                note.Text = text[len(mark):]
                count += 1
                break

# -------------------------------------------------------------------------
# 4) Affichage du résultat
# -------------------------------------------------------------------------
if count == 0:
    msg = u"✅ Aucune note à nettoyer."
elif count == 1:
    msg = u"✅ 1 note nettoyée."
else:
    msg = u"✅ {} notes nettoyées.".format(count)

ResultWindow(msg).ShowDialog()
