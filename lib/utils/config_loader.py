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

def chemin_config():
    """
    Chemin de config.json, ou None s’il reste introuvable.

    1) Chemin fixe : config.json à la racine de l’extension
    2) Si non trouvé, remonte l’arborescence jusqu’à la racine du disque
    """
    # 1) Chemin fixe : lib/ → ../config.json
    lib_dir  = os.path.dirname(__file__)
    ext_dir  = os.path.abspath(os.path.join(lib_dir, os.pardir))
    cfg_path = os.path.join(ext_dir, "config.json")
    if os.path.isfile(cfg_path):
        return cfg_path

    # 2) Ascension automatique
    current = lib_dir
    while True:
        candidate = os.path.join(current, "config.json")
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def load_config():
    """Charge config.json en UTF-8 depuis la racine de l’extension PyNM-BATII."""
    cfg_path = chemin_config()
    if cfg_path:
        with codecs.open(cfg_path, "r", "utf-8") as f:
            return json.load(f)

    # Alerte et exception si non trouvé
    lib_dir  = os.path.dirname(__file__)
    ext_dir  = os.path.abspath(os.path.join(lib_dir, os.pardir))
    attendu  = os.path.join(ext_dir, "config.json")
    forms.alert(
        "Impossible de trouver config.json\n\n"
        "- Chemin testé : {0}".format(attendu),
        title="Erreur de configuration"
    )
    raise FileNotFoundError("config.json introuvable : {0}".format(attendu))


def save_config(cfg):
    """
    Réécrit config.json. Retourne True si l’écriture a abouti.

    Même mise en forme que la fenêtre des paramètres (indent=2, non-ASCII
    conservé, clés triées) : les deux écrivent le même fichier, un écart de
    formatage produirait des diffs illisibles à chaque aller-retour.

    sort_keys est ce qui rend ces diffs lisibles : l'ordre d'un dict
    IronPython 2.7 n'est pas stable d'une exécution à l'autre, et sans tri
    chaque écriture réordonnait le fichier entier.
    """
    cfg_path = chemin_config()
    if not cfg_path:
        return False
    try:
        with codecs.open(cfg_path, "w", "utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2,
                      separators=(u', ', u': '), sort_keys=True)
        return True
    except Exception:
        return False


def set_valeur(section, cle, valeur):
    """
    Écrit UNE valeur dans une section de config.json, sans toucher au reste.

    Relit le fichier juste avant d’écrire, plutôt que de réenregistrer une
    configuration chargée plus tôt : une palette non modale vit longtemps, et
    la fenêtre des paramètres a pu enregistrer entre-temps. Réécrire une copie
    périmée effacerait ces réglages-là.

    Retourne True si l’écriture a abouti.
    """
    try:
        cfg = load_config()
    except Exception:
        return False
    if not isinstance(cfg.get(section), dict):
        cfg[section] = {}
    cfg[section][cle] = valeur
    return save_config(cfg)
