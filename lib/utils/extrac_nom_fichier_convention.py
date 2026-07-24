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
import re


# ---------------------------------------------------------------------------
# Helpers internes
# ---------------------------------------------------------------------------

def _safe_name(gid):
    """Convertit un id (peut contenir '-') en nom valide pour un groupe regex Python."""
    return gid.replace("-", "_")


def _read_quantifier(pattern, i):
    """
    Lit le quantificateur qui commence a la position i dans pattern.
    Retourne (min_repeat, new_i).
    Gere : *, +, ?, {n}, {n,}, {n,m}, {n,m}?
    """
    if i >= len(pattern):
        return 1, i
    c = pattern[i]
    if c == '*':
        return 0, i + 1
    if c == '+':
        return 1, i + 1
    if c == '?':
        return 0, i + 1
    if c == '{':
        j = pattern.find('}', i + 1)
        if j == -1:
            return 1, i
        inner = pattern[i + 1:j]
        parts = inner.split(',')
        try:
            mn = int(parts[0].strip())
        except ValueError:
            return 1, i
        return mn, j + 1
    return 1, i


def _regex_min_len(pattern):
    """
    Estime la longueur minimale d'une chaine correspondant au pattern regex.
    Supporte les constructions courantes : classes de caracteres, quantificateurs,
    groupes non-capturants, alternatives, echappements.
    """
    total = 0
    i = 0
    n = len(pattern)
    while i < n:
        c = pattern[i]
        if c == '\\':
            # Echappement : consomme 1 caractere
            i += 2
            min_q, i = _read_quantifier(pattern, i)
            total += 1 * min_q
        elif c == '[':
            # Classe de caracteres : 1 caractere
            j = i + 1
            if j < n and pattern[j] == '^':
                j += 1
            if j < n and pattern[j] == ']':
                j += 1
            while j < n and pattern[j] != ']':
                j += 1
            i = j + 1
            min_q, i = _read_quantifier(pattern, i)
            total += 1 * min_q
        elif c == '(':
            # Groupe — trouve la fermeture
            depth = 1
            j = i + 1
            while j < n and depth > 0:
                if pattern[j] == '\\':
                    j += 2
                    continue
                if pattern[j] == '(':
                    depth += 1
                elif pattern[j] == ')':
                    depth -= 1
                j += 1
            inner = pattern[i + 1:j - 1]
            # Retire les flags (?:) etc.
            if inner.startswith('?:'):
                inner = inner[2:]
            elif inner.startswith('?'):
                inner = ''
            # Alternative : prendre le min des branches
            alts = re.split(r'(?<!\\)\|', inner)
            min_inner = min(_regex_min_len(a) for a in alts) if alts else 0
            i = j
            min_q, i = _read_quantifier(pattern, i)
            total += min_inner * min_q
        elif c == '|':
            # Fin de branche — s'arrete (gere par le niveau superieur)
            break
        elif c in '.^$':
            i += 1
            if c == '.':
                min_q, i = _read_quantifier(pattern, i)
                total += 1 * min_q
        else:
            # Caractere litteral
            i += 1
            min_q, i = _read_quantifier(pattern, i)
            total += 1 * min_q
    return total


def _tpl_deps(tpl_str, known_ids=None):
    """Retourne l'ensemble des ids references dans un template qui sont des templates connus."""
    refs = {tok[1:-1] for tok in re.findall(r'\{([^}]+)\}', tpl_str)}
    if known_ids is not None:
        return refs & known_ids
    return refs


def _topo_sort(templates_list):
    """
    Trie les templates (liste de dicts avec 'id' et 'template') en ordre
    topologique : un template apparait apres tous ceux dont il depend.
    Leve ValueError si une dependance circulaire est detectee.
    Retourne la liste triee.
    """
    by_id  = {t["id"]: t for t in templates_list}
    deps   = {t["id"]: _tpl_deps(t.get("template", ""), set(by_id)) for t in templates_list}
    sorted_ids = []
    visiting   = set()
    visited    = set()

    def visit(nid):
        if nid in visited:
            return
        if nid in visiting:
            raise ValueError("Dependance circulaire detectee dans les templates : {}".format(nid))
        visiting.add(nid)
        for dep in deps.get(nid, set()):
            visit(dep)
        visiting.discard(nid)
        visited.add(nid)
        sorted_ids.append(nid)

    for t in templates_list:
        visit(t["id"])

    return [by_id[nid] for nid in sorted_ids]


