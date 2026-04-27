# -*- coding: utf-8 -*-
import re

def extract_file_name_info(name, naming_cfg):
    """
    Extrait site, building, level, half, prod, site_short depuis 'name'.
    - Si utiliser_regex → regex
    - Sinon split sur delimiteur ou espace
    """
    if naming_cfg.get("utiliser_regex", False):
        pat = naming_cfg.get("regle_regex", "")
        m = re.match(pat, name)
        return m.groupdict() if m else None

    delim    = naming_cfg.get("delimiteur", "_")
    splitter = "[{0} ]+".format(re.escape(delim))
    parts    = re.split(splitter, name)

    pos_map = {
        "site":       naming_cfg.get("pos_code_site", 0),
        "building":   naming_cfg.get("pos_code_bat", 1),
        "level":      naming_cfg.get("pos_code_niv", 2),
        "half":       naming_cfg.get("pos_code_demi_niv", 3),
        "prod":       naming_cfg.get("pos_code_prod", 4),
        "site_short": naming_cfg.get("pos_nom_site_court", 5),
    }

    max_idx = max(pos_map.values())
    if len(parts) <= max_idx:
        parts += [""] * (max_idx + 1 - len(parts))

    return { key: parts[idx] for key, idx in pos_map.items() }
