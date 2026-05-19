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


#__title__ = 'Simplif. Lim. Pièces'
#__author__ = 'data8bim (d8b)'


"""
NM-BATII — Simplification des limites de pièce (séparateurs) de la vue active.

Interface :
  - "Sélection des limites"      → l'utilisateur sélectionne les séparateurs à traiter
  - "Toutes les limites de la vue" → traite tous les séparateurs de la vue active

Pipeline (répété jusqu'à convergence) :
  Étape 2 : supprime les séparateurs en double (même géométrie).
  Étape 3 : fusionne les séparateurs consécutifs colinéaires en un seul segment.

Puis une fois (après convergence step2+step3) :
  Étape 4 : fusionne les séparateurs colinéaires chevauchants ou adjacents.
  Étape 5 : supprime les doublons signalés par les avertissements Revit.
"""

import sys
import os
import System as _System

from pyrevit import revit, DB, forms, script
from Autodesk.Revit.DB import (
    ViewPlan,
    FilteredElementCollector,
    BuiltInCategory,
    Plane,
    SketchPlane,
    IFailuresPreprocessor,
    FailureProcessingResult,
)
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType

doc    = revit.doc
uidoc  = revit.uidoc
view   = doc.ActiveView
output = script.get_output()


# ── Chargement styles + logs ───────────────────────────────────────────────────

_LOG_ACTIF     = False
_charger_styles = None

try:
    _lib = os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'lib')
    if _lib not in sys.path:
        sys.path.insert(0, _lib)
    from utils.config_loader import load_config
    from dialogs.dialogs_styles_loader import load as _charger_styles
    _LOG_ACTIF = bool(load_config().get('activer_logs_scripts', False))
except Exception:
    pass

if not _LOG_ACTIF:
    try:
        output.close()
    except Exception:
        pass


# ── Pompe UI ───────────────────────────────────────────────────────────────────
# Utilise Dispatcher.Invoke(Render) pour forcer le rendu WPF sans pomper la
# queue Win32 — évite le verrou "Cannot modify document" dans le TransactionGroup.

try:
    from System.Windows.Threading import Dispatcher      as _WPFDispatcher
    from System.Windows.Threading import DispatcherPriority as _WPFPriority

    def _noop():
        pass

    _noop_action = _System.Action(_noop)

    def _pump_ui():
        try:
            _WPFDispatcher.CurrentDispatcher.Invoke(_WPFPriority.Render, _noop_action)
        except Exception:
            pass
except Exception:
    def _pump_ui():
        pass


# ── Log + mise à jour live de la fenêtre de progression ───────────────────────

_last_log_msg    = u""
_active_prog_win = None
_last_prog_tick  = [0]


def _log(msg):
    global _last_log_msg
    _last_log_msg = msg
    if _LOG_ACTIF:
        output.print_md(msg)
    if _active_prog_win is not None:
        try:
            now = _System.Environment.TickCount
            if abs(now - _last_prog_tick[0]) >= 150:
                _active_prog_win.txtLog.Text = msg
                _pump_ui()
                _last_prog_tick[0] = now
        except Exception:
            pass


# ── Constantes géométriques ────────────────────────────────────────────────────

_TOL_PT  = 1e-4


# ── Fonctions utilitaires ──────────────────────────────────────────────────────

def _round_pt(pt):
    return (
        int(round(pt.X / _TOL_PT)),
        int(round(pt.Y / _TOL_PT)),
        int(round(pt.Z / _TOL_PT)),
    )


def _get_sep_lines(working_set=None):
    """Retourne les OST_RoomSeparationLines à traiter (éléments bruts)."""
    if working_set is not None:
        result = []
        for eid_int in working_set:
            try:
                elem = doc.GetElement(DB.ElementId(eid_int))
                if elem is not None and elem.IsValidObject:
                    result.append(elem)
            except Exception:
                pass
        return result

    return list(
        FilteredElementCollector(doc, view.Id)
        .OfCategory(BuiltInCategory.OST_RoomSeparationLines)
        .WhereElementIsNotElementType()
        .ToElements()
    )