def _build_sous_template_regex(st, groups_map, sous_tpl_regex, val_nul_global):
    """
    Construit la regex composite d'un sous-template.

    Resout les tokens {id} (groupes atomiques) depuis groups_map et les tokens {tpl-*}
    depuis sous_tpl_regex (deja resolus en amont par tri topologique).
    La valeur_si_nul est calculee dynamiquement.

    Retourne la regex composite (sans ancre).
    """
    sub_tpl = st.get("template", "")
    composite = ""
    null_len = 0
    for tok in re.split(r'(\{[^}]+\})', sub_tpl):
        if not tok:
            continue
        if tok.startswith("{") and tok.endswith("}"):
            ref_id = tok[1:-1]
            if ref_id in sous_tpl_regex:
                ref_regex = sous_tpl_regex[ref_id]["regex"]
                # Retire l'alternative valeur_si_nul du sous-template imbriquee
                # (elle sera recalculee globalement pour ce template)
                parts = ref_regex.split("|")
                ref_regex = parts[0] if len(parts) > 1 else ref_regex
            else:
                ref_regex = groups_map.get(ref_id, {}).get("regex", "")
            composite += ref_regex
            null_len  += _regex_min_len(ref_regex)
        else:
            lit = re.escape(tok)
            composite += lit
            null_len  += len(tok)
    if val_nul_global and composite and null_len > 0:
        val_nul = val_nul_global * null_len
        composite = composite + "|" + re.escape(val_nul)
    return composite


# ---------------------------------------------------------------------------
# API publique principale
# ---------------------------------------------------------------------------

def get_convention_template(cfg, tpl_id, default=""):
    """
    Retourne le template de nommage identifie par tpl_id.

    Cherche d'abord dans conventions_nommage.templates, puis dans tous les
    tableaux conventions_nommage.nommage_* (nommage_niveaux,
    nommage_niveaux_code, nommage_presentations, nommage_vues...).

    Cette seconde passe est indispensable : les tables de nommage autres que
    "Fichiers" vivent dans ces tableaux frères. Sans elle, la recherche
    echouait toujours et l'appelant retombait silencieusement sur sa valeur
    'default' codee en dur — la table affichee dans 01_Parametres etait donc
    modifiable sans aucun effet. Meme parcours que build_regex(), qui lui
    lisait deja les tableaux nommage_*.

    Un template vide est ignore (on poursuit la recherche, puis on renvoie
    'default') : mieux vaut le nommage par defaut qu'un nom vide.

    Retourne 'default' si l'id n'est trouve nulle part.
    """
    cnv = cfg.get("conventions_nommage", {}) if isinstance(cfg, dict) else {}
    if not isinstance(cnv, dict):
        return default

    # 1) conventions_nommage.templates — prioritaire (contient 'fichiers')
    sources = [cnv.get("templates", [])]
    # 2) tous les tableaux nommage_*
    for _key in sorted(cnv.keys()):
        if _key.startswith("nommage_") and isinstance(cnv.get(_key), list):
            sources.append(cnv[_key])

    for _liste in sources:
        for tpl in _liste:
            if not isinstance(tpl, dict):
                continue
            if tpl.get("id") == tpl_id:
                _val = tpl.get("template", "") or ""
                if _val.strip():
                    return _val
    return default


def _construire_maps(cfg):
    """
    Prepare tout ce qui est necessaire pour assembler la regex de convention.

    Retourne (template, groups_map, sous_tpl_regex, libelles) ou None si
    aucun template 'fichiers' n'est configure.

    Extrait de build_regex() pour etre partage avec diagnostiquer_nom_fichier() :
    les deux doivent imperativement resoudre les identifiants de la meme facon.
    """
    nm = cfg.get("nm_convention_noms_fichiers", {}) if isinstance(cfg, dict) else {}

    template = get_convention_template(cfg, "fichiers", "")
    if not template:
        return None

    val_nul_global = nm.get("valeur_si_nul", "X")

    libelles = {}

    # Map id -> {regex, optionnel} pour les groupes atomiques
    groups_map = {}
    for g in nm.get("groupes", []):
        gid = g.get("id", "")
        if gid:
            groups_map[gid] = {
                "regex":     g.get("regex", ""),
                "optionnel": bool(g.get("optionnel", False)),
            }
            libelles[gid] = g.get("label", "") or gid

    # Map id -> regex composite pour les sous-templates (tpl-*)
    # Tous les templates de conventions_nommage.templates sauf tpl-fichiers,
    # resolus dans l'ordre topologique pour supporter les references croisees.
    cnv = cfg.get("conventions_nommage", {}) if isinstance(cfg, dict) else {}
    # Collecter tous les sous-templates : tableau templates (hors tpl-fichiers)
    # + tous les tableaux nommage_* (nommage_niveaux_code, nommage_niveaux, etc.)
    _all_sous = [t for t in cnv.get("templates", []) if t.get("id") != "fichiers"]
    for _key, _val in cnv.items():
        if _key.startswith("nommage_") and isinstance(_val, list):
            _all_sous.extend(_val)
    # Dedoublonnage par id (templates en premier = prioritaire)
    _seen = set()
    candidates = []
    for t in _all_sous:
        tid = t.get("id", "")
        if tid and tid not in _seen:
            _seen.add(tid)
            candidates.append(t)
    try:
        ordered = _topo_sort(candidates)
    except ValueError:
        ordered = candidates  # fallback ordre brut si cycle detecte
    sous_tpl_regex = {}
    for st in ordered:
        stid = st.get("id", "")
        if stid:
            sous_tpl_regex[stid] = {
                "regex":     _build_sous_template_regex(st, groups_map, sous_tpl_regex, val_nul_global),
                "optionnel": bool(st.get("optionnel", False)),
            }
            libelles.setdefault(stid, st.get("label", "") or stid)

    return template, groups_map, sous_tpl_regex, libelles


