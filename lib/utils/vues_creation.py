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
    View3D,
    ViewPlan,
    ViewDrafting,
    ViewFamily,
    ViewFamilyType,
    ViewDuplicateOption,
    FilteredElementCollector,
    Transaction,
    BuiltInParameter,
)
import re

from utils.types_vues_personnalises import get_type_for_vue_id, get_template_vars

# ---------------------------------------------------------------------------
# Casse des variables de template
# ---------------------------------------------------------------------------
# La casse ECRITE du jeton pilote la casse de la valeur produite :
#     {phase}   -> tout en minuscules
#     {PHASE}   -> TOUT EN MAJUSCULES
#     {Phase}   -> 1re lettre en majuscule, le reste en minuscules
#
# Deux suffixes couvrent ce que la casse du jeton ne peut pas exprimer :
#     {phase:val}  -> valeur brute, inchangee (telle que fournie par Revit)
#     {phase:cap}  -> Chaque Mot De La Valeur Capitalise
#
# NB : ce bloc est volontairement duplique a l'identique dans
# utils/extrac_nom_fichier_convention.py. Les deux modules sont charges
# independamment par des scripts differents ; les coupler creerait une
# dependance d'import supplementaire sans benefice.

# Variables dont la valeur n'est JAMAIS transformee, quelle que soit la casse
# ecrite : le nom de niveau provient de Revit et sert aussi de cle de
# correspondance (recherche du Level, detection des vues existantes). Le
# modifier casserait ces rapprochements. Equivaut a un ':val' implicite.
_CASSE_EXEMPT = frozenset([u'niveau', u'niveau-code'])

# Variables du domaine "nommage de vues". Une variable de cette liste absente
# du dict fourni par le script appelant est traitee comme VIDE : le segment
# correspondant disparait proprement, au lieu de laisser un jeton litteral
# (ex. "FM - {niveau} - 3D") dans le nom de la vue Revit.
#
# Cas concrets couverts : Pieces 3D ne fournit pas {niveau}, et le mode
# "creation par fichier" de Lier CAO ne fournit pas {phase}.
#
# Les jetons HORS de cette liste (faute de frappe, ex. "{nivo}") restent
# litteraux : c'est le signal qui permet de reperer l'erreur de saisie.
_VARIABLES_CANONIQUES = (
    u'vue-pers-titre', u'vue-pers-label', u'vue-pers-valeur-1',
    u'vue-pers-valeur-2', u'vue-pers-usage',
    u'niveau', u'phase', u'categorie', u'type-nomenclature',
)

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
    """
    Applique la casse demandee a 'valeur'.

    jeton   : nom tel qu'ecrit dans le template (ex. 'PHASE', 'Vue-pers-titre')
    var_id  : identifiant reel, en minuscules (ex. 'vue-pers-titre')
    valeur  : valeur brute a transformer
    suffixe : suffixe explicite eventuel ('val' ou 'cap'), sinon ''
    """
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


def variables_inconnues(template, variables_admises=None):
    """
    Retourne la liste ordonnee et dedoublonnee des jetons {xxx} du template qui
    ne correspondent a aucune variable connue.

    Un jeton inconnu (faute de frappe, ex. "{nivo}") serait recopie tel quel
    dans le nom de l'element Revit : la vue s'appellerait "FM - {nivo}". On le
    detecte donc AVANT toute creation, plutot que de polluer le modele.

    template          : chaine du template (ex. "{vue-pers-titre:val} - {nivo}")
    variables_admises : iterable d'identifiants autorises. Par defaut,
                        _VARIABLES_CANONIQUES (domaine du nommage de vues).

    Retourne [] si tout est reconnu.
    """
    if not template:
        return []
    _admises = set(
        (variables_admises if variables_admises is not None
         else _VARIABLES_CANONIQUES))
    _admises = set(_a.lower() for _a in _admises)

    _inconnues = []
    for _brut in _TOKEN_RE.findall(template):
        _jeton = _brut.split(u':')[0] if u':' in _brut else _brut
        if not _jeton.strip():
            continue
        if _jeton.lower() not in _admises and _jeton not in _inconnues:
            _inconnues.append(_jeton)
    return _inconnues


