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

"""
Utilitaire partagé — Types de vue personnalisés (NM-BATII).

Expose la table `types_vues_personnalises` depuis config.json.
Chaque entrée de la table décrit une configuration de vue personnalisée :

  {
    "label":    str  – Identifiant unique, en MAJUSCULES (ex : "FM",
                       "TEMPORAIRE"). Normalisé par la fenêtre des
                       paramètres, qui l'applique aussi aux six tables
                       indexées dessus.
    "titre":    str  – Valeur principale pour les templates {vue-pers-titre}
    "valeur_1": str  – Valeur libre pour les templates {vue-pers-valeur-1}
    "valeur_2": str  – Valeur libre pour les templates {vue-pers-valeur-2}
    "usage":    str  – "Temporaire" ou "Livrable" → {vue-pers-usage}
    "systeme":  bool – True = ligne système non supprimable
  }

Variables disponibles dans les templates de nommage :
    {vue-pers-label}    → valeur de la colonne "Label"
    {vue-pers-titre}    → valeur de la colonne "Titre"
    {vue-pers-valeur-1} → valeur de la colonne "Valeur-1"
    {vue-pers-valeur-2} → valeur de la colonne "Valeur-2"
    {vue-pers-usage}    → valeur de la colonne "Usage"


Les types Revit (ViewFamilyType) sont dans la table séparée `types_vues` :
    cfg['types_vues'] = [{"label": "FM", "types": {"vue-plan": "Plan d'étage", ...}}]
    get_type_for_vue_id(cfg, tvp_label, vue_id) → str nom du VFT Revit

Cas particulier `vue-surface` : un plan de surface Revit n'a pas de
ViewFamilyType librement nommable — son « type » EST son schéma de surface
(Revit : Calculs des surfaces et des volumes > Schémas de surface). La valeur
saisie dans `types_vues[label]['vue-surface']` est donc un NOM DE SCHEMA DE
SURFACE devant exister dans le projet ; il n'est jamais créé automatiquement
(voir _get_area_scheme_id dans utils/vues_creation.py).

La disponibilité d'un type personnalisé par famille de vue est dans la table
`dispo_types_pers_familles` :
    cfg['dispo_types_pers_familles'] = [
        {"label": "FM", "familles": {"vue-plan": True, "vue-surface": False, ...}}
    ]
    is_type_dispo_pour_famille(cfg, tvp_label, vue_id) → bool

Cette table est complémentaire de `dispo_types_pers_lier_cao`, qui porte la
disponibilité par SCRIPT (Lier CAO / Vues + / Pièces 3D). Un type est proposé
dans un script pour une famille donnée si les deux tables l'autorisent.
Toute combinaison absente vaut True : une config antérieure à cette table
conserve donc exactement le comportement d'avant.

La disponibilité par DISCIPLINE suit le même principe, table
`dispo_types_pers_disciplines` :
    cfg['dispo_types_pers_disciplines'] = [
        {"label": "FM", "disciplines": {"510000": True, "520000": False}}
    ]
    filtrer_labels_pour_discipline(cfg, labels, discipline_code) → list
La clé est le `code_ouvrage` d'une ligne de lib/utils/disciplines.py — jamais
son libellé affiché, qui peut changer. Axe indépendant et cumulatif avec la
famille de vue : un type doit passer les deux filtres pour être proposé.

Scripts concernés : ceux qui proposent un MENU de types personnalisés, c.-à-d.
« Vues + » et « Lier CAO ». « Pièces 3D » n'en fait pas partie : il ne propose
pas de menu, son type est désigné par la case exclusive `pieces_3d` de
`dispo_types_pers_lier_cao` — il n'y a donc rien à y filtrer.

Utilisation :

    from utils.types_vues_personnalises import (
        get_types_vues, get_row_by_label,
        get_type_for_vue_id, get_default_livrable,
        get_template_vars,
        get_dispo_familles, is_type_dispo_pour_famille,
        filtrer_labels_pour_famille,
        get_dispo_disciplines, is_type_dispo_pour_discipline,
        filtrer_labels_pour_discipline,
    )
"""