def _collect_line_snapshots(working_set=None):
    """
    Retourne [(int_id, XYZ_p0, XYZ_p1)] — copies indépendantes des coordonnées.
    N'utilise PAS de références vivantes aux éléments Revit afin que les tuples
    restent valides à l'intérieur d'une transaction ultérieure.
    """
    result = []
    for elem in _get_sep_lines(working_set):
        try:
            crv = elem.GeometryCurve
            if isinstance(crv, DB.Line):
                p0 = crv.GetEndPoint(0)
                p1 = crv.GetEndPoint(1)
                result.append((
                    elem.Id.IntegerValue,
                    DB.XYZ(p0.X, p0.Y, p0.Z),
                    DB.XYZ(p1.X, p1.Y, p1.Z),
                ))
        except Exception:
            pass
    return result


def _canonical_dir(v):
    """Direction normalisée et canonique (composante X ≥ 0, ou X=0 et Y ≥ 0)."""
    v = v.Normalize()
    if v.X < -_TOL_PT or (abs(v.X) <= _TOL_PT and v.Y < -_TOL_PT):
        v = DB.XYZ(-v.X, -v.Y, -v.Z)
    return v


def _overlap_or_touch(a1, a2, b1, b2):
    """True si deux intervalles 1D se chevauchent ou se touchent."""
    return not (a2 < b1 - _TOL_PT or b2 < a1 - _TOL_PT)


def _is_sep_line(eid):
    """True si l'ElementId désigne une OST_RoomSeparationLines."""
    try:
        el = doc.GetElement(eid)
        return (el is not None and el.Category is not None and
                el.Category.Id.IntegerValue == int(BuiltInCategory.OST_RoomSeparationLines))
    except Exception:
        return False


# ── Filtre de sélection Revit ──────────────────────────────────────────────────

class LimitesFilter(ISelectionFilter):
    _cat_id = int(BuiltInCategory.OST_RoomSeparationLines)

    def AllowElement(self, elem):
        try:
            return (elem.Category is not None and
                    elem.Category.Id.IntegerValue == LimitesFilter._cat_id)
        except Exception:
            return False

    def AllowReference(self, ref, pt):
        return False


def pick_room_sep_lines():
    try:
        refs = uidoc.Selection.PickObjects(
            ObjectType.Element,
            LimitesFilter(),
            u"Sélectionnez les séparateurs de pièce, puis appuyez sur Terminer (Entrée)"
        )
        if not refs:
            return None
        return set(ref.ElementId.IntegerValue for ref in refs)
    except Exception:
        return None


# ── Fenêtres WPF ──────────────────────────────────────────────────────────────

class ResultWindow(forms.WPFWindow):

    def __init__(self, message, title=u"Simplifier les limites de pièce"):
        forms.WPFWindow.__init__(self, 'ResultWindow.xaml')
        self.Title = title
        self.txtMessage.Text = message
        self.btnClose.Click += self._on_close

    def _on_close(self, sender, args):
        self.Close()

    @staticmethod
    def show(message, title=u"Simplifier les limites de pièce", exit_after=False):
        win = ResultWindow(message, title)
        win.ShowDialog()
        if exit_after:
            sys.exit(0)


class FenetreProgression(forms.WPFWindow):

    def __init__(self):
        forms.WPFWindow.__init__(self, 'ProgressWindow.xaml')

    def mettre_a_jour(self, pct, message, detail=u""):
        self.txtStatus.Text    = message
        self.txtCurrent.Text   = detail
        self.progressBar.Value = min(100, max(0, pct))
        self.txtLog.Text       = _last_log_msg
        _last_prog_tick[0]     = _System.Environment.TickCount
        _pump_ui()


class FenetrePrincipale(forms.WPFWindow):

    def __init__(self):
        if _charger_styles is not None:
            try:
                _charger_styles()
            except Exception:
                pass
        forms.WPFWindow.__init__(self, 'WPFWindow.xaml')
        self.action = None
        self.btn_selection.Click += self._on_selection
        self.btn_toutes.Click    += self._on_toutes
        self.btn_fermer.Click    += self._on_fermer

    def _on_selection(self, sender, args):
        self.action = 'selection'
        self.Close()

    def _on_toutes(self, sender, args):
        self.action = 'toutes'
        self.Close()

    def _on_fermer(self, sender, args):
        self.action = 'fermer'
        self.Close()


# ── Gestionnaire d'avertissements Revit ───────────────────────────────────────

class _SuppressWarnings(IFailuresPreprocessor):
    """Supprime silencieusement les avertissements Revit (Warning)."""
    def PreprocessFailures(self, fa):
        for msg in list(fa.GetFailureMessages()):
            if msg.GetSeverity() == DB.FailureSeverity.Warning:
                try:
                    fa.DeleteWarning(msg)
                except Exception:
                    pass
        return FailureProcessingResult.Continue