def verifier_template(cfg, vue_id, variables_admises=None):
    """
    Controle le template de nommage d'une entree de nommage_vues AVANT toute
    creation d'element Revit.

    Retourne (ok, message) :
      ok      : True si aucune variable inconnue
      message : texte pret a afficher a l'utilisateur si ok vaut False

    A appeler en debut de script, avant d'ouvrir la Transaction : un jeton
    inconnu produirait des elements nommes "FM - {nivo}".
    """
    _nommage = (cfg.get(u'conventions_nommage') or {}).get(u'nommage_vues', [])
    _tpl = u''
    _label = vue_id
    for _entry in _nommage:
        if _entry.get(u'id') == vue_id:
            _tpl = _entry.get(u'template', u'') or u''
            _label = _entry.get(u'label', vue_id) or vue_id
            break

    _inconnues = variables_inconnues(_tpl, variables_admises)
    if not _inconnues:
        return True, u''

    _msg = (
        u"La convention de nommage de la ligne « {} » contient "
        u"{} inconnue{} :\n\n    {}\n\n"
        u"Template actuel :\n    {}\n\n"
        u"Ces variables seraient recopiées telles quelles dans le nom des "
        u"éléments créés. Corrigez la ligne dans "
        u"01_Parametres > Nommage > Nommage des vues, puis relancez."
    ).format(
        _label,
        u"une variable" if len(_inconnues) == 1 else u"des variables",
        u"" if len(_inconnues) == 1 else u"s",
        u", ".join(u"{%s}" % _i for _i in _inconnues),
        _tpl,
    )
    return False, _msg


def substituer_variables(texte, vars_dict):
    """
    Remplace les jetons {variable} de 'texte' par leur valeur dans vars_dict,
    en appliquant la casse demandee.

    La correspondance des noms est insensible a la casse. Un jeton inconnu est
    laisse tel quel dans le texte (comportement historique).
    """
    if not texte:
        return texte
    _vars_low = {}
    for _k, _v in vars_dict.items():
        _vars_low[_k.lower()] = _v

    def _remplacer(_m):
        _brut = _m.group(1)
        if u':' in _brut:
            _jeton, _, _sfx = _brut.partition(u':')
        else:
            _jeton, _sfx = _brut, u''
        _var_id = _jeton.lower()
        if _var_id not in _vars_low:
            return _m.group(0)          # jeton inconnu : inchange
        return _appliquer_casse(_jeton, _var_id, _vars_low[_var_id], _sfx)

    return _TOKEN_RE.sub(_remplacer, texte)

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
_vf_threed = getattr(ViewFamily, u'ThreeDimensional', None)
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
    # La substitution honore la casse ecrite du jeton ({NIVEAU}, {Niveau}...).
    # Complete les variables du domaine non fournies par l'appelant, pour
    # qu'un jeton valide mais sans valeur disparaisse au lieu de rester
    # litteral dans le nom (voir _VARIABLES_CANONIQUES).
    _vars = dict(vars_dict)
    for _cle in _VARIABLES_CANONIQUES:
        _vars.setdefault(_cle, u'')

    _SEP = u' - '
    _segments = tpl.split(_SEP)
    _resolved = []
    for _seg in _segments:
        _val = substituer_variables(_seg, _vars)
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


def _apply_view_phase(view, phase):
    """
    Affecte la phase de projet 'phase' (DB.Phase) au parametre Phase de 'view',
    si ce parametre existe et n'est pas en lecture seule (absent sur les vues
    de dessin et les legendes). Ne fait rien si phase est None.
    Doit etre appele a l'interieur d'une Transaction ouverte.
    """
    if phase is None:
        return
    try:
        p = view.get_Parameter(BuiltInParameter.VIEW_PHASE)
        if p is not None and not p.IsReadOnly:
            p.Set(phase.Id)
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
                         gabarit_name, phase=None, warnings=None):
    """
    Cree UNE vue Revit et retourne l'objet View.
    DOIT etre appelee a l'interieur d'une Transaction ouverte.
    Retourne None si impossible (niveau introuvable, legende sans source, etc.).

    phase : DB.Phase optionnel. Si fourni, affecte au parametre Phase de la
            vue creee (BuiltInParameter.VIEW_PHASE). Sans effet sur les
            familles de vue qui n'exposent pas ce parametre (Drafting, Legend).
    """
    if fam_enum == ViewFamily.Drafting:
        view = ViewDrafting.Create(doc, vft_id)
    elif _vf_threed is not None and fam_enum == _vf_threed:
        # Une vue 3D n'est pas liee a un niveau : lvl_nm est ignore.
        view = View3D.CreateIsometric(doc, vft_id)
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
    _apply_view_phase(view, phase)
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