# Valeurs par défaut si la clé est absente de config.json.
# Lignes SYSTEME, dans l'ordre d'affichage (colonne « Ord. » = index) :
# PIECES 3D=0, TEMPORAIRE=1, FM=2. Elles ne sont ni supprimables ni
# renommables dans 01_Parametres (voir _TVP_LOCKED_ORDER dans son script.py).
DEFAULT_TYPES_VUES = [
    # Ligne réservée à 05_Pieces > Pièces 3D : elle est la SEULE à pouvoir
    # porter la case « Pièces 3D » de la colonne « Disponibilité ». L'outil
    # s'appuie dessus pour nommer et typer la vue 3D qu'il crée.
    {
        u'label':    u'PIECES 3D',
        u'titre':    u'PIECES 3D',
        u'valeur_1': u'',
        u'valeur_2': u'',
        u'usage':    u'Livrable',
        u'systeme':  True,
    },
    {
        u'label':    u'TEMPORAIRE',
        u'titre':    u'TEMP',
        u'valeur_1': u'',
        u'valeur_2': u'',
        u'usage':    u'Temporaire',
        u'systeme':  True,
    },
    {
        u'label':    u'FM',
        u'titre':    u'FM',
        u'valeur_1': u'',
        u'valeur_2': u'',
        u'usage':    u'Livrable',
        u'systeme':  True,
    },
]

# Types Revit par défaut (utilisés si types_vues absent de config.json)
_DEFAULT_TYPES_VFT = [
    {
        u'label': u'TEMPORAIRE',
        u'types': {
            u'vue-plan':      u'TRAITEMENTS DONNEES EXISTANTES',
            u'vue-plaf':      u'TRAITEMENTS DONNEES EXISTANTES',
            u'vue-3d':        u'TRAITEMENTS DONNEES EXISTANTES',
            u'vue-coupe':     u'TRAITEMENTS DONNEES EXISTANTES',
            u'vue-elevation': u'TRAITEMENTS DONNEES EXISTANTES',
        },
    },
    {
        u'label': u'FM',
        u'types': {
            u'vue-plan':      u"Plan d'\xe9tage",
            u'vue-plaf':      u'Plan de faux plafond',
            u'vue-3d':        u"Plan d'\xe9tage",
            u'vue-coupe':     u"Plan d'\xe9tage",
            u'vue-elevation': u"Plan d'\xe9tage",
        },
    },
]


def get_types_vues(cfg):
    """
    Retourne la liste des types de vue personnalisés depuis config.json.
    Normalise les anciennes entrées (champ 'nom' → 'titre').
    Fallback sur l'ancien paramètre `vue_type_personnalise` (string),
    puis sur DEFAULT_TYPES_VUES si rien n'est défini.
    """
    rows = cfg.get(u'types_vues_personnalises')
    if rows:
        # Normalisation rétrocompat : 'nom' → 'titre'
        normalised = []
        for r in rows:
            row = dict(r)
            if u'titre' not in row and u'nom' in row:
                row[u'titre'] = row.pop(u'nom')
            row.setdefault(u'titre',    u'')
            row.setdefault(u'valeur_1', u'')
            row.setdefault(u'valeur_2', u'')
            normalised.append(row)
        return normalised
    # Rétrocompatibilité avec l'ancien paramètre simple
    old = cfg.get(u'vue_type_personnalise', u'').strip()
    if old:
        return [{
            u'label':    old,
            u'titre':    old,
            u'valeur_1': u'',
            u'valeur_2': u'',
            u'usage':    u'Livrable',
            u'systeme':  True,
        }]
    return [dict(r) for r in DEFAULT_TYPES_VUES]


