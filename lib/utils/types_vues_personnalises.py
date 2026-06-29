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

"""
Utilitaire partagé — Types de vue personnalisés (NM-BATII).

Expose la table `types_vues_personnalises` depuis config.json.
Chaque entrée de la table décrit une configuration de vue personnalisée :

  {
    "label":    str  – Identifiant unique (ex : "FM", "Temporaire")
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

Utilisation :

    from utils.types_vues_personnalises import (
        get_types_vues, get_row_by_label,
        get_type_for_vue_id, get_default_livrable,
        get_template_vars,
    )
"""

# Valeurs par défaut si la clé est absente de config.json
DEFAULT_TYPES_VUES = [
    {
        u'label':    u'Temporaire',
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
        u'label': u'Temporaire',
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


def get_default_livrable(cfg):
    """
    Retourne le premier type avec usage='Livrable',
    ou le premier type disponible, ou None.
    """
    rows = get_types_vues(cfg)
    for t in rows:
        if t.get(u'usage', u'') == u'Livrable':
            return t
    return rows[0] if rows else None
