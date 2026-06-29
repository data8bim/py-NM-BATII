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
Utilitaire de creation et nommage des vues Revit selon la convention NM-BATII.

Fonctions publiques :
    resolve_view_name(fam_enum, vars_dict, cfg)
    get_or_create_vft(doc, fam_enum, custom_type_name)
    create_views_from_candidates(doc, candidates, selected_files, levels,
                                  fam_enum, tvp_row, cfg,
                                  do_vue_niveau=False)

Le type Revit (ViewFamilyType) est résolu automatiquement depuis cfg['types_vues']
en combinant le label du tvp_row et l'id de nommage de vue (ex. 'vue-plan').
Plusieurs labels peuvent partager le même type Revit : la résolution se fait
toujours par label, jamais par valeur de type.
"""

from Autodesk.Revit.DB import (
    View,
    ViewPlan,
    ViewDrafting,
    ViewFamily,
    ViewFamilyType,
    ViewDuplicateOption,
    FilteredElementCollector,
    Transaction,
    BuiltInParameter,
)
from utils.types_vues_personnalises import get_type_for_vue_id, get_template_vars

# Mapping ViewFamily → identifiant de template dans conventions_nommage.nommage_vues
# Utilisé uniquement comme fallback quand vue_id n'est pas fourni explicitement.
_FAMILY_TEMPLATE_ID = {
    ViewFamily.FloorPlan:      u'vue-plan',
    ViewFamily.CeilingPlan:    u'vue-plaf',
    ViewFamily.StructuralPlan: u'vue-structure',
    ViewFamily.Section:        u'vue-coupe',
    ViewFamily.Elevation:      u'vue-elevation',
    ViewFamily.Drafting:       None,
}
_vf_legend = getattr(ViewFamily, u'Legend', None)
if _vf_legend is not None:
    _FAMILY_TEMPLATE_ID[_vf_legend] = u'vue-legende'
_vf_threed = getattr(ViewFamily, u'ThreeD', None)
if _vf_threed is not None:
    _FAMILY_TEMPLATE_ID[_vf_threed] = u'vue-3d'


def resolve_view_name(fam_enum, vars_dict, cfg, vue_id=None):
    """
    Resout le nom d'une vue a partir du template de nommage_vues correspondant
    a la famille de vues.

    fam_enum  : ViewFamily (ex. ViewFamily.FloorPlan)
    vars_dict : dict des variables a substituer
                ex. {'niveau': '001_0_0', 'vue-pers-titre': 'FM'}
    cfg       : dict config.json
    vue_id    : identifiant explicite de l'entree nommage_vues (ex. 'vue-surface').
                Si None, derive depuis _FAMILY_TEMPLATE_ID.

    Retourne la chaine resolue, ou une chaine vide si aucun template trouve.
    """
    tpl_id = vue_id if vue_id else _FAMILY_TEMPLATE_ID.get(fam_enum)
    if not tpl_id:
        return vars_dict.get(u'vue-pers-titre', u'')

    nommage_vues = (cfg.get(u'conventions_nommage') or {}).get(u'nommage_vues', [])
    tpl = u''
    for entry in nommage_vues:
        if entry.get(u'id') == tpl_id:
            tpl = entry.get(u'template', u'')
            break

    if not tpl:
        _parts = [p for p in [
            vars_dict.get(u'vue-pers-titre', u''),
            vars_dict.get(u'niveau', u''),
        ] if p and p.strip()]
        return u' - '.join(_parts).strip()

    # Résolution par segments : on découpe sur ' - ', on substitue chaque segment,
    # on filtre les segments vides, on recolle — évite les séparateurs orphelins.
    _SEP = u' - '
    _segments = tpl.split(_SEP)
    _resolved = []
    for _seg in _segments:
        _val = _seg
        for _k, _v in vars_dict.items():
            _val = _val.replace(u'{' + _k + u'}', _v or u'')
        if _val.strip():
            _resolved.append(_val)
    return _SEP.join(_resolved).strip()


def _get_gabarit_name(cfg, tvp_row, fam_enum, vue_id=None):
    """
    Retourne le nom du gabarit de vue Revit a appliquer, ou '' si aucun.

    Recherche par label du tvp_row dans cfg['gabarits_vues'].
    vue_id : identifiant explicite (ex. 'vue-surface'). Prioritaire sur _FAMILY_TEMPLATE_ID.
    """
    tvp_label = (tvp_row or {}).get(u'label', u'')
    if not tvp_label:
        return u''
    tpl_id = vue_id if vue_id else _FAMILY_TEMPLATE_ID.get(fam_enum)
    if not tpl_id:
        return u''
    for entry in cfg.get(u'gabarits_vues', []):
        if entry.get(u'label') == tvp_label:
            return entry.get(u'gabarits', {}).get(tpl_id, u'')
    return u''


def _apply_view_template(doc, view, template_name):
    """
    Applique le gabarit de vue 'template_name' a 'view'.
    Si le gabarit est introuvable, ne fait rien (pas d'exception).
    Doit etre appele a l'interieur d'une Transaction ouverte.
    """
    if not template_name:
        return
    templates = [
        v for v in FilteredElementCollector(doc).OfClass(View)
        if v.IsTemplate and v.Name == template_name
    ]
    if not templates:
        return
    try:
        view.ViewTemplateId = templates[0].Id
    except Exception:
        pass


def _get_vft_name(vft):
    """Retourne le nom du ViewFamilyType via SYMBOL_NAME_PARAM (compatible CPython/IronPython)."""
    p = vft.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
    if p:
        return p.AsString()
    # Fallback LookupParameter
    p2 = vft.LookupParameter("Type Name")
    if p2:
        return p2.AsString()
    return None


def get_or_create_vft(doc, fam_enum, custom_type_name):
    """
    Retourne l'ElementId du ViewFamilyType correspondant a fam_enum + custom_type_name.
    Si custom_type_name est vide, retourne le premier VFT de la famille.
    Cree le type par duplication si absent du projet.
    """
    all_vfts = list(FilteredElementCollector(doc).OfClass(ViewFamilyType))
    base_vft = next((vf for vf in all_vfts if vf.ViewFamily == fam_enum), None)
    if not base_vft:
        raise RuntimeError(
            u"Aucun ViewFamilyType trouve pour la famille {}.".format(fam_enum)
        )

    if not custom_type_name:
        return base_vft.Id

    target_vft = next(
        (vf for vf in all_vfts
         if vf.ViewFamily == fam_enum and _get_vft_name(vf) == custom_type_name),
        None
    )
    if target_vft:
        return target_vft.Id

    # Creation par duplication dans une transaction propre
    tx = Transaction(doc, u"Creer type de vue {}".format(custom_type_name))
    tx.Start()
    dup_res = base_vft.Duplicate(custom_type_name)
    target_vft = dup_res if isinstance(dup_res, ViewFamilyType) else doc.GetElement(dup_res)
    tx.Commit()
    return target_vft.Id


def _get_vft_id_for_candidate(doc, fam_enum, tvp_row, cfg, _vft_cache, vue_id=None):
    """
    Retourne l'ElementId du VFT pour la combinaison (tvp_label, fam_enum).
    Utilise un cache dict {type_name: vft_id} pour éviter les doublons.
    vue_id : identifiant explicite (ex. 'vue-surface'). Prioritaire sur _FAMILY_TEMPLATE_ID.
    """
    tvp_label = (tvp_row or {}).get(u'label', u'')
    vue_id    = vue_id if vue_id else (_FAMILY_TEMPLATE_ID.get(fam_enum) or u'')
    type_name = get_type_for_vue_id(cfg, tvp_label, vue_id)

    cache_key = (fam_enum, type_name)
    if cache_key in _vft_cache:
        return _vft_cache[cache_key]

    vft_id = get_or_create_vft(doc, fam_enum, type_name)
    _vft_cache[cache_key] = vft_id
    return vft_id


def prepare_view_creation(doc, fam_enum, tvp_row, cfg, vue_id=None):
    """
    Resout le ViewFamilyType et le gabarit pour la creation de vues.
    Cree le VFT par duplication si absent du projet.
    Retourne (vft_id, gabarit_name) ou leve RuntimeError si VFT introuvable.
    """
    _vft_cache = {}
    vft_id = _get_vft_id_for_candidate(doc, fam_enum, tvp_row, cfg, _vft_cache, vue_id=vue_id)
    gabarit = _get_gabarit_name(cfg, tvp_row, fam_enum, vue_id=vue_id)
    return vft_id, gabarit


def create_view_element(doc, vue_name, lvl_nm, fam_enum, vft_id, levels,
                         gabarit_name, warnings=None):
    """
    Cree UNE vue Revit et retourne l'objet View.
    DOIT etre appelee a l'interieur d'une Transaction ouverte.
    Retourne None si impossible (niveau introuvable, legende sans source, etc.).
    """
    if fam_enum == ViewFamily.Drafting:
        view = ViewDrafting.Create(doc, vft_id)
    elif _vf_legend is not None and fam_enum == _vf_legend:
        _src_legends = [
            v for v in FilteredElementCollector(doc).OfClass(View)
            if not v.IsTemplate and v.ViewType.ToString() == u'Legend'
        ]
        if not _src_legends:
            if warnings is not None:
                warnings.append(u'[Legend] Aucune legende existante pour duplication.')
            return None
        _dup_id = _src_legends[0].Duplicate(ViewDuplicateOption.Duplicate)
        view = doc.GetElement(_dup_id)
    else:
        lvl = levels.get(lvl_nm)
        if not lvl:
            return None
        view = ViewPlan.Create(doc, vft_id, lvl.Id)
    # Nommer la vue — si le nom est deja pris (autre famille), ajouter un suffixe numerote.
    _name_set = False
    for _attempt, _candidate in enumerate(
            [vue_name] + [u'{} ({})'.format(vue_name, _n) for _n in range(1, 50)]):
        try:
            view.Name = _candidate
            _name_set = True
            break
        except Exception:
            continue
    if not _name_set:
        try:
            doc.Delete(view.Id)
        except Exception:
            pass
        return None
    _apply_view_template(doc, view, gabarit_name)
    return view


def create_views_from_candidates(doc, candidates, selected_files, levels,
                                  fam_enum, tvp_row, cfg,
                                  do_vue_niveau=False, vue_id=None, warnings=None):
    """
    Cree les vues Revit manquantes pour les fichiers candidats selectionnes.

    Parametres
    ----------
    doc            : Document Revit
    candidates     : liste de tuples dont [0]=filename, [1]=lvl_name
    selected_files : collection des noms de fichiers selectionnes
    levels         : dict {lvl_name: Level}
    fam_enum       : ViewFamily (pour brancher sur la bonne classe de vue)
    tvp_row        : dict depuis types_vues_personnalises (doit contenir 'label', 'titre', etc.)
    cfg            : dict config.json
    do_vue_niveau  : si True, une vue par niveau (nommage via template) ;
                     sinon une vue par fichier (nom = filename)
    vue_id         : identifiant de la famille de vue dans nommage_vues (ex. 'vue-surface').
                     Permet de distinguer vue-plan et vue-surface (meme ViewFamily.FloorPlan).
                     Si None, derive depuis _FAMILY_TEMPLATE_ID.

    Le ViewFamilyType est résolu depuis cfg['types_vues'][label][vue_id].
    Si absent du projet, il est créé par duplication.
    Le gabarit de vue est résolu depuis cfg['gabarits_vues'][label][vue_id].

    Retourne la liste des noms de vues effectivement creees.
    """
    # Noms existants uniquement pour la meme famille de vue,
    # pour ne pas bloquer la creation d'une vue d'une autre famille avec le meme nom.
    _family_vft_ids = set(
        vf.Id for vf in FilteredElementCollector(doc).OfClass(ViewFamilyType)
        if vf.ViewFamily == fam_enum
    )
    existing_names = {
        v.Name for v in FilteredElementCollector(doc).OfClass(View)
        if not v.IsTemplate and v.GetTypeId() in _family_vft_ids
    }

    # Construire le dict complet des variables {vue-pers-*} pour les templates
    _tpl_vars = get_template_vars(tvp_row)

    def _build_name(lvl_name, filename):
        if do_vue_niveau:
            vars_dict = dict(_tpl_vars)
            vars_dict[u'niveau'] = lvl_name
            return resolve_view_name(fam_enum, vars_dict, cfg, vue_id=vue_id)
        return filename

    # Resoudre (et creer si necessaire) le VFT AVANT d'ouvrir la Transaction
    # de creation de vues — Revit interdit les transactions imbriquees.
    try:
        vft_id, _gabarit_name = prepare_view_creation(doc, fam_enum, tvp_row, cfg, vue_id=vue_id)
    except RuntimeError:
        return []

    created = []
    seen    = set()

    t = Transaction(doc, u"Creer vues depuis fichiers")
    t.Start()
    for cand in candidates:
        fn     = cand[0]
        lvl_nm = cand[1]
        if fn not in selected_files:
            continue
        vue_name = _build_name(lvl_nm, fn)
        if vue_name in existing_names or vue_name in seen:
            continue
        seen.add(vue_name)
        view = create_view_element(doc, vue_name, lvl_nm, fam_enum, vft_id, levels,
                                    _gabarit_name, warnings=warnings)
        if view is None:
            continue
        created.append(vue_name)
    t.Commit()
    return created