def get_type_labels(cfg):
    """Retourne la liste des labels (pour remplir un menu déroulant)."""
    return [t.get(u'label', u'') for t in get_types_vues(cfg)]


def cle_ordre(val):
    """
    Clé de tri NATURELLE pour le champ `ordre`, qui est du TEXTE libre.

    La colonne « Ord. » de 01_Parametres accepte « A1 », « 10bis » ou
    « B-02 » : un tri purement alphabétique rangerait « 10 » avant « 2 ».
    Chaque suite de chiffres est donc complétée à gauche par des zéros, ce
    qui rend l'ordre numérique aux nombres sans rien interdire au reste.

    Partagée par les trois scripts qui trient cette table (les paramètres,
    « Vues + », « Lier CAO ») : trois règles de tri divergentes donneraient
    trois ordres d'affichage différents pour la même configuration.
    """
    import re as _re
    _txt = u'' if val is None else unicode(val).strip()
    _out = []
    for _bloc in _re.findall(ur'\d+|\D+', _txt):
        _out.append(_bloc.zfill(12) if _bloc.isdigit() else _bloc.lower())
    return u''.join(_out)


def get_template_vars(tvp_row):
    """
    Retourne un dict de toutes les variables {vue-pers-*} utilisables dans les
    templates de nommage, depuis une ligne de types_vues_personnalises.

    """
    row = tvp_row or {}
    return {
        u'vue-pers-label':    row.get(u'label',    u''),
        u'vue-pers-titre':    row.get(u'titre',    u''),
        u'vue-pers-valeur-1': row.get(u'valeur_1', u''),
        u'vue-pers-valeur-2': row.get(u'valeur_2', u''),
        u'vue-pers-usage':    row.get(u'usage',    u''),
    }


def get_row_by_label(cfg, label):
    """
    Retourne le dict correspondant au label donné, ou None.
    Recherche insensible à la casse.
    """
    label_low = (label or u'').lower()
    for t in get_types_vues(cfg):
        if t.get(u'label', u'').lower() == label_low:
            return t
    return None


def get_type_for_vue_id(cfg, tvp_label, vue_id):
    """
    Retourne le nom du ViewFamilyType Revit à utiliser pour la combinaison
    (label du type perso, id de nommage de vue).

    Exemple :
        get_type_for_vue_id(cfg, "FM", "vue-plan") → "Plan d'étage"

    La recherche se fait par label (pas par nom de VFT) afin que plusieurs
    labels puissent partager le même type Revit sans confusion.

    Retourne '' si aucune correspondance.
    """
    tvp_label_low = (tvp_label or u'').lower()
    # Chercher dans cfg['types_vues']
    for entry in cfg.get(u'types_vues', []):
        if entry.get(u'label', u'').lower() == tvp_label_low:
            return entry.get(u'types', {}).get(vue_id, u'')
    # Fallback sur les défauts internes
    for entry in _DEFAULT_TYPES_VFT:
        if entry.get(u'label', u'').lower() == tvp_label_low:
            return entry.get(u'types', {}).get(vue_id, u'')
    # Rétrocompatibilité : ancien champ 'type' sur la ligne tvp elle-même
    row = get_row_by_label(cfg, tvp_label)
    if row:
        return row.get(u'type', u'')
    return u''


# ---------------------------------------------------------------------------
# Disponibilite d'un type personnalise par famille de vue
# ---------------------------------------------------------------------------
# Table config.json : `dispo_types_pers_familles`
#   [{"label": "FM", "familles": {"vue-plan": True, "vue-surface": False}}]
#
# Regle d'or : TOUT CE QUI N'EST PAS RENSEIGNE VAUT True. La table est donc
# purement restrictive — une config.json ecrite avant son introduction (cle
# absente) se comporte a l'identique, et un nouvel id de famille ajoute dans
# "Nommage des vues" est disponible partout tant qu'il n'a pas ete decoche.

