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
NM-BATII — Vues +
Cree en masse des vues en plan a partir des niveaux batiment
et d'un type de vue personnalise defini dans config.json.

Structure attendue dans config.json :
  "vues_en_masse": {
    "types_vues": [
      {
        "nom":            "Plans de reperage",
        "famille":        "Plan d'etage",
        "nom_type_vue":   "TRAITEMENTS DONNEES EXISTANTES",
        "template_nom":   "{nom_niveau} - Reperage"
      }
    ],
    "filtres_types_niveaux_defaut": {
      "batiment":   true,
      "toiture":    false,
      "fondations": false,
      "origine":    false,
      "autres":     false
    }
  }

Le template_nom accepte le placeholder {nom_niveau}
(remplace par le nom du niveau Revit), ainsi que {phase} (remplace par le
nom de la phase de projet selectionnee dans la fenetre de dialogue).

Pour les familles de vue exposant un parametre Phase (Plan d'etage, Plan de
faux plafond, Vue en plan Structure), une vue est creee par combinaison
(niveau x phase) et le parametre Phase de la vue est renseigne en
consequence. Pour les familles sans parametre Phase (Vue de dessin,
Legende), une seule vue est creee par niveau.

La famille Vue 3D n'est pas liee a un niveau : la liste des niveaux est
grisee et une seule vue isometrique est creee par phase cochee.

Les familles proposees dans le menu sont celles dont la case "Vues +" est
cochee dans 01_Parametres > Nommage > Disponibilites familles de vues.
Coupe et Elevation ne sont pas prises en charge par cet outil (cases
desactivees dans ce dialogue).

