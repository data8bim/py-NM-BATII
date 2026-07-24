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
Utilitaire partage — Types de nomenclatures (NM-BATII).

Expose la table `nomenclatures_types` de config.json, editee depuis
01_Parametres > onglet "Nomenclatures" > "Types de nomenclatures".

Chaque entree decrit un type de nomenclature a produire :

  {
    "label":     str – Libelle du type. Sert a la fois de case a cocher dans
                       06_Donnees > "Creer NOMENCLATURES" et de valeur de la
                       variable {type-nomenclature} du template de nommage.
    "type_vue":  str – Nom exact du ViewFamilyType Revit (famille Schedule)
                       a appliquer aux nomenclatures produites. Cree par
                       duplication s'il n'existe pas. Vide = type par defaut.
  }

Cette table remplace, pour les nomenclatures uniquement, le systeme
`types_vues_personnalises` / `types_vues` / `gabarits_vues` : l'axe de
declinaison d'une nomenclature est (categorie x phase x type de nomenclature)
et non (niveau x type de vue personnalise).

Utilisation :

    from utils.nomenclatures_types import (
        get_types_nomenclatures, get_row_by_label, get_or_create_schedule_vft,
    )
"""

# Valeurs par defaut si la cle est absente de config.json.
# Les noms de `type_vue` correspondent aux ViewFamilyType de famille Schedule
# presents dans les maquettes NM-BATII de reference.
DEFAULT_TYPES_NOMENCLATURES = [
    {u'label': u"2a - Saisie des caract\xe9ristiques du TYPE",
     u'type_vue': u'2 - SAISIES DES DONNEES'},
    {u'label': u"2b - Saisie des caract\xe9ristiques d'OCCURRENCES",
     u'type_vue': u'2 - SAISIES DES DONNEES'},
    {u'label': u"3a - Pr\xe9sentation des caract\xe9ristiques du TYPE",
     u'type_vue': u'3 - PRESENTATIONS DES DONNEES'},
    {u'label': u"3b - Pr\xe9sentation des caract\xe9ristiques d'OCCURRENCES",
     u'type_vue': u'3 - PRESENTATIONS DES DONNEES'},
    {u'label': u"3c - Pr\xe9sentation des caract\xe9ristiques AUTRES",
     u'type_vue': u'3 - PRESENTATIONS DES DONNEES'},
]


def get_types_nomenclatures(cfg):
    """
    Retourne la liste des types de nomenclatures depuis config.json.
    Repli sur DEFAULT_TYPES_NOMENCLATURES si la cle est absente ou vide
    (config.json anterieur a l'ajout de la table).
    """
    rows = (cfg or {}).get(u'nomenclatures_types')
    if not rows:
        return [dict(r) for r in DEFAULT_TYPES_NOMENCLATURES]
    normalised = []
    for r in rows:
        row = dict(r)
        row.setdefault(u'label', u'')
        row.setdefault(u'type_vue', u'')
        if row[u'label']:
            normalised.append(row)
    return normalised or [dict(r) for r in DEFAULT_TYPES_NOMENCLATURES]


def get_labels(cfg):
    """Libelles seuls, pour alimenter une liste a cocher."""
    return [t.get(u'label', u'') for t in get_types_nomenclatures(cfg)]


def get_row_by_label(cfg, label):
    """Ligne correspondant au label donne, ou None. Insensible a la casse."""
    label_low = (label or u'').lower()
    for t in get_types_nomenclatures(cfg):
        if t.get(u'label', u'').lower() == label_low:
            return t
    return None


def get_type_vue(cfg, label):
    """Nom du ViewFamilyType associe au label, ou '' si aucun."""
    row = get_row_by_label(cfg, label)
    return (row or {}).get(u'type_vue', u'') or u''


# ---------------------------------------------------------------------------
# Revit — resolution du ViewFamilyType de nomenclature
# ---------------------------------------------------------------------------
# Import isole : ce module doit rester importable hors contexte Revit (le
# dialogue 01_Parametres n'a besoin que des helpers de configuration ci-dessus).
try:
    from Autodesk.Revit.DB import (
        BuiltInParameter, FilteredElementCollector, ViewFamily, ViewFamilyType,
    )
    _REVIT_DISPO = True
except Exception:
    _REVIT_DISPO = False


def _nom_vft(vft):
    """
    Nom d'un ViewFamilyType.

    `Element.Name` est implemente en interface explicite et leve
    AttributeError sur les ElementType en IronPython : on passe par
    SYMBOL_NAME_PARAM (meme contournement que lib/utils/vues_creation.py).
    """
    try:
        return vft.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString()
    except Exception:
        try:
            return vft.Name
        except Exception:
            return u''


def get_or_create_schedule_vft(doc, nom_type):
    """
    Retourne l'ElementId du ViewFamilyType de famille Schedule nomme
    `nom_type`, en le creant par duplication du premier type existant s'il est
    absent.

    Retourne None si `nom_type` est vide (la nomenclature garde alors le type
    par defaut affecte par ViewSchedule.CreateSchedule) ou si la famille
    Schedule n'expose aucun type dans ce document.

    Doit etre appele dans une Transaction ouverte : la duplication modifie le
    document.
    """
    if not _REVIT_DISPO:
        return None
    nom_type = (nom_type or u'').strip()
    if not nom_type:
        return None

    fam_schedule = getattr(ViewFamily, u'Schedule', None)
    if fam_schedule is None:
        return None

    vfts = [vf for vf in FilteredElementCollector(doc).OfClass(ViewFamilyType)
            if vf.ViewFamily == fam_schedule]
    if not vfts:
        return None

    for vf in vfts:
        if _nom_vft(vf) == nom_type:
            return vf.Id

    try:
        dup = vfts[0].Duplicate(nom_type)
        # Selon la version de l'API, Duplicate() renvoie l'element ou son Id.
        return dup.Id if isinstance(dup, ViewFamilyType) else dup
    except Exception:
        return None


def appliquer_type_vue(doc, sched, vft_id):
    """
    Affecte `vft_id` a la nomenclature `sched`.

    ViewSchedule.CreateSchedule() n'accepte pas de ViewFamilyType : le type ne
    peut etre pose qu'apres coup. Retourne True si le type est effectivement
    change — Revit peut accepter l'appel sans effet, on revalide donc via
    GetTypeId() plutot que de se fier a l'absence d'exception.
    """
    if vft_id is None:
        return False
    try:
        if not sched.IsValidType(vft_id):
            return False
    except Exception:
        pass
    try:
        sched.ChangeTypeId(vft_id)
        return sched.GetTypeId() == vft_id
    except Exception:
        return False