def get_dispo_familles(cfg):
    """
    Retourne {label: {vue_id: bool}} depuis cfg['dispo_types_pers_familles'].
    Retourne {} si la table est absente (= tout disponible).
    """
    _res = {}
    for _entry in cfg.get(u'dispo_types_pers_familles', []) or []:
        _lbl = _entry.get(u'label', u'')
        if not _lbl:
            continue
        _fams = {}
        for _vid, _val in (_entry.get(u'familles', {}) or {}).items():
            _fams[_vid] = bool(_val)
        _res[_lbl] = _fams
    return _res


def is_type_dispo_pour_famille(cfg, tvp_label, vue_id, _dispo=None):
    """
    True si le type personnalise `tvp_label` est propose pour la famille de vue
    `vue_id` (ex. 'vue-plan', 'vue-surface').

    _dispo : dict deja obtenu via get_dispo_familles(), pour eviter de relire la
             table a chaque appel dans une boucle. Optionnel.

    Un label inconnu, un vue_id inconnu ou une table absente valent True.
    """
    if not vue_id:
        return True
    _d = get_dispo_familles(cfg) if _dispo is None else _dispo
    return bool(_d.get(tvp_label, {}).get(vue_id, True))


def filtrer_labels_pour_famille(cfg, labels, vue_id):
    """
    Filtre une liste de labels de types personnalises en ne conservant que ceux
    disponibles pour la famille de vue `vue_id`. L'ordre d'entree est conserve.

    Destine au remplissage des menus deroulants « Type personnalise » des
    scripts, apres le filtrage par script (dispo_types_pers_lier_cao).
    """
    _d = get_dispo_familles(cfg)
    return [_l for _l in labels
            if is_type_dispo_pour_famille(cfg, _l, vue_id, _dispo=_d)]


# ---------------------------------------------------------------------------
# Disponibilite d'un type personnalise par Discipline
# ---------------------------------------------------------------------------
# Table config.json : `dispo_types_pers_disciplines`
#   [{"label": "FM", "disciplines": {"510000": True, "520000": False}}]
#
# Meme regle d'or que dispo_types_pers_familles : TOUT CE QUI N'EST PAS
# RENSEIGNE VAUT True. Axe INDEPENDANT et CUMULATIF avec la famille de vue —
# un type doit passer les deux filtres pour etre propose. La cle est le
# code_ouvrage de la ligne du referentiel des disciplines (lib/utils/
# disciplines.py), jamais son libelle affiche.

def get_dispo_disciplines(cfg):
    """
    Retourne {label: {code_ouvrage: bool}} depuis
    cfg['dispo_types_pers_disciplines']. Retourne {} si la table est absente
    (= tout disponible).
    """
    _res = {}
    for _entry in cfg.get(u'dispo_types_pers_disciplines', []) or []:
        _lbl = _entry.get(u'label', u'')
        if not _lbl:
            continue
        _discs = {}
        for _code, _val in (_entry.get(u'disciplines', {}) or {}).items():
            _discs[_code] = bool(_val)
        _res[_lbl] = _discs
    return _res


def is_type_dispo_pour_discipline(cfg, tvp_label, discipline_code, _dispo=None):
    """
    True si le type personnalise `tvp_label` est propose pour la discipline
    `discipline_code` (code_ouvrage d'une ligne du referentiel Disciplines).

    _dispo : dict deja obtenu via get_dispo_disciplines(), pour eviter de
             relire la table a chaque appel dans une boucle. Optionnel.

    Un label inconnu, un discipline_code vide (« Toutes les disciplines »)
    ou une table absente valent True.
    """
    if not discipline_code:
        return True
    _d = get_dispo_disciplines(cfg) if _dispo is None else _dispo
    return bool(_d.get(tvp_label, {}).get(discipline_code, True))