def _transaction(name):
    """Crée un DB.Transaction avec suppression automatique des avertissements."""
    t = DB.Transaction(doc, name)
    opts = t.GetFailureHandlingOptions()
    opts.SetFailuresPreprocessor(_SuppressWarnings())
    t.SetFailureHandlingOptions(opts)
    return t


# ── Étape 2 : suppression des doublons ────────────────────────────────────────

def _endpoint_key(p0, p1):
    k0 = _round_pt(p0)
    k1 = _round_pt(p1)
    return (k0, k1) if k0 <= k1 else (k1, k0)


def step2_delete_duplicates(working_set=None):
    """
    Supprime les séparateurs en double (même courbe).
    Retourne (count, deleted_int_ids_set).
    """
    lines = _get_sep_lines(working_set)
    if len(lines) < 2:
        return 0, set()

    to_delete = []
    seen = {}

    for elem in lines:
        try:
            crv = elem.GeometryCurve
            if not isinstance(crv, DB.Line):
                continue
            key = _endpoint_key(crv.GetEndPoint(0), crv.GetEndPoint(1))
            eid_int = elem.Id.IntegerValue
            if key in seen:
                to_delete.append(elem.Id)
                _log(u"  Doublon : #{} (identique à #{})".format(eid_int, seen[key]))
            else:
                seen[key] = eid_int
        except Exception:
            pass

    if not to_delete:
        return 0, set()

    deleted = set()
    n = 0
    t = _transaction(u"Suppr. séparateurs doublons")
    t.Start()
    try:
        for eid in to_delete:
            eid_int = eid.IntegerValue
            try:
                doc.Delete(eid)
                deleted.add(eid_int)
                n += 1
            except Exception as ex:
                _log(u"  Échec doublon #{} : {}".format(eid_int, str(ex)))
        t.Commit()
    except Exception:
        try:
            t.RollBack()
        except Exception:
            pass
        raise
    return n, deleted


# ── Étape 4 : fusion des chevauchements (algo 10_CLEAN) ───────────────────────

def step4_merge_overlap_once(working_set=None):
    """
    UNE passe de fusion des lignes colinéaires chevauchantes ou adjacentes.
    N'utilise que des int_ids et des copies XYZ dans ops — aucune référence
    vivante à des éléments Revit — pour rester stable à l'intérieur d'une
    transaction imbriquée dans un TransactionGroup.
    Retourne (count_fusions, deleted_int_ids_set, created_int_ids_set).
    """
    raw = _collect_line_snapshots(working_set)  # [(int_id, XYZ_p0, XYZ_p1)]
    if not raw:
        return 0, set(), set()

    # Regroupement par support colinéaire
    groups = {}
    for int_id, p0, p1 in raw:
        vec = DB.XYZ(p1.X - p0.X, p1.Y - p0.Y, p1.Z - p0.Z)
        if vec.GetLength() < _TOL_PT:
            continue
        d = _canonical_dir(vec)
        dot = p0.X * d.X + p0.Y * d.Y          # d.Z == 0 pour lignes horizontales
        proj_x = p0.X - d.X * dot
        proj_y = p0.Y - d.Y * dot
        key = (round(d.X, 4), round(d.Y, 4), round(proj_x, 4), round(proj_y, 4))
        groups.setdefault(key, []).append((int_id, p0, p1))

    # Construction des opérations de fusion
    ops = []  # [(XYZ_start, XYZ_end, [int_id, ...])]
    for key, items in groups.items():
        if len(items) <= 1:
            continue
        d_x, d_y, px, py = key
        d_len = (d_x ** 2 + d_y ** 2) ** 0.5
        if d_len < _TOL_PT:
            continue
        d = DB.XYZ(d_x / d_len, d_y / d_len, 0.0)   # re-normalise depuis la clé
        origin_z = items[0][1].Z
        origin   = DB.XYZ(px, py, origin_z)

        segs = []
        for int_id, p0, p1 in items:
            dp0 = DB.XYZ(p0.X - origin.X, p0.Y - origin.Y, 0.0)
            dp1 = DB.XYZ(p1.X - origin.X, p1.Y - origin.Y, 0.0)
            s0  = d.X * dp0.X + d.Y * dp0.Y
            s1  = d.X * dp1.X + d.Y * dp1.Y
            segs.append((min(s0, s1), max(s0, s1), int_id))
        segs.sort(key=lambda x: x[0])

        cur_s1  = segs[0][0]
        cur_s2  = segs[0][1]
        cur_ids = [segs[0][2]]
        merged  = []
        for s1, s2, iid in segs[1:]:
            if _overlap_or_touch(cur_s1, cur_s2, s1, s2):
                cur_s2 = max(cur_s2, s2)
                cur_ids.append(iid)
            else:
                merged.append((cur_s1, cur_s2, cur_ids))
                cur_s1, cur_s2, cur_ids = s1, s2, [iid]
        merged.append((cur_s1, cur_s2, cur_ids))

        for s1, s2, ids in merged:
            if len(ids) > 1:
                mp1 = DB.XYZ(origin.X + d.X * s1, origin.Y + d.Y * s1, origin_z)
                mp2 = DB.XYZ(origin.X + d.X * s2, origin.Y + d.Y * s2, origin_z)
                ops.append((mp1, mp2, ids))

    if not ops:
        return 0, set(), set()

    plane   = Plane.CreateByNormalAndOrigin(view.ViewDirection, view.Origin)
    deleted = set()
    created = set()
    n = 0
    t = _transaction(u"Fusion colinéaires chevauchants")
    t.Start()
    try:
        sk = SketchPlane.Create(doc, plane)
        for mp1, mp2, ids in ops:
            if any(iid in deleted for iid in ids):
                continue
            try:
                new_line  = DB.Line.CreateBound(mp1, mp2)
                crv_array = DB.CurveArray()
                crv_array.Append(new_line)
                new_elems = doc.Create.NewRoomBoundaryLines(sk, crv_array, view)
                for iid in ids:
                    if iid not in deleted:
                        try:
                            doc.Delete(DB.ElementId(iid))
                            deleted.add(iid)
                        except Exception:
                            pass
                if new_elems is not None:
                    for ne in new_elems:
                        created.add(ne.Id.IntegerValue)
                n += 1
                _log(u"  Chevauchement fusionné : {} lignes → 1 segment".format(len(ids)))
            except Exception as ex:
                _log(u"  Échec fusion chevauchement : {}".format(str(ex)))
        t.Commit()
    except Exception:
        try:
            t.RollBack()
        except Exception:
            pass
        raise
    return n, deleted, created