def build_regex(cfg):
    """
    Construit la regex complete depuis le template 'fichiers'
    (conventions_nommage.templates).

    Supporte :
    - groupes atomiques : id sans prefixe (regex directe)
    - sous-templates    : regex composite depuis sous_templates

    Les groupes nommes Python utilisent _safe_name(id) pour remplacer '-' par '_'.

    Retourne la regex compilable, ou "" si la config est incomplete.
    """
    _maps = _construire_maps(cfg)
    if _maps is None:
        return ""
    template, groups_map, sous_tpl_regex, _libelles = _maps

    # Tokenisation du template maitre
    tokens = re.split(r'(\{[^}]+\})', template)

    result      = "^"
    pending_sep = None

    for token in tokens:
        if not token:
            continue
        if token.startswith("{") and token.endswith("}"):
            gid = token[1:-1]

            # Sous-template ou groupe atomique ?
            if gid in sous_tpl_regex:
                g_info = sous_tpl_regex[gid]
            elif gid in groups_map:
                g_info = groups_map[gid]
            else:
                # Groupe inconnu : capture litterale du nom
                g_info = {"regex": re.escape(gid), "optionnel": False}

            pat      = g_info.get("regex", "")
            optional = g_info.get("optionnel", False)
            named    = "(?P<" + _safe_name(gid) + ">" + pat + ")"

            if optional:
                sep_esc = re.escape(pending_sep) if pending_sep else ""
                result += "(?:" + sep_esc + named + ")?"
                pending_sep = None
            else:
                if pending_sep is not None:
                    result += re.escape(pending_sep)
                    pending_sep = None
                result += named
        else:
            if pending_sep is not None:
                result += re.escape(pending_sep)
            pending_sep = token

    result += "$"
    return result