def filtrer_labels_pour_discipline(cfg, labels, discipline_code):
    """
    Filtre une liste de labels de types personnalises en ne conservant que
    ceux disponibles pour la discipline `discipline_code`. L'ordre d'entree
    est conserve. `discipline_code` vide (« Toutes les disciplines ») rend
    la liste inchangee.

    Destine au remplissage des menus deroulants « Type personnalise » des
    scripts, apres le filtrage par famille de vue
    (filtrer_labels_pour_famille) : les deux se cumulent.
    """
    if not discipline_code:
        return list(labels)
    _d = get_dispo_disciplines(cfg)
    return [_l for _l in labels
            if is_type_dispo_pour_discipline(cfg, _l, discipline_code, _dispo=_d)]


def get_disciplines_utilisees(cfg, labels=None):
    """
    Codes de discipline EXPLICITEMENT coches pour au moins un type personnalise.

    labels : restreint aux types donnes (ex. ceux disponibles dans « Vues + »).
             None = tous les types.

    Sert a n'offrir dans les menus que les disciplines REELLEMENT employees par
    les vues personnalisees, et non les ~100 lignes du referentiel de l'onglet
    « Disciplines » : la quasi-totalite n'y menerait a aucun type.

    Attention a la difference avec is_type_dispo_pour_discipline, ou une
    combinaison ABSENTE vaut disponible (table permissive). Ici on veut
    l'inverse : seules les cases cochees comptent, sans quoi « utilisees »
    engloberait tout le referentiel et la restriction n'aurait aucun effet.
    La table etant ecrite exhaustivement par 01_Parametres, la nuance ne se
    voit que sur un config.json ancien ou edite a la main.
    """
    _autorises = None if labels is None else set(labels)
    _codes = set()
    for _entry in cfg.get(u'dispo_types_pers_disciplines', []) or []:
        _lbl = _entry.get(u'label', u'')
        if _autorises is not None and _lbl not in _autorises:
            continue
        for _code, _val in (_entry.get(u'disciplines', {}) or {}).items():
            if _val and _code:
                _codes.add(_code)
    return _codes


def filtrer_labels_pour_disciplines(cfg, labels, codes):
    """
    Filtre des labels en ne gardant que ceux disponibles pour AU MOINS UN des
    codes de discipline donnes. L'ordre d'entree est conserve.

    `codes` vide ou None = aucun filtrage (« Toutes les disciplines »).

    La semantique « au moins un » est celle qu'attend une selection large :
    choisir une discipline sans preciser la sous-discipline doit rendre les
    types de TOUTE la branche, pas seulement ceux coches sur la ligne de tete.
    """
    if not codes:
        return list(labels)
    _d = get_dispo_disciplines(cfg)
    _codes = list(codes)
    return [_l for _l in labels
            if any(is_type_dispo_pour_discipline(cfg, _l, _c, _dispo=_d)
                   for _c in _codes)]


def get_default_livrable(cfg):
    """
    Retourne le premier type avec usage='Livrable',
    ou le premier type disponible, ou None.

    Les lignes réservées à un outil précis sont écartées : "PIECES 3D" est
    en tête de liste (Ord. 0) et porte usage='Livrable', elle serait donc
    retournée alors qu'elle n'est proposée dans aucun menu. Le repérage se
    fait par la case `pieces_3d` de `dispo_types_pers_lier_cao`, jamais par
    le label — voir [_TVP_LABEL_PIECES_3D dans 01_Parametres].
    """
    _reserves = set(
        _d.get(u'label', u'')
        for _d in (cfg.get(u'dispo_types_pers_lier_cao', []) or [])
        if _d.get(u'pieces_3d', False))
    rows = get_types_vues(cfg)
    _libres = [t for t in rows if t.get(u'label', u'') not in _reserves]
    for t in _libres:
        if t.get(u'usage', u'') == u'Livrable':
            return t
    return _libres[0] if _libres else (rows[0] if rows else None)
