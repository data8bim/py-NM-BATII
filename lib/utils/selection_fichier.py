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
import os
from pyrevit import forms

def pick_file_info(file_ext="*.dwg;*.pdf", title="Choisissez un fichier"):
    """
    Ouvre une boîte de dialogue pour choisir un fichier.
    Retourne un dict avec :
      - full_path : chemin complet vers le fichier
      - folder    : dossier contenant le fichier
      - filename  : nom du fichier avec son extension
      - basename  : nom du fichier sans extension
    Si aucun fichier n'est sélectionné, renvoie None.
    """
    path = forms.pick_file(file_ext=file_ext, title=title)
    if not path:
        return None

    folder   = os.path.dirname(path)
    filename = os.path.basename(path)
    basename = os.path.splitext(filename)[0]

    return {
        "full_path": path,
        "folder":    folder,
        "filename":  filename,
        "basename":  basename
    }
