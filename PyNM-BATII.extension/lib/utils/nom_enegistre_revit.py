# -*- coding: utf-8 -*-
import re

def normalize_level_code(level_code):
    """
    Reformate un code niveau en 'R+XX'.
    Ex. '3' → 'R+03', '12' → 'R+12'.
    """
    m = re.search(r"\d+", level_code or "")
    return "R+{0}".format(m.group(0).zfill(2)) if m else ""

def build_rvt_name(info, naming_cfg):
    """
    Construit le nom .rvt en concaténant :
    site, building, level, half, prod, site_short avec le délimiteur.
    """
    delim = naming_cfg.get("delimiteur", "_")
    keys  = ["site","building","level","half","prod","site_short"]
    parts = [info.get(k, "") for k in keys]
    filename = delim.join([p for p in parts if p])
    return filename + ".rvt"
