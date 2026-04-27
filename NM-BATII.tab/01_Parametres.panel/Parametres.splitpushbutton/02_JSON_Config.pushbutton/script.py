# -*- coding: utf-8 -*-

# Copyright 2026 data8bim (d8b)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.



#__title__ = 'JSON Config'
#__author__ = 'data8bim (d8b)'

import os, sys, subprocess
from pyrevit import forms

# 1) Localiser la racine .extension
this_script = os.path.abspath(__file__)
cur = os.path.dirname(this_script)
while not cur.lower().endswith('.extension'):
    parent = os.path.dirname(cur)
    if parent == cur:
        forms.alert(
            "⛔ Impossible de trouver le dossier .extension\n{}".format(this_script),
            title="Config DWG", exitscript=True
        )
    cur = parent
ext_root = cur

# 2) Calculer config_path
config_path = os.path.join(ext_root, 'config.json')

# 3) Si absent, on crée un fichier JSON d’exemple
if not os.path.isfile(config_path):
    sample = {
      "use_regex": False,
      "delimiter": "_",
      "site_index": 0,
      "building_index": 1,
      "level_index": 2,
      "filename_pattern": "^(?P<site>[^_]+)_(?P<building>[^_]+)_(?P<level>.+)$",
      "site_group": "site",
      "building_group": "building",
      "level_group": "level",
      "full_level_suffix": "_0"
    }
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            import json
            json.dump(sample, f, indent=2)
        forms.alert(
            "Un config.json d’exemple a été créé :\n{}".format(config_path),
            title="Config DWG"
        )
    except Exception as e:
        forms.alert(
            "❌ Impossible de créer config.json :\n{}".format(e),
            title="Config DWG", exitscript=True
        )

# 4) Tenter d’ouvrir le config.json
try:
    if sys.platform.startswith("win"):
        os.startfile(config_path)
    else:
        cmd = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.Popen([cmd, config_path])
except Exception as e1:
    # fallback vers Notepad
    try:
        subprocess.Popen(["notepad.exe", config_path])
    except Exception as e2:
        forms.alert(
            "❌ Échec à l’ouverture :\n{}\n{}".format(e1, e2),
            title="Config DWG", exitscript=True
        )