# ── Étape 5 : nettoyage des avertissements RoomSeparationLinesOverlap ──────────

def step5_clean_overlap_warnings(working_set=None):
    """
    Supprime les lignes en doublon signalées par RoomSeparationLinesOverlap.
    Si working_set fourni, ne supprime que les lignes présentes dans la sélection.
    Retourne (count, deleted_int_ids_set).
    """
    try:
        failure_id = DB.BuiltInFailures.OverlapFailures.RoomSeparationLinesOverlap
    except Exception:
        return 0, set()

    warnings = list(doc.GetWarnings())
    deleted = set()
    n = 0
    t = _transaction(u"Nettoyage avert. chevauchement")
    t.Start()
    try:
        for w in warnings:
            try:
                if w.GetFailureDefinitionId() != failure_id:
                    continue
            except Exception:
                continue
            failing_ids = list(w.GetFailingElements())
            if len(failing_ids) <= 1:
                continue
            room_lines = [eid for eid in failing_ids if _is_sep_line(eid)]
            if working_set is not None:
                room_lines = [eid for eid in room_lines
                              if eid.IntegerValue in working_set]
            if len(room_lines) <= 1:
                continue
            for eid in room_lines[1:]:
                try:
                    doc.Delete(eid)
                    deleted.add(eid.IntegerValue)
                    n += 1
                except Exception:
                    pass
        t.Commit()
    except Exception:
        try:
            t.RollBack()
        except Exception:
            pass
        raise
    return n, deleted


# ── Pipeline principal ─────────────────────────────────────────────────────────

# Répartition de la barre de progression :
#   0 – 90 % : boucle step4 + step5 (fusion chevauchements + avert., max 20 passes)
#  90 – 95 % : step2 passe unique (filet de sécurité doublons exacts résiduels)
#  95 – 100 % : fin

_PCT_STEP45_MAX = 90
_MAX_PASSES_45  = 20


