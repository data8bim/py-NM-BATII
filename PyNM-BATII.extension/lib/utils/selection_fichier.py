# -*- coding: utf-8 -*-
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
