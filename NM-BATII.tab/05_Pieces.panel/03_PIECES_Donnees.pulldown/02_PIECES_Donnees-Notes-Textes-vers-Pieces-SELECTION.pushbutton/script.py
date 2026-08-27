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


#__title__ = "Texte → Pièces\n[SELECTION]"
#__doc__ = """Transfère les valeurs des notes textuelles
#Description : Transfère les valeurs des notes textuelles sélectionnées dans la vue vers un paramètre cible des pièces qui les contiennent.

#Version : 3.3 — 2026-04-17
#Auteur : data8bim (d8b)
#"""


# ─── FENÊTRE PRINCIPALE NON MODALE ────────────────────────────────────────────
# Le sélecteur de paramètre (ParamDialog) est affiché via Show() : l'utilisateur
# peut naviguer dans Revit fenêtre ouverte. Au clic « Sélectionner les notes »,
# la fenêtre se MASQUE (pour laisser le focus à Revit), la sélection interactive
# (PickObjects) + la copie (transaction) s'exécutent via un ExternalEvent (thread
# Revit, contexte API valide), puis la fenêtre se RÉAFFICHE pour enchaîner un
# nouveau traitement. Pour arrêter : Annuler / fermer le sélecteur.
#
# Contrainte technique — cf [[palette-non-modale-globals-ironpython]] : après le
# retour de Execute(), IronPython/pyRevit VIDE les globals du module. Tout ce
# qu'un callback (on_ok, _run_copy) utilise doit donc être un attribut d'instance
# ou un import fait EN LOCAL. Le handler ExternalEvent REMONTE ses erreurs (pas
# de « except: pass » silencieux — c'est ce qui masquait l'échec auparavant).

import clr, os, sys
from pyrevit import revit, forms, script
from pyrevit.forms import WPFWindow

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    BuiltInCategory,
    BuiltInParameter,
    StorageType,
    TextNote,
    XYZ,
    ViewPlan
)
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException

doc    = revit.doc
uidoc  = revit.uidoc
MARKER = u"✔ "

# -----------------------------------------------------------------------------
# Chargement des styles WPF (fournit aussi show_alert) — AVANT les gardes.
# -----------------------------------------------------------------------------
script_dir = os.path.dirname(__file__)
lib_dir    = os.path.abspath(os.path.join(script_dir, "..", "..", "..", "lib"))
if lib_dir not in sys.path:
    sys.path.append(lib_dir)

from dialogs.dialogs_styles_loader import load as load_styles, show_alert
load_styles(lib_dir=lib_dir)

# -----------------------------------------------------------------------------
# 1) Vérifier qu'on est dans une vue en plan et récupérer son niveau.
# -----------------------------------------------------------------------------
view = doc.ActiveView
if not isinstance(view, ViewPlan):
    show_alert(u"Information", "Ouvrez d'abord une vue en plan (étage ou plafond).")
    script.exit()

level = view.GenLevel
if not level:
    show_alert(u"Information", "Impossible de récupérer le niveau associé à la vue.")
    script.exit()

# ProjectElevation = Z interne Revit (repère origine projet). NE PAS utiliser
# level.Elevation : c'est la valeur UI, relative à la base d'élévation du niveau
# (point de base projet / point topo). Dès qu'elle est non nulle, le point de
# sonde tombe hors de toutes les pièces et GetRoomAtPoint renvoie None partout.
# +0.1 ft : petit déport vers le haut pour être franchement dans le volume.
view_level = level.ProjectElevation + 0.1

# Phase de la vue active : GetRoomAtPoint sans phase utilise la dernière phase du
# projet, ce qui rate les pièces d'une autre phase.
_php = view.get_Parameter(BuiltInParameter.VIEW_PHASE)
view_phase_id = _php.AsElementId() if _php else None


# -----------------------------------------------------------------------------
# Fenetre modeless : parentage Win32 + ExternalEvent pour les ecritures Revit
# -----------------------------------------------------------------------------
def _set_revit_owner(window):
    """Attache la fenetre WPF comme enfant Win32 de la fenetre principale Revit
    (reste au-dessus de Revit et se ferme avec lui)."""
    try:
        from System.Windows.Interop import WindowInteropHelper
        from pyrevit import HOST_APP as _HOST
        WindowInteropHelper(window).Owner = _HOST.uiapp.MainWindowHandle
    except Exception:
        pass