def run_pipeline(working_set, prog_win):
    """
    Exécute le pipeline complet sur working_set (ou toute la vue si None) :
      1. Boucle step4+step5 jusqu'à convergence (0–90 %) — fusion chevauchements + avert.
      2. Step2 passe unique (90–95 %) — filet de sécurité doublons exacts résiduels
    Toutes les transactions sont regroupées dans un TransactionGroup
    pour éviter l'erreur "Cannot modify the document... temporarily disabled".
    Retourne (total_n4, total_n5, total_n2, nb_passes45).
    """
    global _active_prog_win
    _active_prog_win = prog_win

    current_ws = set(working_set) if working_set is not None else None

    def _prog(pct, msg, detail=u""):
        if prog_win is not None:
            prog_win.mettre_a_jour(pct, msg, detail)

    tg = DB.TransactionGroup(doc, u"Simplification des limites de pièce")
    tg.Start()
    try:

        # ── Boucle step4 + step5 jusqu'à convergence ─────────────────────────
        total_n4  = 0
        total_n5  = 0
        pass_idx  = 1
        _log(u"### Étapes 4+5 — Fusion chevauchements + nettoyage avertissements")
        for pass_idx in range(1, _MAX_PASSES_45 + 1):
            pct_base = int(_PCT_STEP45_MAX * (pass_idx - 1) / _MAX_PASSES_45)

            _prog(
                pct_base,
                u"Fusion des chevauchements — passe {}...".format(pass_idx)
            )
            n4, del4, cre4 = step4_merge_overlap_once(current_ws)
            if current_ws is not None:
                current_ws -= del4
                current_ws |= cre4
            total_n4 += n4
            _log(u"  Passe {} : {} fusion(s) chevauchement".format(pass_idx, n4))

            _prog(
                pct_base + int(_PCT_STEP45_MAX / _MAX_PASSES_45 / 2),
                u"Nettoyage avert. chevauchement — passe {}...".format(pass_idx),
                u"Fusions : {}".format(n4)
            )
            n5, del5 = step5_clean_overlap_warnings(current_ws)
            if current_ws is not None:
                current_ws -= del5
            total_n5 += n5
            _log(u"  Passe {} : {} ligne(s) supprimée(s) via avertissements".format(pass_idx, n5))

            if n4 == 0 and n5 == 0:
                break

        # ── Step2 passe unique : filet de sécurité doublons exacts résiduels ─
        _prog(
            _PCT_STEP45_MAX,
            u"Vérification des doublons résiduels..."
        )
        _log(u"### Étape 2 — Doublons exacts résiduels")
        total_n2, del2 = step2_delete_duplicates(current_ws)
        if current_ws is not None:
            current_ws -= del2
        _log(u"  {} doublon(s) supprimé(s)".format(total_n2))

        tg.Assimilate()

    except Exception:
        try:
            tg.RollBack()
        except Exception:
            pass
        raise

    _prog(100, u"Terminé.", u"")
    _active_prog_win = None
    return total_n4, total_n5, total_n2, pass_idx


# ── Vérification vue active ────────────────────────────────────────────────────

if not isinstance(view, ViewPlan):
    ResultWindow.show(
        u"La vue active doit être un plan d'étage (Floor Plan).",
        title=u"Vue incompatible",
        exit_after=True
    )

if not _get_sep_lines():
    ResultWindow.show(
        u"Aucun séparateur de pièce trouvé dans la vue active.",
        exit_after=True
    )


# ── Boucle principale ──────────────────────────────────────────────────────────

while True:
    dlg = FenetrePrincipale()
    dlg.ShowDialog()

    action = dlg.action
    if action is None or action == 'fermer':
        break

    working_set = None
    if action == 'selection':
        working_set = pick_room_sep_lines()
        if not working_set:
            continue

    count_before = len(_get_sep_lines())

    prog = FenetreProgression()
    prog.Show()
    _pump_ui()

    total_n4, total_n5, total_n2, passes = run_pipeline(working_set, prog)

    count_after = len(_get_sep_lines())
    prog.Close()

    if working_set is not None:
        mode_txt = u"[{} limite(s) sélectionnée(s)]".format(len(working_set))
    else:
        mode_txt = u"[vue complète]"

    msg = (
        u"Terminé en {p} passe(s). {m}\n\n"
        u"  {n4} fusion(s) de segments chevauchants\n"
        u"  {n5} ligne(s) supprimée(s) via avertissements\n"
        u"  {n2} doublon(s) résiduel(s) supprimé(s)\n\n"
        u"Avant : {cb}  \u2192  Après : {ca} séparateur(s) dans la vue"
    ).format(
        p=passes, m=mode_txt,
        n4=total_n4, n5=total_n5, n2=total_n2,
        cb=count_before, ca=count_after
    )

    ResultWindow.show(msg)
