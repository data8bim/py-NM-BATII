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
NM-BATII — Pièces 3D
Demande à l'utilisateur, via une interface dédiée, de choisir une phase du
projet et éventuellement une combinaison de paramètres de pièces servant à
coloriser les volumes, puis recrée, pour chaque pièce placée de cette phase,
un solide 3D (DirectShape, catégorie "Volume") correspondant à sa
volumétrie calculée par Revit. Permet de disposer d'une géométrie 3D réelle
des pièces, utile pour les vues 3D, les exports et les contrôles visuels de
volumétrie.

Rappel : la catégorie "Volume" n'est visible dans les vues que si l'option
"Afficher les catégories de masse" est activée (onglet Massage, ou
visibilité de catégorie de la vue/du gabarit).

Une vue 3D dédiée "<nom> - <phase>" est créée (ou réutilisée si elle existe
déjà), réglée sur la phase choisie, et reçoit le gabarit de vue configuré
s'il est présent dans le projet, puis devient la vue active.
Le type de vue Revit, le gabarit et le nom de base de cette vue sont résolus
via le même système de convention de nommage que les scripts "01_Vues_+" et
"01_Lier_CAO" (table "Nommage des vues", entrée "Vue 3D" ; table "Vues
personnalisées", "Types de vues" et "Gabarits de vues"), à partir du type
personnalisé désigné comme "Pièces 3D" dans NM-BATII.tab > 01_Parametres.panel
> Paramètres > onglet "Vues" > table "Vues personnalisées" > colonne
"Disponibilité" > case "Pièces 3D".

Si une combinaison de paramètres de pièces a été construite dans
l'interface, et qu'une couleur a été choisie pour tout ou partie des
valeurs générées, les volumes correspondants reçoivent une surcharge
graphique (couleur de ligne + remplissage plein) dans cette vue 3D
dédiée uniquement.

Toute géométrie précédemment générée par cet outil pour la phase choisie
est supprimée avant d'être reconstruite, afin d'éviter les doublons lors
des relances (les volumétries des autres phases, dans leurs propres vues,
ne sont pas affectées).
"""

import os
import json
import codecs
import colorsys
import clr
clr.AddReference('System.Drawing')
import System.Drawing
from pyrevit import revit, DB, forms, script
from Autodesk.Revit.DB import Element
from System.Collections.Generic import List
from System.Windows import Thickness, GridLength, GridUnitType, TextWrapping, VerticalAlignment
from System.Windows.Controls import Grid, ColumnDefinition, TextBlock, Button, Border
from System.Windows.Media import SolidColorBrush, Color as WpfColor, Brushes
from System.Windows.Forms import ColorDialog, SaveFileDialog, OpenFileDialog, DialogResult
import System.Windows.Threading as Threading

from dialogs.dialogs_styles_loader import load as _load_styles, show_alert, show_confirm
import dialogs.selection_liste as _selection_liste_mod
reload(_selection_liste_mod)
from dialogs.selection_liste import choisir_dans_liste
from utils.config_loader import load_config
from utils.types_vues_personnalises import (get_row_by_label, get_template_vars,
                                            get_type_for_vue_id)
# reload() avant le from-import : sans lui, un simple « Recharger » pyRevit
# laisse la version en cache de sys.modules et une fonction nouvellement
# ajoutee au module partage reste introuvable (ImportError).
import utils.vues_creation as _vues_creation_mod
reload(_vues_creation_mod)
from utils.vues_creation import (resolve_view_name, prepare_view_creation,
                                 verifier_template, apply_view_template)
_load_styles()

doc    = revit.doc
uidoc  = revit.uidoc
output = script.get_output()

# --- Contrôle de l'affichage des logs (config.json > activer_logs_scripts) ---
_LOG_ACTIF = False
_cfg_init  = {}
try:
    _cfg_init  = load_config()
    _LOG_ACTIF = bool(_cfg_init.get('activer_logs_scripts', False))
except Exception:
    pass

if not _LOG_ACTIF:
    try:
        output.close()
    except Exception:
        pass


def _log(msg):
    """Écrit dans le panneau pyRevit uniquement si les logs sont activés."""
    if _LOG_ACTIF:
        output.print_md(msg)


# Fichier de sauvegarde automatique (pyRevit appdata) : conserve la
# dernière configuration de colorisation utilisée d'une session à l'autre.
_LAST_CFG = script.get_data_file('last_colorisation', 'NM-Coloris-Pieces')
_CFG_EXT  = u'NM-Coloris-Pieces'


# ─── Constantes ────────────────────────────────────────────────────────────
MARQUEUR         = u"NM-BATII_PIECES_3D"
# Ancien marqueur (avant renommage "Volumétrie 3D" -> "Pièces 3D") : conservé
# uniquement pour que les volumes déjà créés dans des projets existants
# restent détectés/remplacés au prochain lancement, au lieu de devenir des
# doublons orphelins.
_MARQUEUR_ANCIEN = u"NM-BATII_VOLUMETRIE_PIECES"
CATEGORIE_ID     = DB.ElementId(DB.BuiltInCategory.OST_Mass)


def _get_tvp_row_pieces_3d(cfg):
    """
    Retourne la ligne de types_vues_personnalises désignée comme type
    "Pièces 3D" (case cochée dans Paramètres > onglet Vues > table
    "Vues personnalisées" > colonne "Disponibilité" > case "Pièces 3D"),
    ou None si aucune ligne n'est ainsi désignée.

    En pratique c'est toujours la ligne système "PIECES 3D" (Ord. 0) : la
    case est grisée sur toutes les autres lignes, et 01_Parametres assainit
    la config au chargement comme à l'enregistrement. La recherche reste
    faite par la case et non par le label, pour rester tolérante à une
    config ancienne et ne pas coder le label en dur ici.
    """
    for entry in cfg.get(u'dispo_types_pers_lier_cao', []):
        if entry.get(u'pieces_3d', False):
            return get_row_by_label(cfg, entry.get(u'label', u''))
    return None


def _get_vue_id_pieces_3d(cfg):
    """
    Retourne l'identifiant (ex. "vue-3d") de l'entrée de "Nommage des vues"
    désignée comme convention à utiliser pour les vues "Pièces 3D" (case
    cochée dans Paramètres > onglet Vues > table "Nommage des vues" >
    bouton "Disponibilite..." > colonne "Pièces 3D"), ou None si aucune
    entrée n'est ainsi désignée.

    Ne jamais coder en dur un identifiant de convention de nommage ici :
    c'est cette table de disponibilité qui indique au script quelle
    convention utiliser, afin qu'une future évolution de la table
    "Nommage des vues" (ex. renommage de l'entrée, ajout d'alternatives)
    reste utilisable par ce script sans modification de code.
    """
    nommage_vues = (cfg.get(u'conventions_nommage') or {}).get(u'nommage_vues', [])
    for entry in nommage_vues:
        if entry.get(u'pieces_3d', False):
            return entry.get(u'id') or None
    return None


# ─── Utilitaires pièces ──────────────────────────────────────────────────────
def _elem_name(e):
    """
    Nom d'un Element Revit (contournement IronPython : Element.Name est
    implémenté en interface explicite sur certains types, ce qui fait échouer
    l'accès direct e.Name).

    Délègue à l'implémentation PARTAGÉE. C'est ce même lecteur qui compare les
    noms de gabarits dans apply_view_template : deux lectures différentes du
    même nom finiraient par diverger — c'est précisément ce qui avait empêché
    l'application du gabarit ici.
    """
    return _vues_creation_mod.element_name(e)


def _is_placed_room(room):
    try:
        return room.Location is not None
    except Exception:
        return False


def room_phase_id(room):
    p = room.get_Parameter(DB.BuiltInParameter.ROOM_PHASE)
    return p.AsElementId() if p and p.HasValue else DB.ElementId.InvalidElementId


def collecter_pieces_placees(doc, phase_id):
    pieces = DB.FilteredElementCollector(doc)\
        .OfCategory(DB.BuiltInCategory.OST_Rooms)\
        .WhereElementIsNotElementType()\
        .ToElements()
    return [p for p in pieces
            if _is_placed_room(p) and room_phase_id(p) == phase_id]


def room_number(room):
    try:
        p = room.get_Parameter(DB.BuiltInParameter.ROOM_NUMBER)
        return p.AsString() if p else u''
    except Exception:
        return u''


def room_name(room):
    try:
        p = room.get_Parameter(DB.BuiltInParameter.ROOM_NAME)
        return p.AsString() if p else u''
    except Exception:
        return u''


def room_label(room):
    label = u"{} {}".format(room_number(room), room_name(room)).strip()
    return label if label else u"(pièce ID {})".format(room.Id.IntegerValue)


# ─── Paramètres de pièces : énumération et combinaison de valeurs ──────────
def _param_display_value(doc, p):
    if p is None or not p.HasValue:
        return u''
    st = p.StorageType
    if st == DB.StorageType.String:
        return p.AsString() or u''
    elif st == DB.StorageType.ElementId:
        try:
            eid = p.AsElementId()
        except Exception:
            eid = None
        if eid is None or eid == DB.ElementId.InvalidElementId:
            return u''
        elem = doc.GetElement(eid)
        if elem is None:
            return u''
        try:
            return _elem_name(elem) or u''
        except Exception:
            return u''
    elif st == DB.StorageType.Integer:
        return p.AsValueString() or unicode(p.AsInteger())
    elif st == DB.StorageType.Double:
        return p.AsValueString() or unicode(p.AsDouble())
    else:
        return p.AsValueString() or u''


def get_room_param_names(rooms):
    """Union, en ordre alphabétique, de tous les noms de paramètres des
    pièces (y compris les paramètres de projet)."""
    names = set()
    for r in rooms:
        try:
            for p in r.Parameters:
                try:
                    nm = p.Definition.Name
                    if nm:
                        names.add(nm)
                except Exception:
                    pass
        except Exception:
            pass
    return sorted(names)


def room_combo_value(doc, room, param_names):
    """Concatène les valeurs affichées des paramètres choisis, dans l'ordre,
    pour former la clé de regroupement/colorisation de la pièce."""
    parts = [_param_display_value(doc, room.LookupParameter(nm)) for nm in param_names]
    return u" | ".join(parts)


# ─── Purge des anciennes volumétries générées par cet outil ─────────────────
def prefixe_marqueur(phase_id, marqueur=MARQUEUR):
    return u"{}:{}:".format(marqueur, phase_id.IntegerValue)


def collecter_direct_shapes_existantes(doc, phase_id):
    # Reconnaît aussi l'ancien marqueur pour nettoyer les volumes créés avant
    # le renommage "Volumétrie 3D" -> "Pièces 3D" (cf. _MARQUEUR_ANCIEN).
    prefixes = (prefixe_marqueur(phase_id), prefixe_marqueur(phase_id, _MARQUEUR_ANCIEN))
    ds_list = DB.FilteredElementCollector(doc)\
        .OfClass(DB.DirectShape)\
        .WhereElementIsNotElementType()\
        .ToElements()
    result = []
    for ds in ds_list:
        p = ds.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        if p is not None and p.HasValue:
            valeur = p.AsString()
            if valeur and valeur.startswith(prefixes):
                result.append(ds)
    return result


# ─── Calcul et création de la géométrie 3D ──────────────────────────────────
def calculer_solide_piece(room, calculator):
    try:
        resultats = calculator.CalculateSpatialElementGeometry(room)
        solide = resultats.GetGeometry()
        if solide is None or solide.Volume <= 0:
            return None
        return solide
    except Exception:
        return None


def tesseller_solide(solide):
    """
    Le solide renvoyé par SpatialElementGeometryCalculator contient souvent
    des arêtes/faces quasi dégénérées (issues du calcul de volumétrie aux
    intersections de murs), que DirectShape.SetShape refuse tel quel, même
    après SolidUtils.Clone ("does not satisfy DirectShape validation
    criteria"). Solution robuste recommandée par l'API Revit : trianguler
    chaque face puis reconstruire la géométrie via TessellatedShapeBuilder
    (avec repli automatique en Mesh si un solide fermé ne peut pas être
    reconstruit).
    Retourne une liste de GeometryObject (Solid et/ou Mesh) prête pour
    DirectShape.SetShape, ou une liste vide en cas d'échec.
    """
    builder = DB.TessellatedShapeBuilder()
    builder.OpenConnectedFaceSet(True)
    for face in solide.Faces:
        mesh = face.Triangulate()
        if mesh is None:
            continue
        for i in range(mesh.NumTriangles):
            triangle = mesh.get_Triangle(i)
            pts = List[DB.XYZ]()
            pts.Add(triangle.get_Vertex(0))
            pts.Add(triangle.get_Vertex(1))
            pts.Add(triangle.get_Vertex(2))
            builder.AddFace(DB.TessellatedFace(pts, DB.ElementId.InvalidElementId))
    builder.CloseConnectedFaceSet()
    builder.Target = DB.TessellatedShapeBuilderTarget.AnyGeometry
    builder.Fallback = DB.TessellatedShapeBuilderFallback.Mesh
    builder.Build()
    resultat = builder.GetBuildResult()
    return list(resultat.GetGeometricalObjects())


def creer_direct_shape_piece(doc, room, solide, phase_id):
    geom_objs = tesseller_solide(solide)
    if not geom_objs:
        raise Exception(u"Géométrie triangulée vide")

    ds = DB.DirectShape.CreateElement(doc, CATEGORIE_ID)
    geoms = List[DB.GeometryObject]()
    for g in geom_objs:
        geoms.Add(g)
    ds.SetShape(geoms)

    try:
        ds.Name = u"Pièces 3D - {} - {}".format(room_number(room), room_name(room))
    except Exception:
        pass

    p = ds.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    if p is not None and not p.IsReadOnly:
        p.Set(u"{}{}".format(prefixe_marqueur(phase_id), room.UniqueId))

    # Le DirectShape est créé par défaut avec la phase courante du projet
    # (pas forcément celle de la pièce traitée) : on force ici la phase de
    # création à la phase traitée pour que le volume soit cohérent avec sa
    # pièce d'origine.
    p_phase = ds.get_Parameter(DB.BuiltInParameter.PHASE_CREATED)
    if p_phase is not None and not p_phase.IsReadOnly:
        p_phase.Set(phase_id)

    return ds


# ─── Vue 3D dédiée + gabarit de vue ──────────────────────────────────────────
def trouver_vue_par_nom(doc, nom):
    vues = DB.FilteredElementCollector(doc).OfClass(DB.View).ToElements()
    for v in vues:
        if not v.IsTemplate and _elem_name(v) == nom:
            return v
    return None


# La recherche du gabarit n'est PAS refaite ici : elle passe par
# utils.vues_creation.apply_view_template, exactement comme « Vues + » et
# « Lier CAO ». Deux implementations divergentes du meme rapprochement de nom
# finiraient par se contredire.


def obtenir_ou_creer_vue_3d(doc, nom, phase, vft_id, gabarit_nom):
    """
    Retourne (vue, creee, etat_type, gabarit_applique) : réutilise la vue 3D
    existante portant ce nom, ou en crée une nouvelle (vue 3D isométrique du
    type Revit résolu via le système de convention de nommage — cf.
    utils.vues_creation.prepare_view_creation). Lève une exception si un autre
    type de vue porte déjà ce nom (noms de vues uniques dans tout le projet
    Revit).

    Applique, dans le même ordre que create_view_element() utilisé par
    « Vues + » : la phase choisie, puis le gabarit de vue configuré — via la
    fonction PARTAGEE utils.vues_creation.apply_view_template, pour que les
    deux outils se comportent à l'identique.

    etat_type vaut :
      'cree'        vue neuve, créée directement au type configuré
      'conforme'    vue réutilisée, déjà au type configuré
      'reapplique'  vue réutilisée, son type a été corrigé
      'impossible'  vue réutilisée d'un autre type, que Revit refuse de changer

    Le type de vue configuré n'était appliqué qu'à la CREATION : modifier la
    colonne « Types de vues » des paramètres restait donc sans effet tant que
    la vue existait — seul le gabarit suivait. On le réapplique désormais sur
    une vue réutilisée, et le cas 'impossible' est remonté à l'utilisateur
    plutôt que d'échouer en silence (Revit n'expose pas de sélecteur de type
    pour les vues ; la faisabilité dépend de ce qu'autorise IsValidType).

    Le nom, lui, sert de clé de recherche : le changer produit une nouvelle
    vue, l'ancienne subsiste.
    """
    vue_existante = trouver_vue_par_nom(doc, nom)
    if vue_existante is not None:
        if not isinstance(vue_existante, DB.View3D):
            raise Exception(
                u"Une vue non-3D nommée « {} » existe déjà dans le projet.".format(nom))
        vue = vue_existante
        vue_creee = False
        etat_type = u'conforme'
        if vft_id is not None and vue.GetTypeId() != vft_id:
            etat_type = u'impossible'
            # IsValidType avant ChangeTypeId : sans ce garde-fou, un type
            # refuse leverait une exception qui ferait perdre tout le reste du
            # traitement (les volumes sont deja crees a ce stade).
            try:
                if vue.IsValidType(vft_id):
                    vue.ChangeTypeId(vft_id)
                    etat_type = u'reapplique'
            except Exception:
                etat_type = u'impossible'
    else:
        vue = DB.View3D.CreateIsometric(doc, vft_id)
        vue.Name = nom
        vue_creee = True
        etat_type = u'cree'

    p = vue.get_Parameter(DB.BuiltInParameter.VIEW_PHASE)
    if p is not None and not p.IsReadOnly:
        p.Set(phase.Id)

    gabarit_applique = apply_view_template(doc, vue, gabarit_nom)

    return vue, vue_creee, etat_type, gabarit_applique


# ─── Colorisation : motif de remplissage plein ──────────────────────────────
def _get_solid_fill_pattern_id(doc):
    fills = DB.FilteredElementCollector(doc).OfClass(DB.FillPatternElement).ToElements()
    model_solid = None
    other_solid = None
    for f in fills:
        try:
            pat = f.GetFillPattern()
        except Exception:
            continue
        if not pat.IsSolidFill:
            continue
        if pat.Target == DB.FillPatternTarget.Model:
            model_solid = f.Id
            break
        elif other_solid is None:
            other_solid = f.Id
    if model_solid is not None:
        return model_solid
    if other_solid is not None:
        return other_solid
    return DB.ElementId.InvalidElementId


# ─── Colorisation : sauvegarde / chargement de configuration ───────────────
def _json_default(obj):
    """
    Filet de securite pour json.dump : convertit les objets .NET que le module
    json d'IronPython ne reconnait pas comme des types Python natifs.

    Sans lui, l'enregistrement d'une configuration echouait avec un message du
    type "217 is not JSON serializable" : 217 est une composante de couleur
    (System.Byte), dont la representation ressemble a un entier mais que json
    refuse d'ecrire. Le cas se produisait apres un choix de couleur dans la
    palette Windows (voir _on_pick), seul chemin qui ne convertissait pas
    explicitement les composantes.
    """
    try:
        return int(obj)
    except Exception:
        pass
    try:
        return unicode(obj)
    except Exception:
        return str(obj)


def _config_to_dict(phase_name, selected, color_map):
    return {
        'phase': phase_name,
        'parametres': list(selected),
        'couleurs': dict((k, [int(c.Red), int(c.Green), int(c.Blue)]) for k, c in color_map.items()),
    }


def _dict_to_config(data):
    phase_name = data.get('phase', u'')
    selected = list(data.get('parametres', []))
    color_map = {}
    for k, rgb in data.get('couleurs', {}).items():
        try:
            color_map[k] = DB.Color(int(rgb[0]), int(rgb[1]), int(rgb[2]))
        except Exception:
            pass
    return phase_name, selected, color_map


def _auto_save_config(phase_name, selected, color_map):
    try:
        with codecs.open(_LAST_CFG, 'w', 'utf-8') as f:
            json.dump(_config_to_dict(phase_name, selected, color_map), f,
                      indent=2, ensure_ascii=False, default=_json_default)
    except Exception:
        pass


def _auto_load_config():
    if not os.path.isfile(_LAST_CFG):
        return None
    try:
        with codecs.open(_LAST_CFG, 'r', 'utf-8') as f:
            data = json.load(f)
        return _dict_to_config(data)
    except Exception:
        return None


def _save_config_to_file(phase_name, selected, color_map):
    dlg = SaveFileDialog()
    dlg.Title = u'Enregistrer la configuration de colorisation'
    dlg.Filter = u'Fichiers de colorisation (*.{0})|*.{0}'.format(_CFG_EXT)
    dlg.DefaultExt = _CFG_EXT
    dlg.FileName = u'colorisation_pieces.{}'.format(_CFG_EXT)
    if dlg.ShowDialog() != DialogResult.OK:
        return
    try:
        with codecs.open(dlg.FileName, 'w', 'utf-8') as f:
            json.dump(_config_to_dict(phase_name, selected, color_map), f,
                      indent=2, ensure_ascii=False, default=_json_default)
        show_alert(u"Colorisation", u"Configuration enregistrée :\n{}".format(dlg.FileName))
    except Exception as ex:
        show_alert(u"Erreur", u"Erreur d'écriture :\n{}".format(ex))


def _load_config_from_file():
    dlg = OpenFileDialog()
    dlg.Title = u'Charger une configuration de colorisation'
    dlg.Filter = u'Fichiers de colorisation (*.{0})|*.{0}'.format(_CFG_EXT)
    dlg.DefaultExt = _CFG_EXT
    if dlg.ShowDialog() != DialogResult.OK:
        return None
    if not dlg.FileName.lower().endswith(u'.' + _CFG_EXT.lower()):
        show_alert(u"Format incorrect",
                  u"Seuls les fichiers « .{} » sont acceptés.".format(_CFG_EXT))
        return None
    try:
        with codecs.open(dlg.FileName, 'r', 'utf-8') as f:
            data = json.load(f)
        return _dict_to_config(data)
    except Exception as ex:
        show_alert(u"Erreur", u"Erreur de lecture :\n{}".format(ex))
        return None


# ─── Interface : phase + combinaison de paramètres + couleurs ──────────────
def show_colorisation_dialog(doc):
    """
    Fenêtre unique affichée avant toute création : choix de la phase,
    construction d'une combinaison ordonnée de paramètres de pièces (liste
    double avec boutons de transfert), génération du tableau des valeurs
    distinctes produites par cette combinaison, et choix d'une couleur par
    valeur. Retourne (phase, param_combo, color_map) où param_combo est la
    liste ordonnée des noms de paramètres choisis (peut être vide : dans ce
    cas aucune colorisation n'est appliquée) et color_map associe une valeur
    de combinaison (unicode) à un DB.Color. Retourne None si l'utilisateur
    annule.
    """
    # Ordre inverse demandé (phase la plus récente en tête de liste).
    phases = list(reversed(list(doc.Phases)))
    if not phases:
        raise Exception(u"Aucune phase définie dans le projet.")

    xaml_path = os.path.join(os.path.dirname(__file__), 'ColorisationDialog.xaml')
    wpf = forms.WPFWindow(xaml_path)

    phase_names = [_elem_name(ph) for ph in phases]
    for nm in phase_names:
        wpf.cmbPhase.Items.Add(nm)

    available = []
    selected = []
    color_map = {}

    def _current_phase():
        idx = wpf.cmbPhase.SelectedIndex
        if idx < 0:
            return None
        return phases[idx]

    def _refresh_listboxes():
        wpf.lstAvailable.Items.Clear()
        for nm in available:
            wpf.lstAvailable.Items.Add(nm)
        wpf.lstSelected.Items.Clear()
        for nm in selected:
            wpf.lstSelected.Items.Add(nm)

    def _clear_values_table():
        color_map.clear()
        wpf.valuesPanel.Children.Clear()
        wpf.txtValuesCount.Text = u"(0 valeur générée)"

    def _reset_params_for_phase():
        available[:] = []
        selected[:] = []
        _clear_values_table()
        phase = _current_phase()
        if phase is None:
            _refresh_listboxes()
            return
        pieces = collecter_pieces_placees(doc, phase.Id)
        available[:] = get_room_param_names(pieces)
        _refresh_listboxes()

    def _on_phase_changed(s, e):
        _reset_params_for_phase()

    wpf.cmbPhase.SelectionChanged += _on_phase_changed

    def _on_add(s, e):
        chosen = list(wpf.lstAvailable.SelectedItems)
        for nm in chosen:
            if nm in available:
                available.remove(nm)
            if nm not in selected:
                selected.append(nm)
        _refresh_listboxes()
        _clear_values_table()

    def _on_remove(s, e):
        chosen = list(wpf.lstSelected.SelectedItems)
        for nm in chosen:
            if nm in selected:
                selected.remove(nm)
            if nm not in available:
                available.append(nm)
        available.sort()
        _refresh_listboxes()
        _clear_values_table()

    def _on_up(s, e):
        idx = wpf.lstSelected.SelectedIndex
        if idx > 0:
            selected[idx - 1], selected[idx] = selected[idx], selected[idx - 1]
            _refresh_listboxes()
            wpf.lstSelected.SelectedIndex = idx - 1
            _clear_values_table()

    def _on_down(s, e):
        idx = wpf.lstSelected.SelectedIndex
        if 0 <= idx < len(selected) - 1:
            selected[idx + 1], selected[idx] = selected[idx], selected[idx + 1]
            _refresh_listboxes()
            wpf.lstSelected.SelectedIndex = idx + 1
            _clear_values_table()

    wpf.btnAdd.Click    += _on_add
    wpf.btnRemove.Click += _on_remove
    wpf.btnUp.Click     += _on_up
    wpf.btnDown.Click   += _on_down

    def _brush_from_db_color(c):
        return SolidColorBrush(WpfColor.FromRgb(c.Red, c.Green, c.Blue))

    def _default_color_for_index(i, total):
        """Couleur par défaut distincte pour chaque valeur générée (teinte
        répartie sur le cercle chromatique, saturation et luminosité fixées
        pour exclure les gris, le noir et le blanc)."""
        hue = (float(i) / float(total)) if total > 0 else 0.0
        r, g, b = colorsys.hsv_to_rgb(hue, 0.65, 0.85)
        return DB.Color(int(round(r * 255)), int(round(g * 255)), int(round(b * 255)))

    def _add_value_row(key, count):
        row = Grid()
        c0 = ColumnDefinition(); c0.Width = GridLength(1, GridUnitType.Star)
        c1 = ColumnDefinition(); c1.Width = GridLength(60)
        c2 = ColumnDefinition(); c2.Width = GridLength(150)
        row.ColumnDefinitions.Add(c0)
        row.ColumnDefinitions.Add(c1)
        row.ColumnDefinitions.Add(c2)
        row.Margin = Thickness(2)

        tb = TextBlock()
        tb.Text = u"{}  —  {} pièce(s)".format(key if key else u"(vide)", count)
        tb.VerticalAlignment = VerticalAlignment.Center
        tb.TextWrapping = TextWrapping.Wrap
        Grid.SetColumn(tb, 0)

        swatch = Border()
        swatch.Width = 40
        swatch.Height = 20
        swatch.BorderThickness = Thickness(1)
        swatch.BorderBrush = Brushes.Gray
        existing = color_map.get(key)
        swatch.Background = _brush_from_db_color(existing) if existing is not None else Brushes.LightGray
        Grid.SetColumn(swatch, 1)

        btn = Button()
        btn.Content = u"Choisir couleur..."
        btn.Padding = Thickness(6, 2, 6, 2)
        Grid.SetColumn(btn, 2)

        def _on_pick(sender, args, k=key, sw=swatch):
            cd = ColorDialog()
            cur = color_map.get(k)
            if cur is not None:
                cd.Color = System.Drawing.Color.FromArgb(cur.Red, cur.Green, cur.Blue)
            if cd.ShowDialog() == DialogResult.OK:
                c = cd.Color
                # int() explicite : c.R/G/B sont des System.Byte (couleur issue
                # de la palette Windows). Sans conversion, ces octets se
                # retrouvaient tels quels dans color_map, puis dans json.dump
                # qui les rejetait ("217 is not JSON serializable").
                # Les deux autres points de peuplement de color_map
                # (_dict_to_config et _default_color_for_index) convertissent
                # deja, d'ou un bug limite aux couleurs choisies a la palette.
                color_map[k] = DB.Color(int(c.R), int(c.G), int(c.B))
                sw.Background = SolidColorBrush(WpfColor.FromRgb(c.R, c.G, c.B))

        btn.Click += _on_pick

        row.Children.Add(tb)
        row.Children.Add(swatch)
        row.Children.Add(btn)
        wpf.valuesPanel.Children.Add(row)

    def _generate_values():
        phase = _current_phase()
        if phase is None or not selected:
            return
        pieces = collecter_pieces_placees(doc, phase.Id)
        combos = {}
        for room in pieces:
            key = room_combo_value(doc, room, selected)
            combos[key] = combos.get(key, 0) + 1
        ordered_keys = sorted(combos.keys())
        total = len(ordered_keys)
        for i, key in enumerate(ordered_keys):
            if key not in color_map:
                color_map[key] = _default_color_for_index(i, total)
        wpf.valuesPanel.Children.Clear()
        for key in ordered_keys:
            _add_value_row(key, combos[key])
        wpf.txtValuesCount.Text = u"({} valeur(s) générée(s))".format(total)

    def _on_generer(s, e):
        if not selected:
            show_alert(u"Colorisation",
                       u"Sélectionnez au moins un paramètre (colonne de droite) "
                       u"avant de générer les valeurs.")
            return
        _generate_values()

    wpf.btnGenerer.Click += _on_generer

    def _apply_loaded_config(cfg):
        """
        Applique une configuration (phase + combinaison de paramètres +
        couleurs) chargée automatiquement ou depuis un fichier. Si cfg est
        None, ou que sa phase n'existe plus dans le projet, sélectionne
        simplement la première phase de la liste (déjà en ordre inverse).
        """
        if cfg is not None and cfg[0] in phase_names:
            idx = phase_names.index(cfg[0])
        else:
            idx = 0
        if wpf.cmbPhase.SelectedIndex == idx:
            _reset_params_for_phase()
        else:
            wpf.cmbPhase.SelectedIndex = idx  # déclenche _on_phase_changed

        if cfg is not None:
            _, saved_selected, saved_colors = cfg
            for nm in saved_selected:
                if nm in available:
                    available.remove(nm)
                    selected.append(nm)
            available.sort()
            _refresh_listboxes()
            color_map.update(saved_colors)
            if selected:
                _generate_values()

    def _on_load_config(s, e):
        cfg = _load_config_from_file()
        if cfg is not None:
            _apply_loaded_config(cfg)

    def _on_save_config(s, e):
        phase = _current_phase()
        phase_name = _elem_name(phase) if phase is not None else u''
        _save_config_to_file(phase_name, selected, color_map)

    wpf.btnLoadConfig.Click += _on_load_config
    wpf.btnSaveConfig.Click += _on_save_config

    # Restaure la dernière configuration utilisée (session précédente),
    # sinon sélectionne simplement la première phase de la liste.
    _apply_loaded_config(_auto_load_config())

    result = {'ok': False}

    def _on_apply(s, e):
        if _current_phase() is None:
            show_alert(u"Colorisation", u"Sélectionnez une phase.")
            return
        result['ok'] = True
        wpf.Close()

    wpf.btnApply.Click  += _on_apply
    wpf.btnCancel.Click += lambda s, e: wpf.Close()

    frame = Threading.DispatcherFrame()

    def _on_window_closed(s, e):
        phase = _current_phase()
        phase_name = _elem_name(phase) if phase is not None else u''
        _auto_save_config(phase_name, selected, color_map)
        frame.Continue = False

    wpf.Closed += _on_window_closed
    wpf.Show()
    Threading.Dispatcher.PushFrame(frame)

    if not result['ok']:
        return None

    phase = _current_phase()
    return phase, list(selected), dict(color_map)


# ─── Corps principal ─────────────────────────────────────────────────────────
try:
    tvp_row_p3d = _get_tvp_row_pieces_3d(_cfg_init)
    vue_id_p3d  = _get_vue_id_pieces_3d(_cfg_init)
    if tvp_row_p3d is None or vue_id_p3d is None:
        _manque = []
        if vue_id_p3d is None:
            _manque.append(
                u"- onglet « Vues » > table « Nommage des vues » > bouton "
                u"« Disponibilite... » : cochez la colonne « Pièces 3D » pour "
                u"« Vue 3D »."
            )
        if tvp_row_p3d is None:
            _manque.append(
                u"- onglet « Vues » > table « Vues personnalisées » > ligne "
                u"« PIECES 3D » (Ord. 0) > colonne « Disponibilité » : cochez "
                u"« Pièces 3D ». Cette case est réservée à cette ligne, elle "
                u"est grisée sur les autres."
            )
        show_alert(
            u"Pièces 3D",
            u"La création de la vue « Pièces 3D » n'est pas (entièrement) "
            u"configurée.\n\n"
            u"Rendez-vous dans NM-BATII.tab > 01_Parametres.panel > "
            u"Paramètres :\n\n" + u"\n".join(_manque)
        )
        script.exit()

    config = show_colorisation_dialog(doc)
    if config is None:
        script.exit()
    phase, param_combo, color_map = config
    nom_phase = _elem_name(phase)

    pieces = collecter_pieces_placees(doc, phase.Id)
    if not pieces:
        show_alert(u"Pièces 3D",
                   u"Aucune pièce placée trouvée pour la phase « {} ».".format(nom_phase))
        script.exit()

    msg_confirm = (
        u"**{} pièce(s)** trouvée(s) pour la phase **« {} »**.\n\n"
        u"Leurs volumes 3D vont être **recréés** (les anciens volumes de "
        u"cette phase sont automatiquement supprimés).\n\n"
        u"Rappel : activez « Afficher les catégories de masse » pour voir "
        u"le résultat dans les vues."
    ).format(len(pieces), nom_phase)
    if param_combo and color_map:
        msg_confirm += (
            u"\n\n**{} couleur(s)** seront appliquées selon la combinaison "
            u"de paramètres choisie."
        ).format(len(color_map))

    # Styles et largeur laisses par defaut : show_confirm() applique desormais
    # le pied de dialogue standard (NMButtonAppliquer / NMButtonAnnuler, 130).
    if not show_confirm(u"Pièces 3D", msg_confirm,
                         yes_label=u"▶  Appliquer", no_label=u"Annuler"):
        script.exit()

    # Garde-fou : un jeton inconnu dans le template serait recopie tel quel
    # dans le nom de la vue 3D creee.
    _tpl_ok, _tpl_msg = verifier_template(_cfg_init, vue_id_p3d)
    if not _tpl_ok:
        show_alert(u"Convention de nommage invalide", _tpl_msg)
        script.exit()

    # Résolution du type de vue Revit et du gabarit "Pièces 3D" via le même
    # système de convention de nommage que "01_Vues_+" / "01_Lier_CAO" — doit
    # être fait hors Transaction (peut en ouvrir une propre pour dupliquer un
    # type de vue si celui-ci est absent du projet).
    vft_id_3d, nom_gabarit_3d = prepare_view_creation(
        doc, DB.ViewFamily.ThreeDimensional, tvp_row_p3d, _cfg_init, vue_id=vue_id_p3d)
    # Nom du type configuré, pour le rapport uniquement.
    _type_vue_3d_nom = get_type_for_vue_id(_cfg_init, tvp_row_p3d.get(u'label', u''),
                                           vue_id_p3d)

    _vars_p3d = get_template_vars(tvp_row_p3d)
    _vars_p3d[u'phase'] = nom_phase
    nom_vue_3d = resolve_view_name(
        DB.ViewFamily.ThreeDimensional, _vars_p3d, _cfg_init, vue_id=vue_id_p3d).strip()
    if not nom_vue_3d:
        nom_vue_3d = nom_phase

    # Gabarit configuré mais absent du projet : proposer une substitution.
    # Fait AVANT la Transaction — ouvrir une fenêtre modale alors qu'une
    # transaction Revit est ouverte laisserait le modèle verrouillé pendant
    # tout le temps de réflexion de l'utilisateur.
    _gabarit_substitue = False
    _gabarit_configure = nom_gabarit_3d
    if nom_gabarit_3d:
        _tpls_projet = _vues_creation_mod.get_view_templates(doc)
        _noms_tpl = [_elem_name(_t) for _t in _tpls_projet]
        if nom_gabarit_3d not in _noms_tpl:
            if not _noms_tpl:
                show_alert(
                    u"Pièces 3D — gabarit de vue introuvable",
                    u"Le gabarit « {} » configuré dans 01_Paramètres > Vues > "
                    u"Vues personnalisées > Gabarits de vues (ligne « Vue 3D ») "
                    u"n'existe pas dans ce projet, qui ne contient d'ailleurs "
                    u"aucun gabarit de vue.\n\n"
                    u"La vue 3D sera créée sans gabarit.".format(nom_gabarit_3d))
                nom_gabarit_3d = u''
            else:
                # Filtre de compatibilité, comme dans « Vues + » et
                # « Lier CAO » : la comparaison porte sur le NOM
                # D'ENUMERATION Revit, la traduction française n'intervient
                # qu'à l'affichage.
                _vt_attendu = _vues_creation_mod.VUE_ID_TO_VIEWTYPE.get(
                    vue_id_p3d)
                _lbl_fam = (_vues_creation_mod.libelle_view_type(
                    _cfg_init, _vt_attendu) if _vt_attendu else u'')
                # Libellés français de « Nommage des vues » plutôt que les
                # noms d'énumération Revit (ThreeD, DraftingView…).
                _fr = lambda _lst: [
                    (_elem_name(_t),
                     _vues_creation_mod.libelle_view_type(
                         _cfg_init, _t.ViewType.ToString()))
                    for _t in _lst]
                _compat = ([_t for _t in _tpls_projet
                            if _t.ViewType.ToString() == _vt_attendu]
                           if _vt_attendu else None)
                _choix_tpl = choisir_dans_liste(
                    titre=u"Gabarit de vue introuvable — Pièces 3D",
                    description=(
                        u"Sélectionnez le gabarit à appliquer à la vue 3D "
                        u"« {} », ou annulez pour la créer sans gabarit.".format(
                            nom_vue_3d)),
                    note=(u"Le gabarit « {} » configuré dans 01_Paramètres > "
                          u"Vues > Vues personnalisées > Gabarits de vues "
                          u"(ligne « Vue 3D ») n'existe pas dans ce "
                          u"projet.".format(nom_gabarit_3d)),
                    entete_nom=u"Gabarit de vue",
                    entete_info=u"Type de vue",
                    items_tous=_fr(_tpls_projet),
                    items_compat=(_fr(_compat) if _compat is not None
                                  else None),
                    libelle_compat=(
                        u"Uniquement les gabarits compatibles avec "
                        u"« {} »".format(_lbl_fam)),
                    valeur_courante=u'')
                # Substitution valable pour CETTE exécution seulement : la
                # configuration n'est pas réécrite ici (seul 01_Paramètres
                # écrit config.json). Le rapport final le rappelle.
                nom_gabarit_3d = _choix_tpl or u''
                _gabarit_substitue = bool(_choix_tpl)

    n_ok = 0
    n_skip = 0
    n_supprimees = 0
    n_colorisees = 0
    pieces_ignorees = []
    ids_creees = []
    ds_combo_key = {}
    vue_3d = None
    vue_creee = False
    gabarit_applique = False
    etat_type = None
    erreur_vue = None

    with revit.Transaction(u"NM-BATII : Pièces 3D"):
        anciennes = collecter_direct_shapes_existantes(doc, phase.Id)
        for ds in anciennes:
            doc.Delete(ds.Id)
        n_supprimees = len(anciennes)

        calculator = DB.SpatialElementGeometryCalculator(doc)
        for room in pieces:
            solide = calculer_solide_piece(room, calculator)
            if solide is None:
                n_skip += 1
                pieces_ignorees.append(room_label(room))
                continue
            try:
                ds = creer_direct_shape_piece(doc, room, solide, phase.Id)
                ids_creees.append(ds.Id)
                if param_combo:
                    ds_combo_key[ds.Id] = room_combo_value(doc, room, param_combo)
                n_ok += 1
            except Exception:
                n_skip += 1
                pieces_ignorees.append(room_label(room))

        try:
            vue_3d, vue_creee, etat_type, gabarit_applique = (
                obtenir_ou_creer_vue_3d(doc, nom_vue_3d, phase, vft_id_3d,
                                        nom_gabarit_3d))
        except Exception as e:
            erreur_vue = str(e)

        if vue_3d is not None and param_combo and color_map:
            solid_fill_id = _get_solid_fill_pattern_id(doc)
            for ds_id, key in ds_combo_key.items():
                couleur = color_map.get(key)
                if couleur is None:
                    continue
                ogs = DB.OverrideGraphicSettings()
                if solid_fill_id != DB.ElementId.InvalidElementId:
                    ogs.SetSurfaceForegroundPatternId(solid_fill_id)
                    ogs.SetSurfaceForegroundPatternColor(couleur)
                    ogs.SetCutForegroundPatternId(solid_fill_id)
                    ogs.SetCutForegroundPatternColor(couleur)
                ogs.SetProjectionLineColor(couleur)
                ogs.SetCutLineColor(couleur)
                vue_3d.SetElementOverrides(ds_id, ogs)
                n_colorisees += 1

    if vue_3d is not None:
        # Gabarit de substitution retenu : rappeler que le remplacement ne vaut
        # que pour cette execution, la configuration n'ayant pas ete reecrite.
        if _gabarit_substitue and gabarit_applique:
            show_alert(
                u"Pièces 3D — gabarit de substitution appliqué",
                u"Le gabarit « {} » a été appliqué à la vue « {} » à la place "
                u"de « {} », introuvable dans ce projet.\n\n"
                u"Ce remplacement vaut pour cette exécution seulement. Pour le "
                u"rendre permanent, corrigez-le dans 01_Paramètres > Vues > "
                u"Vues personnalisées > Gabarits de vues, ligne "
                u"« Vue 3D ».".format(
                    nom_gabarit_3d, nom_vue_3d, _gabarit_configure))
        # Gabarit demande mais refuse par Revit (cas residuel : le gabarit
        # existe mais ne s'applique pas a une vue 3D). Le log est muet quand
        # activer_logs_scripts est a false, d'ou la boite de message.
        elif nom_gabarit_3d and not gabarit_applique:
            show_alert(
                u"Pièces 3D — gabarit de vue non appliqué",
                u"Le gabarit « {} » existe dans le projet mais Revit a refusé "
                u"de l'appliquer à la vue « {} ».\n\n"
                u"Vérifiez qu'il s'agit bien d'un gabarit de vue 3D : un "
                u"gabarit ne s'applique qu'aux vues de sa propre famille."
                .format(nom_gabarit_3d, nom_vue_3d))
        # Le type configure n'a pas pu etre pose sur la vue existante : c'est
        # actionnable par l'utilisateur (supprimer la vue), donc visible meme
        # quand les logs de script sont desactives.
        if etat_type == u'impossible':
            show_alert(
                u"Pièces 3D — type de vue non appliqué",
                u"La vue « {} » existe déjà et n'est pas du type de vue "
                u"« {} » configuré dans 01_Paramètres > Vues > Vues "
                u"personnalisées > Types de vues.\n\n"
                u"Revit ne permet pas de changer le type d'une vue existante. "
                u"Supprimez cette vue puis relancez « Pièces 3D » : elle sera "
                u"recréée au bon type.\n\n"
                u"Le reste de la configuration (nom, gabarit, phase) a bien "
                u"été appliqué.".format(
                    nom_vue_3d,
                    _type_vue_3d_nom or u"(type par défaut de la famille)"))
        try:
            uidoc.ActiveView = vue_3d
        except Exception:
            pass
    elif erreur_vue:
        # Erreur non bloquante (les volumes ont bien été créés) mais qui doit
        # être visible même si les logs de script sont désactivés.
        show_alert(
            u"Pièces 3D",
            u"Les volumes ont été créés, mais la vue 3D dédiée n'a pas pu "
            u"être créée/réutilisée :\n\n{}".format(erreur_vue)
        )

    _log(u"## NM-BATII — Pièces 3D\n")
    _log(u"- Phase : **{}**".format(nom_phase))
    _log(u"- Anciennes géométries supprimées : **{}**".format(n_supprimees))
    _log(u"- Pièces traitées : **{}**".format(n_ok))
    _log(u"- Pièces ignorées (volume introuvable, pièce non fermée) : **{}**".format(n_skip))
    if pieces_ignorees:
        _log(u"\n**Pièces ignorées :**\n")
        for label in pieces_ignorees:
            _log(u"- {}".format(label))

    if param_combo:
        _log(u"\n### Colorisation\n")
        _log(u"- Combinaison de paramètres : **{}**".format(u" | ".join(param_combo)))
        _log(u"- Volumes colorisés : **{}**".format(n_colorisees))

    _log(u"\n### Vue 3D\n")
    if erreur_vue:
        _log(u"- **Erreur** : {}".format(erreur_vue))
    else:
        _log(u"- Vue « {} » : **{}**".format(
            nom_vue_3d, u"créée" if vue_creee else u"réutilisée"))
        _nom_type_aff = _type_vue_3d_nom or u"(type par défaut de la famille)"
        if etat_type == u'cree':
            _log(u"- Type de vue « {} » appliqué.".format(_nom_type_aff))
        elif etat_type == u'conforme':
            _log(u"- Type de vue « {} » : déjà conforme.".format(_nom_type_aff))
        elif etat_type == u'reapplique':
            _log(u"- Type de vue « {} » réappliqué à la vue existante.".format(
                _nom_type_aff))
        elif etat_type == u'impossible':
            _log(
                u"- **Avertissement** : la vue existante n'est pas du type "
                u"« {} » et Revit refuse d'en changer le type après coup. "
                u"Supprimez la vue « {} » puis relancez : elle sera recréée "
                u"au bon type.".format(_nom_type_aff, nom_vue_3d))
        if gabarit_applique:
            _log(u"- Gabarit « {} » appliqué.".format(nom_gabarit_3d))
        elif not nom_gabarit_3d:
            _log(
                u"- Aucun gabarit configuré pour ce type (table « Gabarits "
                u"de vues », entrée « Vue 3D ») : vue créée/réutilisée sans "
                u"gabarit appliqué."
            )
        else:
            _log(
                u"- **Avertissement** : gabarit « {} » introuvable dans le "
                u"projet, la vue a été créée/réutilisée sans gabarit "
                u"appliqué.".format(nom_gabarit_3d))

except Exception as e:
    show_alert(u"Erreur NM-BATII", unicode(e))
    script.exit()