def diagnostiquer_nom_fichier(name, cfg):
    """
    Explique POURQUOI un nom de fichier ne respecte pas la convention.

    Assemble la regex element par element et s'arrete au premier qui ne
    correspond plus : on sait alors quelle partie du nom est fautive, au lieu
    de se contenter d'un "non conforme" global.

    Retourne (ok, lignes) :
      ok     : True si le nom est conforme (lignes vide)
      lignes : liste de chaines prete a afficher, decrivant element par element
               ce qui a ete lu et ou la lecture echoue.
    """
    _maps = _construire_maps(cfg)
    if _maps is None:
        return False, [u"Aucune convention de nommage de fichiers n'est configurée."]
    template, groups_map, sous_tpl_regex, libelles = _maps

    base = os.path.splitext(name)[0]

    complet = build_regex(cfg)
    if complet and re.match(complet, base):
        return True, []

    tokens = re.split(r'(\{[^}]+\})', template)

    # Largeur de colonne calculee sur les libelles reellement utilises, pour
    # que les lignes restent alignees quel que soit le nommage configure.
    _larg = 12
    for _tk in tokens:
        if _tk and _tk.startswith("{") and _tk.endswith("}"):
            _larg = max(_larg, len(libelles.get(_tk[1:-1], _tk[1:-1])))

    partiel     = "^"
    pending_sep = None
    position    = 0
    lignes      = []
    fautif      = None

    for token in tokens:
        if not token:
            continue
        if not (token.startswith("{") and token.endswith("}")):
            if pending_sep is not None:
                partiel += re.escape(pending_sep)
            pending_sep = token
            continue

        gid = token[1:-1]
        if gid in sous_tpl_regex:
            g_info = sous_tpl_regex[gid]
        elif gid in groups_map:
            g_info = groups_map[gid]
        else:
            g_info = {"regex": re.escape(gid), "optionnel": False}

        pat      = g_info.get("regex", "")
        optional = g_info.get("optionnel", False)
        named    = "(?P<" + _safe_name(gid) + ">" + pat + ")"

        if optional:
            sep_esc = re.escape(pending_sep) if pending_sep else ""
            partiel += "(?:" + sep_esc + named + ")?"
            pending_sep = None
        else:
            if pending_sep is not None:
                partiel += re.escape(pending_sep)
                pending_sep = None
            partiel += named

        position += 1
        libelle = libelles.get(gid, gid)

        if fautif is not None:
            lignes.append(u"  {}. {:<{w}}  non vérifié".format(
                position, libelle, w=_larg))
            continue

        m = re.match(partiel, base)
        if m:
            valeur = m.groupdict().get(_safe_name(gid)) or u""
            if optional and not valeur:
                lignes.append(u"  {}. {:<{w}}  absent (facultatif)".format(
                    position, libelle, w=_larg))
            else:
                lignes.append(u"  {}. {:<{w}}  OK       « {} »".format(
                    position, libelle, valeur, w=_larg))
        else:
            fautif = libelle
            lignes.append(u"  {}. {:<{w}}  ERREUR   attendu : {}".format(
                position, libelle, pat or u"(motif vide)", w=_larg))

    if fautif is None:
        # Tous les elements passent mais le nom entier est refuse : il reste
        # des caracteres apres le dernier element attendu.
        lignes.append(u"")
        lignes.append(u"Tous les éléments sont reconnus, mais le nom comporte "
                      u"des caractères en trop à la fin.")
    else:
        lignes.insert(0, u"La lecture échoue sur l'élément « {} ».".format(fautif))
        lignes.insert(1, u"")

    return False, lignes


def delimiter_from_template(cfg):
    """
    Extrait le separateur entre les deux premiers {id} du template 'fichiers'.
    Retourne "_" par defaut.
    """
    template = get_convention_template(cfg, "fichiers", "")
    if not template:
        return "_"
    m = re.search(r'\{[^}]+\}([^{]+)\{[^}]+\}', template)
    return m.group(1) if (m and m.group(1)) else "_"


def delimiter_from_regex(pattern):
    """
    Extrait le separateur litteral entre le premier et le deuxieme groupe
    nomme de la regex de convention.
    Retourne "_" par defaut.
    """
    m = re.search(r'\)([^(]+)\(\?P<', pattern)
    sep = m.group(1) if (m and m.group(1)) else "_"
    sep = re.sub(r'\\(.)', r'\1', sep)
    return sep


def extract_file_name_info(name, cfg):
    """
    Extrait site, building, level, half, producteur, specialite depuis 'name'
    via la regex de convention.

    Retourne un dict ou None si pas de correspondance.
    """
    pat = build_regex(cfg)
    name_bare = os.path.splitext(name)[0]
    if not pat:
        return None
    m = re.match(pat, name_bare)
    if not m:
        return None
    gd = m.groupdict()
    # Le nom du groupe vient de l'identifiant du sous-template "Niveau (code)"
    # via _safe_name() : 'niveau-code' -> 'niveau_code'. L'ancien identifiant
    # 'niveau' est encore accepte pour les config.json anterieurs au renommage.
    _level = gd.get("niveau_code") or gd.get("niveau") or ""
    return {
        "site":       gd.get("site",        "") or "",
        "building":   gd.get("construction","") or "",
        "level":      _level,
        "half":       gd.get("demi_niv",    "") or "",
        "producteur": gd.get("producteur",  "") or "",
        "specialite": gd.get("specialite",  "") or "",
    }


# ---------------------------------------------------------------------------
# Casse des variables de template (generation de noms uniquement)
# ---------------------------------------------------------------------------
# La casse ECRITE du jeton pilote la casse de la valeur produite :
#     {construction}   -> tout en minuscules
#     {CONSTRUCTION}   -> TOUT EN MAJUSCULES
#     {Construction}   -> 1re lettre en majuscule, le reste en minuscules
#
# Deux suffixes couvrent ce que la casse du jeton ne peut pas exprimer :
#     {construction:val}  -> valeur brute, inchangee
#     {construction:cap}  -> Chaque Mot De La Valeur Capitalise
#
# N'affecte QUE resolve_template() (generation de noms). build_regex(), qui
# analyse des noms de fichiers existants, continue de comparer les identifiants
# a l'identique et ignore totalement ce mecanisme.
#
# NB : bloc volontairement duplique a l'identique dans utils/vues_creation.py
# (voir le commentaire equivalent la-bas).

