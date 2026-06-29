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
import re
from utils.extrac_nom_fichier_convention import delimiter_from_regex

def normalize_level_code(level_code):
    """
    Normalise un code niveau en preservant son prefixe complet.
    Ex. 'R+2' -> 'R+02', 'F-1' -> 'F-01', 'T+3' -> 'T+03', 'O+0' -> 'O+00'.
    Retro-compatibilite : '3' -> 'R+03' (chiffres seuls -> R+ par defaut).
    """
    if not level_code:
        return ""
    m = re.match(r"([RFTO])([+-])(\d+)", level_code)
    if m:
        prefix, sign, num = m.groups()
        return "{0}{1}{2}".format(prefix, sign, num.zfill(2))
    m = re.search(r"\d+", level_code)
    return "R+{0}".format(m.group(0).zfill(2)) if m else ""

def build_rvt_name(info, naming_cfg):
    """
    Construit le nom .rvt en concaténant :
    site, building, level, half, producteur, site_short avec le délimiteur.
    """
    delim = delimiter_from_regex(naming_cfg.get("regle_regex", ""))
    keys  = ["site","building","level","half","producteur","specialite","site_short"]
    parts = [info.get(k, "") for k in keys]
    filename = delim.join([p for p in parts if p])
    return filename + ".rvt"
