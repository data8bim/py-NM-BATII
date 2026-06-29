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
import json
import codecs
from pyrevit import forms

def load_config():
    """
    Charge config.json en UTF-8 depuis la racine de l’extension PyNM-BATII.
    1) Chemin fixe : config.json à la racine de l’extension
    2) Si non trouvé, remonte l’arborescence jusqu’à la racine du disque
    """
    # 1) Chemin fixe : lib/ → ../config.json
    lib_dir  = os.path.dirname(__file__)
    ext_dir  = os.path.abspath(os.path.join(lib_dir, os.pardir))
    cfg_path = os.path.join(ext_dir, "config.json")
    if os.path.isfile(cfg_path):
        with codecs.open(cfg_path, "r", "utf-8") as f:
            return json.load(f)

    # 2) Ascension automatique
    current = lib_dir
    while True:
        candidate = os.path.join(current, "config.json")
        if os.path.isfile(candidate):
            with codecs.open(candidate, "r", "utf-8") as f:
                return json.load(f)
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent

    # Alerte et exception si non trouvé
    forms.alert(
        "Impossible de trouver config.json\n\n"
        "- Chemin testé : {0}".format(cfg_path),
        title="Erreur de configuration"
    )
    raise FileNotFoundError("config.json introuvable : {0}".format(cfg_path))