Auteur : d8b
Version : 1.3
"""

import sys
import os
import re
import traceback

import clr
clr.AddReference('PresentationFramework')
from System.Windows.Controls import CheckBox as WPFCheckBox
from System.Windows import Thickness

from Autodesk.Revit.DB import (
    Element,
    FilteredElementCollector,
    BuiltInCategory,
    BuiltInParameter,
    View3D,
    ViewPlan,
    ViewDrafting,
    ViewFamily,
    ViewFamilyType,
    Transaction,
)

from pyrevit import forms, revit

# ---------------------------------------------------------------------------
# Ajout de lib/ au sys.path
# ---------------------------------------------------------------------------
_script_dir = os.path.dirname(__file__)
_ext_dir    = os.path.abspath(
    os.path.join(_script_dir, os.pardir, os.pardir, os.pardir)
)
_lib_dir = os.path.join(_ext_dir, "lib")
if _lib_dir not in sys.path:
    sys.path.append(_lib_dir)

from utils.config_loader import load_config
from dialogs.dialogs_styles_loader import load as charger_styles, show_alert
import dialogs.selection_liste as _selection_liste_mod
reload(_selection_liste_mod)
from dialogs.selection_liste import choisir_dans_liste
import utils.types_vues_personnalises as _tvp_mod
reload(_tvp_mod)
from utils.types_vues_personnalises import (get_types_vues, get_row_by_label,
                                            get_template_vars,
                                            filtrer_labels_pour_famille,
                                            filtrer_labels_pour_disciplines,
                                            get_disciplines_utilisees,
                                            cle_ordre as _cle_ordre)
import utils.disciplines as _disc_mod
reload(_disc_mod)
import dialogs.combo_recherche as _combo_mod
reload(_combo_mod)
from dialogs.combo_recherche import ComboCherchable
import dialogs.combo_multi_cases as _combo_multi_mod
reload(_combo_multi_mod)
from dialogs.combo_multi_cases import ComboMultiCases
import utils.vues_creation as _vues_creation_mod
reload(_vues_creation_mod)
from utils.vues_creation import (prepare_view_creation, create_view_element,
                                 resolve_view_name, verifier_template)

# Chargement des styles WPF communs NM-BATII
charger_styles(lib_dir=_lib_dir)

# ---------------------------------------------------------------------------
# Fonctions utilitaires
# ---------------------------------------------------------------------------

def get_vft_name(vft):
    """Retourne le nom du ViewFamilyType via le parametre SYMBOL_NAME_PARAM."""
    param = vft.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
    return param.AsString() if param else None


def _phase_name(phase):
    """
    Retourne le nom d'une phase de projet (DB.Phase).
    Contournement IronPython : Element.Name est implemente en interface
    explicite sur certains types, ce qui fait echouer l'acces direct phase.Name.
    """
    return Element.Name.__get__(phase)


_VF_THREED = getattr(ViewFamily, u'ThreeDimensional', None)

# Familles de vue exposant un parametre Phase (BuiltInParameter.VIEW_PHASE).
# Les vues de dessin et legendes n'ont pas ce parametre.
# AreaPlan (Plan de surface) derive de ViewPlan et porte bien ce parametre :
# il est traite comme les autres plans, une vue par (niveau x phase cochee).
_FAM_SUPPORTS_PHASE = set([
    ViewFamily.FloorPlan,
    ViewFamily.AreaPlan,
    ViewFamily.CeilingPlan,
    ViewFamily.StructuralPlan,
])
if _VF_THREED is not None:
    _FAM_SUPPORTS_PHASE.add(_VF_THREED)

# Marqueur affiche DANS une liste deroulante que la cascade a videe. Un menu
# vide et grise ne dit pas s'il n'y a rien ou si le remplissage a echoue ; ce
# faux item le dit, sans allonger les libelles ni la fenetre.
# Il n'est jamais une valeur : ComboCherchable.valeur() rend None dessus.
_AUCUNE_VALEUR = u"< Aucune valeur disponible >"


# Identifiants nommage_vues dont les vues ne sont PAS liees a un niveau Revit.
# Pour ceux-ci, la liste des niveaux est ignoree (et grisee dans le dialogue) :
# une seule vue est creee par phase cochee.
_VUE_IDS_SANS_NIVEAU = set([u'vue-3d'])


def collecter_niveaux(doc):
    """
    Retourne tous les niveaux Revit tries par elevation decroissante
    (du plus haut au plus bas).
    """
    tous_niveaux = list(
        FilteredElementCollector(doc)
        .OfCategory(BuiltInCategory.OST_Levels)
        .WhereElementIsNotElementType()
        .ToElements()
    )
    return sorted(tous_niveaux, key=lambda lvl: lvl.Elevation, reverse=True)


def construire_filtres(prefixes_config, vm_defaults):
    """
    Construit la liste des items de filtres depuis les prefixes config.json.
    Retourne une liste de tuples :
      (definition_key_lower_or_None, label_affiche, [prefixes], default_checked)

    definition_key_lower_or_None :
      - str lowercase (ex: "batiment") pour les definitions reconnues
      - None pour "Autres"
    """
    # Regrouper les prefixes par definition
    def_to_pfxs = {}
    for p in prefixes_config:
        defn = p.get(u"definition", u"")
        pfx  = p.get(u"prefixe",    u"")
        if defn:
            if defn not in def_to_pfxs:
                def_to_pfxs[defn] = []
            def_to_pfxs[defn].append(pfx)

    items = []
    for defn in sorted(def_to_pfxs.keys()):
        pfxs  = def_to_pfxs[defn]
        label = u"{} - {}".format(defn, u", ".join(pfxs))
        key   = defn.lower()
        default = vm_defaults.get(key, key == u"batiment")
        items.append((key, label, pfxs, default))

    # "Autres" en dernier
    autres_default = vm_defaults.get(u"autres", False)
    items.append((None, u"Autres", [], autres_default))

    return items



def vue_existe_par_nom(doc, nom_vue, fam_enum):
    """
    Retourne True si une vue portant exactement nom_vue et appartenant
    a fam_enum existe deja dans le projet.
    """
    if fam_enum == ViewFamily.Drafting:
        vues = list(
            FilteredElementCollector(doc)
            .WhereElementIsNotElementType()
            .OfClass(ViewDrafting)
            .ToElements()
        )
        return any(v.Name == nom_vue for v in vues)

    if _VF_THREED is not None and fam_enum == _VF_THREED:
        vues_3d = list(
            FilteredElementCollector(doc)
            .WhereElementIsNotElementType()
            .OfClass(View3D)
            .ToElements()
        )
        return any((not v.IsTemplate) and v.Name == nom_vue for v in vues_3d)

    vues_plan = list(
        FilteredElementCollector(doc)
        .WhereElementIsNotElementType()
        .OfClass(ViewPlan)
        .ToElements()
    )
    for v in vues_plan:
        if v.Name != nom_vue:
            continue
        vft = doc.GetElement(v.GetTypeId())
        if vft and vft.ViewFamily == fam_enum:
            return True
    return False



# ---------------------------------------------------------------------------
# Corps principal
# ---------------------------------------------------------------------------

def main():
    try:
        doc = revit.doc

        # -- 1. Charger la configuration --
        cfg = load_config()
        cfg_masse   = cfg.get(u"vues_en_masse", {})
        vm_defaults = cfg_masse.get(u"filtres_types_niveaux_defaut", {})

        # -- 2. Prefixes depuis config --
        prefixes_config = cfg.get(u"creer_niveaux", {}).get(u"prefixes", [])

        # -- Familles de vues disponibles (depuis nommage_vues avec vues_plus=True) --
        _VUE_ID_TO_FAMILY = {
            u'vue-plan':      ViewFamily.FloorPlan,
            u'vue-plaf':      ViewFamily.CeilingPlan,
            u'vue-structure': ViewFamily.StructuralPlan,
            u'vue-dessin':    ViewFamily.Drafting,
            # Plan de surface = AreaPlan, PAS FloorPlan : mappe sur FloorPlan,
            # ViewPlan.Create() produisait des plans d'etage.
            u'vue-surface':   ViewFamily.AreaPlan,
        }
        _vf_legend = getattr(ViewFamily, u'Legend', None)
        if _vf_legend is not None:
            _VUE_ID_TO_FAMILY[u'vue-legende'] = _vf_legend
        if _VF_THREED is not None:
            _VUE_ID_TO_FAMILY[u'vue-3d'] = _VF_THREED

        _nommage_vues_cfg = cfg.get(u'conventions_nommage', {}).get(u'nommage_vues', [])
        view_options = []
        _fams_non_gerees = []
        for _nv in _nommage_vues_cfg:
            if _nv.get(u'vues_plus', False):
                _fam = _VUE_ID_TO_FAMILY.get(_nv.get(u'id', u''))
                if _fam is not None:
                    view_options.append((_nv.get(u'label', u''), _fam, _nv.get(u'id', u'')))
                else:
                    # Famille cochee dans les parametres mais non prise en charge
                    # par Vues + (ex. Coupe, Elevation) : on le signale au lieu
                    # de l'ignorer silencieusement.
                    _fams_non_gerees.append(_nv.get(u'label', _nv.get(u'id', u'?')))
        if _fams_non_gerees:
            show_alert(
                u"Familles de vues non prises en charge",
                u"Les familles suivantes sont cochées dans la colonne "
                u"« Vues + » des paramètres mais ne sont pas gérées "
                u"par cet outil, elles n'apparaîtront pas dans la liste :\n\n"
                u"  • {}".format(u"\n  • ".join(_fams_non_gerees)))
        if not view_options:
            view_options = [
                (u"Plan d'\xe9tage",           ViewFamily.FloorPlan,      u'vue-plan'),
                (u"Plans de faux-plafonds", ViewFamily.CeilingPlan,    u'vue-plaf'),
                (u"Plan de structure",      ViewFamily.StructuralPlan, u'vue-structure'),
                (u"Vue de dessin",          ViewFamily.Drafting,       u'vue-dessin'),
            ]
        view_labels   = [lbl for lbl, _, __ in view_options]
        view_families = {lbl: fam for lbl, fam, _ in view_options}
        view_vue_ids  = {lbl: vid for lbl, _, vid in view_options}

        # -- Types personnalises filtrés par disponibilité --
        _tvp_list_all = get_types_vues(cfg)
        # Lignes systeme, toujours en tete (meme ordre que 01_Parametres)
        # « Ord. » est du TEXTE libre depuis qu'il accepte « A1 » ou « 10bis » :
        # le tri passe par la clé naturelle partagée, sinon « 10 » se rangerait
        # avant « 2 ». Les lignes système restent en tête (préfixe 0).
        # Comparaison en MAJUSCULES : les labels le sont depuis que la fenetre
        # des parametres les normalise, mais une config pas encore
        # re-enregistree porte encore « Temporaire ». Sans cela cette ligne
        # perdrait sa place en tete de liste.
        _TVP_LOCKED_ORD = {u'PIECES 3D': 0, u'TEMPORAIRE': 1, u'FM': 2}
        def _tvp_ord_key(t):
            _lbl = (t.get(u'label', u'') or u'').upper()
            if _lbl in _TVP_LOCKED_ORD:
                return (0, _cle_ordre(_TVP_LOCKED_ORD[_lbl]))
            return (1, _cle_ordre(t.get(u'ordre', u'')))
        _tvp_sorted = sorted(_tvp_list_all, key=_tvp_ord_key)
        _dispo_tpd  = {d.get(u'label', u''): d.get(u'vues_plus', True)
                       for d in cfg.get(u'dispo_types_pers_lier_cao', [])}
        # Disponibilite par SCRIPT (colonne "Vues +"). La disponibilite par
        # FAMILLE de vue est appliquee ensuite, a chaque changement du menu
        # "Famille de vue" (voir _maj_types_pers ci-dessous).
        _tvp_labels = [t.get(u'label', u'') for t in _tvp_sorted
                       if _dispo_tpd.get(t.get(u'label', u''), True)]
        _tvp_list   = _tvp_sorted

        # -- 3. Construire les patterns regex prefixe -> definition --
        # Format des noms Revit : {bat_code}_<PREFIXE><signe><num>_<demi>
        # Ex : s1234567_001_R+00_0  →  _R+ est present dans le nom
        # On utilise re.search pour localiser le prefixe au sein du nom complet.
        _sign_pos = cfg.get(u"creer_niveaux", {}).get(u"signe_positif", u"+")
        _sign_neg = cfg.get(u"creer_niveaux", {}).get(u"signe_negatif", u"-")

        # Liste de (regex_compile, definition_key_lower) par ordre de declaration
        _pfx_patterns = []
        for _p in prefixes_config:
            _pfx  = _p.get(u"prefixe",    u"")
            _defn = _p.get(u"definition", u"")
            if _pfx:
                # Chercher : underscore + prefixe + (signe_pos ou signe_neg)
                # L'underscore precedent garantit qu'on ne match pas en plein milieu
                # d'un autre token. Ex : "_R+" dans "s1234567_001_R+00_0"
                _pat = re.compile(
                    u"_" + re.escape(_pfx)
                    + u"[" + re.escape(_sign_pos) + re.escape(_sign_neg) + u"]"
                )
                _pfx_patterns.append((_pat, _defn.lower()))

        def _def_key_for_nom(nom):
            """Retourne la definition_key (lowercase) du niveau, ou None si 'Autres'."""
            for _pat, _defn_key in _pfx_patterns:
                if _pat.search(nom):
                    return _defn_key
            return None

        # -- 4. Collecter tous les niveaux (tri decroissant = plus haut en premier) --
        niveaux = collecter_niveaux(doc)
        if not niveaux:
            show_alert(u"Aucun niveau",
                       u"Le projet Revit ne contient aucun niveau.",
                       centrer=True)
            return

        noms_niveaux = [lvl.Name for lvl in niveaux]
        map_niveaux  = {lvl.Name: lvl for lvl in niveaux}

        # -- 4bis. Collecter les phases du projet --
        phases_projet = list(doc.Phases)
        if not phases_projet:
            show_alert(u"Aucune phase", u"Aucune phase trouv\u00e9e dans le projet.")
            return

        # -- 5. Construire les filtres --
        filtre_items = construire_filtres(prefixes_config, vm_defaults)

        # -- 6. Fenetre WPF de selection --
        xaml_path = os.path.join(_script_dir, "WPFWindow.xaml")
        win = forms.WPFWindow(xaml_path)

        # -- 6ter. Cascade Discipline -> Sous-discipline -> Famille -> Type ---
        # Les quatre menus forment une cascade : chacun ne propose que des
        # valeurs qui laissent au moins un choix au suivant. Une famille dont
        # plus aucun type personnalise ne releve pour la discipline courante
        # n'est donc pas affichee, au lieu de mener a un menu « Type
        # personnalise » vide.
        #
        # Deux tables portent ces disponibilites, cumulatives :
        # cfg['dispo_types_pers_familles'] (colonne "Familles de vues" de
        # 01_Parametres > Vues > Vues personnalisees) et
        # cfg['dispo_types_pers_disciplines'] (colonne "Discipline").
        #
        # Les disciplines proposees sont celles REELLEMENT employees par les
        # vues personnalisees disponibles ici, et NON les ~100 lignes du
        # referentiel de l'onglet « Disciplines » : la quasi-totalite n'y
        # menerait a aucun type, ce qui rendait le menu inutilisable.
        #
        # Indexe sur les listes de couples, pas sur le libelle affiche : deux
        # branches distinctes du referentiel peuvent partager un libelle.
        _TOUTES_DISC  = u"Toutes les disciplines"
        _TOUTES_SOUS  = u"Toutes les sous-disciplines"

        _fmt_disc   = _disc_mod.get_format(cfg)
        _codes_util = get_disciplines_utilisees(cfg, _tvp_labels)

        # Une sous-discipline employee implique sa discipline de tete : sans
        # cela « ARCHITECTURE » manquerait alors que « SPACE PLANNING » en
        # releve.
        _par_code = {}
        for _e_d in _disc_mod.get_table(cfg):
            _par_code[_disc_mod.code_ouvrage(_e_d, fmt=_fmt_disc)] = _e_d

        def _racine(code):
            """Code de la ligne de niveau 1 dont releve `code`."""
            _anc = _disc_mod.get_ancetres(code, cfg)
            return (_disc_mod.code_ouvrage(_anc[0], fmt=_fmt_disc)
                    if _anc else code)

        # [(code, libelle)] des disciplines de tete employees, triees.
        _disc_racines = []
        _vus_rac = set()
        for _c in sorted(_codes_util):
            if _c not in _par_code:
                continue          # code obsolete : referentiel modifie depuis
            _r = _racine(_c)
            if _r in _vus_rac or _r not in _par_code:
                continue
            _vus_rac.add(_r)
            _disc_racines.append(
                (_r, (_par_code[_r].get(u'discipline') or u'').strip() or _r))

        # {code_racine: [(code, libelle_sous), ...]} des sous-disciplines
        # employees, rangees sous leur discipline de tete.
        _sous_par_racine = {}
        for _c in sorted(_codes_util):
            _e = _par_code.get(_c)
            if _e is None or _disc_mod.get_niveau(_e, fmt=_fmt_disc) <= 1:
                continue
            _r = _racine(_c)
            _lbl_s = (_e.get(u'sous_discipline') or u'').strip() or _c
            _sous_par_racine.setdefault(_r, []).append((_c, _lbl_s))

        _disc_options = []      # [(code, libelle)] du menu Discipline
        _sous_options = []      # [(code, libelle)] du menu Sous-discipline

        # Remplir un ItemsSource declenche SelectionChanged : sans ce drapeau,
        # une mise a jour relancerait la cascade depuis son propre milieu, sur
        # des listes d'options a demi remplacees.
        _cascade_en_cours = {u'v': False}

        # L'indisponibilite s'affiche DANS le menu (_AUCUNE_VALEUR), pas dans
        # le libelle : la fenetre est en SizeToContent, une phrase la ferait
        # grandir. Le detail passe en infobulle — d'ou le
        # ToolTipService.ShowOnDisabled du XAML, sans quoi elle resterait
        # invisible sur un menu grise.
        _AIDE_INDISPO = (
            u"Aucun type personnalis\xe9 ne correspond \xe0 cette combinaison.\n"
            u"R\xe9glez les colonnes « Familles de vues », « Discipline » et "
            u"« Vues + » (colonne « Disponibilit\xe9 ») dans\n"
            u"01_Param\xe8tres > Vues > Vues personnalis\xe9es.")

        def _code_selectionne(combo_cherchable, options, marqueur):
            """Code associe au libelle retenu dans un menu, ou '' si neutre."""
            _v = combo_cherchable.valeur()
            if _v is None or _v == marqueur:
                return u''
            for _code, _lbl in options:
                if _lbl == _v:
                    return _code
            return u''

        def _codes_actifs():
            """
            Codes de discipline a tester pour le filtrage des types.

            Sous-discipline choisie -> ce seul code. Discipline seule -> la
            tete ET toutes ses sous-disciplines employees : choisir une
            discipline sans preciser doit rendre les types de TOUTE la branche.
            Rien de choisi -> aucun filtre.
            """
            _sc = _code_selectionne(_cmb_sous, _sous_options, _TOUTES_SOUS)
            if _sc:
                return [_sc]
            _dc = _code_selectionne(_cmb_disc, _disc_options, _TOUTES_DISC)
            if not _dc:
                return []
            return [_dc] + [_c for _c, _l in _sous_par_racine.get(_dc, [])]

        def _labels_disponibles():
            """Types personnalises passant les filtres Discipline + Sous."""
            return filtrer_labels_pour_disciplines(
                cfg, _tvp_labels, _codes_actifs())

        # --- Etage 2 : sous-disciplines de la discipline choisie -------------
        def _maj_sous_disciplines():
            _dc = _code_selectionne(_cmb_disc, _disc_options, _TOUTES_DISC)
            _opts = [(u'', _TOUTES_SOUS)]
            if _dc:
                _opts.extend(_sous_par_racine.get(_dc, []))
            else:
                # « Toutes les disciplines » : proposer toutes les
                # sous-disciplines employees, triees par discipline.
                for _r, _lbl_r in _disc_racines:
                    for _c, _lbl_s in _sous_par_racine.get(_r, []):
                        _opts.append((_c, u"{} — {}".format(_lbl_r, _lbl_s)))
            _prec = _code_selectionne(_cmb_sous, _sous_options, _TOUTES_SOUS)
            _sous_options[:] = _opts
            _codes = [_c for _c, _l in _opts]
            _cmb_sous.definir(
                [_l for _c, _l in _opts],
                selection=(_opts[_codes.index(_prec)][1]
                           if _prec in _codes else None))
            _cmb_sous.combo.IsEnabled = len(_opts) > 1
            _cmb_sous.combo.ToolTip = (
                None if len(_opts) > 1 else
                u"Aucune sous-discipline n'est renseign\xe9e pour cette "
                u"discipline dans les vues personnalis\xe9es.")

        # --- Etage 3 : familles de vues laissant au moins un type ------------
        def _maj_familles():
            _labels = _labels_disponibles()
            _opts = [_lbl for _lbl in view_labels
                     if filtrer_labels_pour_famille(
                         cfg, _labels, view_vue_ids.get(_lbl, u''))]
            _prec = _cmb_fam.valeur()
            if _opts:
                _cmb_fam.definir(_opts,
                                 selection=(_prec if _prec in _opts else None))
            else:
                _cmb_fam.definir([])
            _cmb_fam.combo.IsEnabled = bool(_opts)
            _cmb_fam.combo.ToolTip   = None if _opts else _AIDE_INDISPO

        # --- Etage 4 : types personnalises ----------------------------------
        def _maj_types_pers():
            _fam_lbl = _cmb_fam.valeur() or u''
            _dispo = filtrer_labels_pour_famille(
                cfg, _labels_disponibles(), view_vue_ids.get(_fam_lbl, u''))
            _prec = _cmb_type.valeur()
            if _dispo:
                _cmb_type.definir(
                    _dispo, selection=(_prec if _prec in _dispo else None))
            else:
                _cmb_type.definir([])
            _cmb_type.combo.IsEnabled = bool(_dispo)
            _cmb_type.combo.ToolTip   = None if _dispo else _AIDE_INDISPO
            # Sans type personnalise disponible, il n'y a rien a creer : on
            # bloque la validation plutot que de laisser produire des vues au
            # nommage incomplet.
            win.btnOk.IsEnabled = bool(_dispo)

        def _depuis(etage):
            """Rejoue la cascade a partir de l'etage donne."""
            if _cascade_en_cours[u'v']:
                return
            _cascade_en_cours[u'v'] = True
            try:
                if etage <= 2:
                    _maj_sous_disciplines()
                if etage <= 3:
                    _maj_familles()
                _maj_types_pers()
            finally:
                _cascade_en_cours[u'v'] = False

        _cmb_disc = ComboCherchable(win.cmbDiscipline,
                                    on_change=lambda: _depuis(2),
                                    marqueur_vide=_AUCUNE_VALEUR)
        _cmb_sous = ComboCherchable(win.cmbSousDiscipline,
                                    on_change=lambda: _depuis(3),
                                    marqueur_vide=_AUCUNE_VALEUR)
        _cmb_fam  = ComboCherchable(win.cmbViewFamily,
                                    on_change=lambda: _depuis(4),
                                    marqueur_vide=_AUCUNE_VALEUR)
        _cmb_type = ComboCherchable(win.cmbVueTypePers,
                                    marqueur_vide=_AUCUNE_VALEUR)

        _disc_options[:] = [(u'', _TOUTES_DISC)] + _disc_racines
        _cmb_disc.definir([_l for _c, _l in _disc_options])
        _cascade_en_cours[u'v'] = True
        try:
            _maj_sous_disciplines()
            _maj_familles()
            _maj_types_pers()
        finally:
            _cascade_en_cours[u'v'] = False

        # -- 6bis. Liste deroulante a cocher des phases --
        # Par defaut, seule la derniere phase du projet est cochee
        # (reproduit le comportement par defaut de Revit a la creation d'une vue).
        _cmb_phases = ComboMultiCases(win.cmbPhases,
                                      texte_vide=u"(aucune phase)")
        _cmb_phases.definir([(ph, _phase_name(ph)) for ph in phases_projet],
                            coches=[phases_projet[-1]])

        # -- 7. Creer les checkboxes de filtre dynamiquement --
        filter_checkboxes = []  # (key_or_None, [prefixes], checkbox_ctrl)

        def _get_noms_filtres():
            """Retourne la liste des noms de niveaux correspondant aux filtres actifs."""
            enabled_keys = set()
            enable_autres = False
            for key, pfxs, cb in filter_checkboxes:
                if cb.IsChecked:
                    if key is None:
                        enable_autres = True
                    else:
                        enabled_keys.add(key)

            result = []
            for nom in noms_niveaux:
                matched_def = _def_key_for_nom(nom)
                if matched_def is not None:
                    if matched_def in enabled_keys:
                        result.append(nom)
                else:
                    if enable_autres:
                        result.append(nom)
            return result

        def _update_niveau_list(sender=None, args=None):
            win.lstNiveaux.ItemsSource = _get_noms_filtres()

        for key, label, pfxs, default in filtre_items:
            cb = WPFCheckBox()
            cb.Content   = label
            cb.IsChecked = default
            cb.Margin    = Thickness(0, 0, 12, 2)
            from System.Windows import VerticalAlignment
            cb.VerticalContentAlignment = VerticalAlignment.Center
            win.pnlFiltresTypes.Children.Add(cb)
            filter_checkboxes.append((key, pfxs, cb))
            cb.Checked   += _update_niveau_list
            cb.Unchecked += _update_niveau_list

        # -- 7bis. Types de niveaux par defaut, propres au type personnalise --
        # Le reglage n'est plus global : chaque vue personnalisee porte ses
        # types de niveaux preselectionnes (01_Parametres > Vues > Vues
        # personnalisees, colonne "Types de niveaux par défaut"). On
        # reapplique donc les cases a chaque changement de type — l'utilisateur
        # reste libre de les modifier ensuite, c'est un etat initial.
        _niv_defaut_pers = {}
        for _nd in cfg.get(u'niveaux_defaut_types_pers', []) or []:
            _lbl_nd = _nd.get(u'label', u'')
            if _lbl_nd:
                _niv_defaut_pers[_lbl_nd] = _nd.get(u'niveaux', {}) or {}

        def _maj_filtres_niveaux(sender=None, args=None):
            # Les menus etant editables, la valeur se lit sur l'enveloppe et
            # non sur SelectedItem : ce dernier suit la liste filtree par la
            # frappe, pas la valeur reellement retenue.
            _lbl_tvp = _cmb_type.valeur()
            if _lbl_tvp is None:
                return
            # Repli sur l'ancien reglage global tant que ce type n'a pas ete
            # configure : comportement identique a celui d'avant.
            _defauts = _niv_defaut_pers.get(_lbl_tvp)
            if _defauts is None:
                _defauts = vm_defaults
            for _key_f, _pfxs_f, _cb_f in filter_checkboxes:
                _cle_f = _key_f if _key_f is not None else u'autres'
                _cb_f.IsChecked = bool(
                    _defauts.get(_cle_f, _cle_f == u'batiment'))

        win.cmbVueTypePers.SelectionChanged += _maj_filtres_niveaux
        _maj_filtres_niveaux()

        # Population initiale de la liste
        _update_niveau_list()

        # -- 8. Boutons de selection de la liste --
        def selectionner_tout(sender, args):
            for item in win.lstNiveaux.Items:
                if not win.lstNiveaux.SelectedItems.Contains(item):
                    win.lstNiveaux.SelectedItems.Add(item)

        def deselectionner_tout(sender, args):
            win.lstNiveaux.SelectedItems.Clear()

        def inverser_selection(sender, args):
            nouvelle = [
                item for item in win.lstNiveaux.Items
                if not win.lstNiveaux.SelectedItems.Contains(item)
            ]
            win.lstNiveaux.SelectedItems.Clear()
            for item in nouvelle:
                win.lstNiveaux.SelectedItems.Add(item)

        win.btnSelectAll.Click   += selectionner_tout
        win.btnDeselectAll.Click += deselectionner_tout
        win.btnInvert.Click      += inverser_selection

        # -- 8bis. Griser la zone "niveaux" pour les familles sans niveau (3D) --
        def _famille_sans_niveau():
            _lbl = _cmb_fam.valeur() or u''
            return view_vue_ids.get(_lbl, u'') in _VUE_IDS_SANS_NIVEAU

        def _maj_etat_niveaux(sender=None, args=None):
            _actif = not _famille_sans_niveau()
            for _ctrl in (win.txtLabelFiltres, win.pnlFiltresTypes,
                          win.txtLabelNiveaux, win.lstNiveaux,
                          win.btnSelectAll, win.btnDeselectAll, win.btnInvert):
                _ctrl.IsEnabled = _actif
            win.txtLabelNiveaux.Text = (
                u"Cochez les niveaux b\xe2timent \xe0 traiter :" if _actif
                else u"Niveaux : sans objet")
            win.txtLabelNiveaux.ToolTip = (
                None if _actif else
                u"Une vue 3D n'est pas li\xe9e \xe0 un niveau : une seule vue "
                u"est cr\xe9\xe9e par phase coch\xe9e.")

        win.cmbViewFamily.SelectionChanged += _maj_etat_niveaux
        _maj_etat_niveaux()

        win.btnOk.Click     += lambda s, e: setattr(win, "DialogResult", True)
        win.btnCancel.Click += lambda s, e: setattr(win, "DialogResult", False)

        if not win.ShowDialog():
            return

        # -- 9. Lecture de la selection --
        chosen_fam_lbl = _cmb_fam.valeur() or u''
        chosen_tvp_lbl = _cmb_type.valeur() or u''
        fam_enum       = view_families.get(chosen_fam_lbl, ViewFamily.FloorPlan)
        _chosen_vue_id = view_vue_ids.get(chosen_fam_lbl, u'')
        _selected_tvp  = get_row_by_label(cfg, chosen_tvp_lbl) or (_tvp_list[0] if _tvp_list else {})

        # Garde-fou : un jeton inconnu dans le template serait recopie tel quel
        # dans le nom des vues creees. On arrete avant toute transaction.
        _tpl_ok, _tpl_msg = verifier_template(cfg, _chosen_vue_id)
        if not _tpl_ok:
            show_alert(u"Convention de nommage invalide", _tpl_msg)
            return

        # Les familles sans niveau (3D) ignorent la liste des niveaux : on
        # boucle sur un unique pseudo-niveau vide pour n'obtenir qu'une vue
        # par phase cochee.
        _sans_niveau = _chosen_vue_id in _VUE_IDS_SANS_NIVEAU
        if _sans_niveau:
            niveaux_choisis = [u'']
        else:
            niveaux_choisis = [item for item in win.lstNiveaux.SelectedItems]
            if not niveaux_choisis:
                show_alert(u"Aucune selection",
                           u"Aucun niveau selectionne. Operation annulee.")
                return

        phases_choisies = _cmb_phases.valeurs()
        if not phases_choisies:
            show_alert(u"Aucune phase", u"Aucune phase selectionnee. Operation annulee.")
            return

        # Les familles sans parametre Phase (Drafting, Legende) ne creent
        # qu'une seule fois par niveau, en utilisant la premiere phase cochee
        # uniquement pour la resolution du template de nommage.
        _fam_supporte_phase  = fam_enum in _FAM_SUPPORTS_PHASE
        _phases_pour_creation = phases_choisies if _fam_supporte_phase else phases_choisies[:1]

        # -- 10. Resoudre le ViewFamilyType et le gabarit (avant la transaction) --
        try:
            vft_id, gabarit_name = prepare_view_creation(
                doc, fam_enum, _selected_tvp, cfg, vue_id=_chosen_vue_id)
        except RuntimeError as _e:
            show_alert(u"Type de vue introuvable", unicode(_e))
            return

        # -- 10bis. Gabarit configure mais absent du projet ---------------------
        # Un nom de gabarit errone est sans effet visible : la vue se cree, sans
        # gabarit, et rien ne le signale. On propose donc une substitution.
        # Fait AVANT la Transaction — une fenetre modale ouverte pendant une
        # transaction Revit laisserait le modele verrouille tout ce temps.
        _gabarit_configure = gabarit_name
        _gabarit_substitue = False
        if gabarit_name:
            _tpls_projet = _vues_creation_mod.get_view_templates(doc)
            _noms_tpl = [_vues_creation_mod.element_name(t) for t in _tpls_projet]
            if gabarit_name not in _noms_tpl:
                if not _tpls_projet:
                    show_alert(
                        u"Gabarit de vue introuvable",
                        u"Le gabarit « {} » configuré pour « {} » n'existe pas "
                        u"dans ce projet, qui ne contient d'ailleurs aucun "
                        u"gabarit de vue.\n\n"
                        u"Les vues seront créées sans gabarit.".format(
                            gabarit_name, chosen_tvp_lbl))
                    gabarit_name = u''
                else:
                    # Filtre de compatibilite sur le NOM D'ENUMERATION ; la
                    # traduction francaise n'intervient qu'a l'affichage.
                    _vt_attendu = _vues_creation_mod.VUE_ID_TO_VIEWTYPE.get(
                        _chosen_vue_id)
                    _fr = lambda _lst: [
                        (_vues_creation_mod.element_name(_t),
                         _vues_creation_mod.libelle_view_type(
                             cfg, _t.ViewType.ToString()))
                        for _t in _lst]
                    _compat = ([_t for _t in _tpls_projet
                                if _t.ViewType.ToString() == _vt_attendu]
                               if _vt_attendu else None)
                    _choix_tpl = choisir_dans_liste(
                        titre=u"Gabarit de vue introuvable — Vues +",
                        description=(
                            u"Sélectionnez le gabarit à appliquer aux vues "
                            u"« {} » créées, ou annulez pour les créer sans "
                            u"gabarit.".format(chosen_fam_lbl)),
                        note=(u"Le gabarit « {} » configuré dans 01_Paramètres "
                              u"> Vues > Vues personnalisées > Gabarits de "
                              u"vues (ligne « {} », type « {} ») n'existe pas "
                              u"dans ce projet.".format(
                                  gabarit_name, chosen_fam_lbl,
                                  chosen_tvp_lbl)),
                        entete_nom=u"Gabarit de vue",
                        entete_info=u"Type de vue",
                        items_tous=_fr(_tpls_projet),
                        items_compat=(_fr(_compat) if _compat is not None
                                      else None),
                        libelle_compat=(
                            u"Uniquement les gabarits compatibles avec "
                            u"« {} »".format(chosen_fam_lbl)),
                        valeur_courante=u'')
                    # Substitution valable pour CETTE execution seulement : la
                    # configuration n'est pas reecrite ici (seul 01_Parametres
                    # ecrit config.json). Le rapport final le rappelle.
                    gabarit_name = _choix_tpl or u''
                    _gabarit_substitue = bool(_choix_tpl)

        # -- 11. Creation des vues en transaction --
        vues_creees   = []
        vues_ignorees = []
        vues_erreurs  = []

        t = Transaction(doc, u"NM-BATII : Vues +")
        t.Start()
        try:
            for nom_niveau in niveaux_choisis:
                for _phase in _phases_pour_creation:
                    _lookup_vars = get_template_vars(_selected_tvp)
                    _lookup_vars[u'niveau'] = nom_niveau
                    _lookup_vars[u'phase']  = _phase_name(_phase)
                    nom_vue = resolve_view_name(
                        fam_enum, _lookup_vars, cfg, vue_id=_chosen_vue_id).strip()
                    if not nom_vue:
                        # Repli : nom du niveau, ou nom de la phase pour les
                        # familles sans niveau (3D).
                        nom_vue = nom_niveau or _phase_name(_phase)

                    if vue_existe_par_nom(doc, nom_vue, fam_enum):
                        vues_ignorees.append(nom_vue)
                        continue

                    try:
                        vue = create_view_element(
                            doc, nom_vue, nom_niveau, fam_enum,
                            vft_id, map_niveaux, gabarit_name,
                            phase=(_phase if _fam_supporte_phase else None))
                        if vue is None:
                            vues_erreurs.append(u"{} (creation impossible)".format(nom_vue))
                        else:
                            vues_creees.append(vue.Name)
                    except Exception as e_vue:
                        vues_erreurs.append(u"{} ({})".format(nom_vue, str(e_vue)))

            t.Commit()

        except Exception:
            t.RollBack()
            raise

        # -- 12. Rapport ResultWindow --
        res_xaml = os.path.join(_script_dir, "ResultWindow.xaml")
        res_win  = forms.WPFWindow(res_xaml)

        nb_crees   = len(vues_creees)
        nb_ignores = len(vues_ignorees)
        nb_erreurs = len(vues_erreurs)

        res_win.txtResume.Text = (
            u"{} vue(s) cr\u00e9\u00e9e(s)  |  {} ignor\u00e9e(s)  |  {} erreur(s)".format(
                nb_crees, nb_ignores, nb_erreurs
            )
        )

        # Substitution de gabarit : le rappeler ici, sinon rien ne distingue
        # une exécution normale d'une exécution où le réglage était erroné.
        _entete_gab = u""
        if _gabarit_substitue:
            _entete_gab = (
                u"[GABARIT SUBSTITUÉ]\n"
                u"  « {} » appliqué à la place de « {} », introuvable dans ce "
                u"projet.\n"
                u"  Remplacement valable pour cette exécution seulement — "
                u"corrigez-le dans\n"
                u"  01_Paramètres > Vues > Vues personnalisées > Gabarits de "
                u"vues pour le rendre permanent.\n\n".format(
                    gabarit_name, _gabarit_configure))
        elif _gabarit_configure and not gabarit_name:
            _entete_gab = (
                u"[SANS GABARIT]\n"
                u"  Le gabarit « {} » configuré est introuvable dans ce projet "
                u"et aucun\n  remplacement n'a été choisi : les vues sont "
                u"créées sans gabarit.\n\n".format(_gabarit_configure))

        if vues_creees:
            res_win.txtCreees.Text = (
                _entete_gab + u"[CREEES]\n"
                + u"\n".join(u"  + {}".format(n) for n in vues_creees)
            )
        else:
            res_win.txtCreees.Text = _entete_gab + u"[CREEES]\n  (aucune)"

        if vues_ignorees:
            res_win.txtIgnorees.Text = (
                u"\n[IGNOREES - vues existantes]\n"
                + u"\n".join(u"  ~ {}".format(n) for n in vues_ignorees)
            )
        else:
            res_win.txtIgnorees.Text = u""

        if vues_erreurs:
            res_win.txtErreurs.Text = (
                u"\n[ERREURS]\n"
                + u"\n".join(u"  ! {}".format(n) for n in vues_erreurs)
            )
        else:
            res_win.txtErreurs.Text = u""

        res_win.btnClose.Click += lambda s, e: setattr(res_win, "DialogResult", True)
        res_win.ShowDialog()

    except Exception:
        show_alert(u"Erreur NM-BATII", traceback.format_exc())


if __name__ == "__main__":
    main()