# Valeurs jamais transformees, quelle que soit la casse ecrite (equivaut a un
# ':val' implicite) :
#   niveau      nom du niveau Revit, sert aussi de cle de correspondance
#   niveau-code code de niveau extrait du nom de fichier (ex. "R+02") : le
#               forcer en minuscules produirait "r+02" et casserait les codes
_CASSE_EXEMPT = frozenset([u'niveau', u'niveau-code'])

_TOKEN_RE = re.compile(u'\\{([^{}]*)\\}')

# Separateurs de mots pour ':cap'. L'apostrophe en est volontairement absente
# pour ne pas produire "L'Etage" a partir de "l'etage".
_SEPARATEURS_MOTS = u" \t\r\n-_/."


def _capitaliser(valeur):
    """1re lettre en majuscule, reste en minuscules (sans decouper les mots)."""
    if not valeur:
        return valeur
    return valeur[0].upper() + valeur[1:].lower()


def _capitaliser_mots(valeur):
    """Capitalise chaque mot : 'plan de sol' -> 'Plan De Sol'."""
    if not valeur:
        return valeur
    _res = []
    _nouveau_mot = True
    for _c in valeur.lower():
        if _nouveau_mot and _c not in _SEPARATEURS_MOTS:
            _res.append(_c.upper())
            _nouveau_mot = False
        else:
            _res.append(_c)
            if _c in _SEPARATEURS_MOTS:
                _nouveau_mot = True
    return u''.join(_res)


def _appliquer_casse(jeton, var_id, valeur, suffixe):
    """Applique la casse demandee a 'valeur' (voir en-tete de section)."""
    if valeur is None:
        valeur = u''
    if var_id in _CASSE_EXEMPT:
        return valeur

    _sfx = (suffixe or u'').strip().lower()
    if _sfx:
        if _sfx == u'val':
            return valeur
        if _sfx == u'cap':
            return _capitaliser_mots(valeur)
        return valeur           # suffixe inconnu -> valeur brute (securite)

    if jeton == var_id:                 # tout en minuscules
        return valeur.lower()
    if jeton == var_id.upper():         # TOUT EN MAJUSCULES
        return valeur.upper()
    if jeton == _capitaliser(var_id):   # 1re lettre seulement
        return _capitaliser(valeur)
    return valeur               # casse mixte non reconnue -> valeur brute


def _substituer(texte, mapping):
    """
    Remplace les jetons {variable} presents dans 'mapping' en appliquant la
    casse demandee. Correspondance insensible a la casse ; un jeton absent du
    mapping est laisse tel quel (indispensable au fonctionnement en deux
    passes de resolve_template).
    """
    if not texte:
        return texte
    _low = {}
    for _k, _v in mapping.items():
        _low[_k.lower()] = _v

    def _remplacer(_m):
        _brut = _m.group(1)
        if u':' in _brut:
            _jeton, _, _sfx = _brut.partition(u':')
        else:
            _jeton, _sfx = _brut, u''
        _var_id = _jeton.lower()
        if _var_id not in _low:
            return _m.group(0)
        return _appliquer_casse(_jeton, _var_id, _low[_var_id], _sfx)

    return _TOKEN_RE.sub(_remplacer, texte)


def resolve_template(template, values, sous_tpl_map=None):
    """
    Resout un template en deux passes :
    1. Remplace les jetons des sous-templates par leur valeur (sous_tpl_map)
    2. Remplace les jetons des groupes atomiques par leur valeur (values)

    sous_tpl_map : dict {id_sous_tpl: valeur_calculee}
    values       : dict {id_groupe: valeur}

    La casse ecrite du jeton pilote la casse produite ({CONSTRUCTION},
    {Construction}, {construction}) ; voir l'en-tete de section ci-dessus.

    Retourne la chaine resolue.
    """
    if sous_tpl_map is None:
        sous_tpl_map = {}
    # Passe 1 : sous-templates. Les jetons inconnus sont conserves pour que la
    # passe 2 puisse les resoudre (et une valeur de sous-template contenant
    # elle-meme un jeton reste resolvable, comme avant).
    result = _substituer(template, sous_tpl_map)
    # Passe 2 : groupes atomiques
    result = _substituer(result, values)
    return result