# PickObjects et la transaction doivent s'executer dans un contexte API Revit
# valide : depuis le thread WPF d'une fenetre non modale c'est impossible, on
# planifie le travail dans un ExternalEvent execute sur le thread Revit.
class _ActionHandler(IExternalEventHandler):
    def __init__(self):
        self._fn = [None]   # mutable — pas de nonlocal en IronPython 2.7

    def planifier(self, fn):
        self._fn[0] = fn

    def Execute(self, uiapp):
        fn = self._fn[0]
        self._fn[0] = None
        if fn:
            try:
                fn()
            except Exception:
                # Ne JAMAIS avaler en silence (cf memoire) : remonter la cause.
                import traceback
                try:
                    import System.Windows as _SW
                    _SW.MessageBox.Show(traceback.format_exc(),
                                        u'NM-BATII — Erreur')
                except Exception:
                    pass

    def GetName(self):
        return u"NM-BATII — Copie note textuelle vers parametre"


_action_handler = _ActionHandler()
_ext_event      = ExternalEvent.Create(_action_handler)

# -----------------------------------------------------------------------------
# 3) Dernier paramètre choisi (relu à chaque ouverture de sélecteur, voir __init__)
# -----------------------------------------------------------------------------
settings_file = os.path.join(script_dir, "last_param.txt")


def _lire_dernier_param():
    try:
        with open(settings_file, "r") as f:
            return f.read().strip()
    except:
        return None


# -----------------------------------------------------------------------------
# 4) Récupérer les paramètres string d'instance des pièces (setup)
# -----------------------------------------------------------------------------
def get_room_text_params():
    rooms = (
        FilteredElementCollector(doc)
        .OfCategory(BuiltInCategory.OST_Rooms)
        .WhereElementIsNotElementType()
        .ToElements()
    )
    if not rooms:
        show_alert(u"Information", "Aucune pièce trouvée.")
        script.exit()

    sample = rooms[0]
    return sorted({
        p.Definition.Name
        for p in sample.Parameters
        if not p.IsReadOnly and p.StorageType == StorageType.String
    })


# -----------------------------------------------------------------------------
# 6) Filtre de sélection : Notes Textuelles
# -----------------------------------------------------------------------------
class TextNoteFilter(object, ISelectionFilter):
    # AllowElement est appelé par Revit PENDANT PickObjects, donc depuis
    # l'ExternalEvent, APRÈS le vidage des globals : « TextNote » doit être
    # ré-importé EN LOCAL, sinon NameError → plus aucun élément n'est
    # sélectionnable à la souris (échec silencieux côté Revit).
    def AllowElement(self, element):
        from Autodesk.Revit.DB import TextNote
        return isinstance(element, TextNote)
    def AllowReference(self, reference, point):
        return False


# -----------------------------------------------------------------------------
# 7) Fenêtre de résultat (méthodes n'utilisant que self / args : callback-safe)
# -----------------------------------------------------------------------------
class ResultWindow(WPFWindow):
    def __init__(self, xaml_file, message):
        # Cette fenêtre est construite DEPUIS un callback (ExternalEvent), après
        # le vidage des globals : « super(ResultWindow, self) » lèverait
        # NameError car le nom de la classe est lui-même un global du module.
        # On appelle la classe de base explicitement, ré-importée en local.
        from pyrevit.forms import WPFWindow as _WPFWindow
        _WPFWindow.__init__(self, xaml_file)
        self.txtMessage.Text = message
        self.btnClose.Click += self.on_close
        self.KeyDown += self.on_key

    def on_close(self, sender, args):
        self.Close()

    def on_key(self, sender, args):
        key = args.Key.ToString()
        if key in ["Escape", "Enter", "Return"]:
            self.Close()


# -----------------------------------------------------------------------------
# 5) Sélecteur de paramètre — NON MODAL. Reste ouvert entre les traitements
#    (masqué pendant la sélection dans Revit, puis réaffiché). Tout ce dont les
#    callbacks ont besoin est résolu ICI (globals vivants) et porté par l'instance.
# -----------------------------------------------------------------------------
class ParamDialog(WPFWindow):
    def __init__(self, xaml_file):
        super(ParamDialog, self).__init__(xaml_file)

        self._doc            = doc
        self._uidoc          = uidoc
        self._view_level     = view_level
        self._view_phase_id  = view_phase_id
        self._MARKER         = MARKER
        self._settings_file  = settings_file
        self._action_handler = _action_handler
        self._ext_event      = _ext_event
        self._sel_filter     = TextNoteFilter()
        self._ResultWindow   = ResultWindow
        self._result_xaml    = script.get_bundle_file("ResultWindow.xaml")

        params = get_room_text_params()
        self.ParamSelector.ItemsSource = params
        last_param = _lire_dernier_param()
        if last_param in params:
            self.ParamSelector.SelectedItem = last_param
        self.SelectNotesButton.Click += self.on_ok
        self.CancelButton.Click      += self.on_cancel
        self.selected_param = None

    def on_ok(self, sender, args):
        from dialogs.dialogs_styles_loader import show_alert
        param = self.ParamSelector.SelectedItem
        if not param:
            show_alert(u"Information", "Veuillez choisir un paramètre.")
            return
        self.selected_param = param
        try:
            with open(self._settings_file, "w") as f:
                f.write(param)
        except:
            pass
        # Masquer le sélecteur pour laisser le focus à Revit (PickObjects), puis
        # planifier pick + copie dans l'ExternalEvent (contexte API valide).
        self.Hide()

        def _do():
            self._run_copy(param)

        self._action_handler.planifier(_do)
        self._ext_event.Raise()

    def on_cancel(self, sender, args):
        self.Close()

    def _show_result(self, msg):
        rw = self._ResultWindow(self._result_xaml, msg)
        rw.ShowDialog()

    def _run_copy(self, param_name):
        """Étapes B→E exécutées sur le thread Revit (ExternalEvent) : sélection
        interactive des notes, regroupement par pièce, copie, résultat. Le
        sélecteur est réaffiché à la fin (quoi qu'il arrive) pour un nouveau tour."""
        from Autodesk.Revit.UI.Selection import ObjectType
        from Autodesk.Revit.Exceptions import OperationCanceledException
        from Autodesk.Revit.DB import XYZ
        from pyrevit import revit

        doc        = self._doc
        uidoc      = self._uidoc
        view_level = self._view_level
        MARKER     = self._MARKER

        phase = None
        if self._view_phase_id:
            try:
                phase = doc.GetElement(self._view_phase_id)
            except Exception:
                phase = None

        try:
            # B) Sélection des notes textuelles
            try:
                picked_refs = uidoc.Selection.PickObjects(
                    ObjectType.Element,
                    self._sel_filter,
                    "Sélectionnez vos Notes Textuelles puis Terminer"
                )
            except OperationCanceledException:
                picked_refs = []

            if not picked_refs:
                self._show_result(u"❌ Aucune note sélectionnée.")
                return

            # C) Regrouper les notes par pièce via la vue en plan
            room_to_notes = {}
            for reference in picked_refs:
                note = doc.GetElement(reference)
                pt2d = note.Coord
                pt3d = XYZ(pt2d.X, pt2d.Y, view_level)
                room = (doc.GetRoomAtPoint(pt3d, phase) if phase
                        else doc.GetRoomAtPoint(pt3d))
                if room:
                    room_to_notes.setdefault(room.Id, []).append(note)

            single_note_rooms = {
                rid: notes[0]
                for rid, notes in room_to_notes.items()
                if len(notes) == 1
            }

            if not single_note_rooms:
                self._show_result(u"❌ Aucune pièce avec exactement une note.")
                return

            # D) Transaction : copie du texte dans le paramètre de la pièce
            processed = set()
            with revit.Transaction("Copie Note → Pièce"):
                for room_id, note in single_note_rooms.items():
                    text = note.Text
                    room  = doc.GetElement(room_id)
                    param = room.LookupParameter(param_name)
                    if not param or param.IsReadOnly:
                        continue

                    param.Set(text)
                    if not text.startswith(MARKER):
                        note.Text = MARKER + text

                    processed.add(room_id)

            # E) Affichage du résultat
            count = len(processed)
            if   count == 0:
                msg = u"❌ Aucun paramètre n'a été mis à jour."
            elif count == 1:
                msg = u"✅ 1 pièce mise à jour sur « {} ».".format(param_name)
            else:
                msg = u"✅ {} pièces mises à jour sur « {} ».".format(count, param_name)

            self._show_result(msg)
        finally:
            # Réafficher le sélecteur pour enchaîner un nouveau traitement.
            self.Show()
            try:
                self.Activate()
            except Exception:
                pass


# -----------------------------------------------------------------------------
# === LANCEMENT — sélecteur de paramètre NON MODAL ===
# -----------------------------------------------------------------------------
xaml_param = script.get_bundle_file("param_dialog.xaml")
pd         = ParamDialog(xaml_param)
_set_revit_owner(pd)
pd.Show()
