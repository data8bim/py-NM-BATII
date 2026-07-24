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


#__title__ = 'Lignes → Sép. Pièces (palette)'
#__author__ = 'data8bim (d8b)'


"""
NM-BATII — Recopie des lignes en separateurs de piece (palette non modale).

Palette non modale. Remplace l'ancienne version qui exigeait de selectionner
les lignes AVANT de lancer le bouton.

Pourquoi une palette plutot qu'un PickObjects :
  PickObjects() monopolise la session de selection Revit : le ruban est
  desactive et l'utilisateur perd les outils natifs de tri (filtre de
  selection, selection par categorie, « selectionner toutes les occurrences »,
  Visibilite/Graphismes, masquage dans la vue...). Une fenetre non modale
  laisse Revit totalement disponible : l'utilisateur compose sa selection
  comme il veut, puis clique sur « Convertir la selection ».

Contraintes techniques d'une fenetre non modale :
  - Tout appel modifiant le document doit passer par un IExternalEventHandler,
    sinon Revit leve « Starting a transaction from an external application
    running outside of API context is not allowed ».
  - PIEGE MAJEUR : apres le retour de IExternalCommand.Execute(),
    IronPython/pyRevit vide les globals du module. Tout callback (timer,
    evenement Revit, clic bouton) qui appelle une fonction module par son nom
    global leve alors « NameError: name '...' is not defined ». Si ce callback
    avale ses exceptions, le symptome visible est un simple affichage fige,
    sans erreur. Regle appliquee ici : les callbacks n'utilisent QUE des
    methodes (resolues via la classe, maintenue vivante par l'instance), des
    attributs d'instance, et des imports faits en local dans la methode.
  - La vue active peut changer pendant que la palette est ouverte : elle est
    donc relue et revalidee a chaque conversion, jamais capturee au demarrage.

Suivi de la selection (deux sources, complementaires) :
  - UIApplication.SelectionChanged (Revit >= 2024) : signal instantane.
  - DispatcherTimer de secours, explicitement rattache au Dispatcher de la
    fenetre. Le constructeur DispatcherTimer() sans argument s'accroche au
    Dispatcher.CurrentDispatcher du thread appelant, qui n'est pas toujours
    celui qui pompe les messages -> le timer ne se declenche jamais et le
    libelle reste fige sur son etat initial.
"""

import os
import sys

from pyrevit import HOST_APP, forms
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent
from Autodesk.Revit.DB import IFailuresPreprocessor

_HERE = os.path.dirname(__file__)

# Feuille de styles WPF partagee (lib/dialogs/dialogs_styles.xaml) : rend
# disponibles les cles NMButtonValide / NMButtonAppliquer / NMButtonAnnuler
# utilisees par les pieds de dialogue. Tous les styles y sont nommes (x:Key),
# le chargement n'applique donc rien de lui-meme aux controles existants.
_lib = os.path.join(_HERE, '..', '..', '..', '..', 'lib')
if _lib not in sys.path:
    sys.path.insert(0, _lib)
from dialogs.dialogs_styles_loader import load as _charger_styles
_charger_styles()


# ── Lecture de la sélection ──────────────────────────────────────────────────

def _set_revit_owner(window):
    """Attache la fenetre WPF comme enfant Win32 de la fenetre principale Revit."""
    try:
        from System.Windows.Interop import WindowInteropHelper
        from pyrevit import HOST_APP as _HOST
        WindowInteropHelper(window).Owner = _HOST.uiapp.MainWindowHandle
    except Exception:
        pass


# ── Fenêtre de résultat ──────────────────────────────────────────────────────

class ResultWindow(forms.WPFWindow):
    """Charge ResultWindow.xaml et affiche un message."""

    def __init__(self, message, title=u"Séparateurs de pièce"):
        forms.WPFWindow.__init__(self, os.path.join(_HERE, 'ResultWindow.xaml'))
        self.Title = title
        self.txtMessage.Text = message
        _set_revit_owner(self)
        self.btnClose.Click += self._on_close

    def _on_close(self, sender, args):
        self.Close()

    @staticmethod
    def show(message, title=u"Séparateurs de pièce"):
        ResultWindow(message, title).ShowDialog()


# ── External event ───────────────────────────────────────────────────────────

class _ActionHandler(IExternalEventHandler):
    """
    Delegue les appels Revit API au thread principal Revit (contexte sur).
    Pattern obligatoire pour les fenetres non modales (palette) en Revit.
    Voir : https://www.revitapidocs.com/2024/6285066f-4e6e-8aae-3bc3-0d0f6a3dc582.htm
    """

    def __init__(self):
        self._fn = [None]   # mutable — pas de nonlocal en IronPython 2.7

    def planifier(self, fn):
        """Enregistre l'action a executer (appele depuis le thread WPF)."""
        self._fn[0] = fn

    def Execute(self, uiapp):
        """Execute par Revit sur le thread principal a un moment sur."""
        fn = self._fn[0]
        self._fn[0] = None
        if fn:
            try:
                fn()
            except Exception:
                pass   # les erreurs sont gerees a l'interieur de fn()

    def GetName(self):
        return u"NM-BATII — Lignes vers séparateurs de pièce"


_action_handler = _ActionHandler()
_ext_event      = ExternalEvent.Create(_action_handler)


# ── Masquage ciblé des avertissements Revit ──────────────────────────────────

class _MasquerAvertissements(IFailuresPreprocessor):
    """
    Supprime a la volee les avertissements de « leger decalage par rapport a
    l'axe » emis pendant la creation des separateurs de piece.

    Recopier des lignes DWG produit presque toujours des segments a une
    fraction de degre de l'horizontale : Revit ouvre alors une boite modale
    par ligne, ce qui rend la conversion en masse inutilisable.

    Le masquage est CIBLE : seuls les identifiants listes dans _NOMS_CIBLES
    sont supprimes. Tout autre avertissement (chevauchement de separateurs,
    etc.) reste affiche normalement — il porte une information que
    l'utilisateur doit voir.
    """

    # Membres de BuiltInFailures.InaccurateFailures. Resolus par nom et non en
    # dur : un membre absent d'une version de Revit est simplement ignore.
    _NOMS_CIBLES = (
        'InaccurateRoomSeparation',   # separateur de piece hors axe (le cas vise)
        'InaccurateLine',             # ligne generique hors axe
        'InaccurateSketchLine',       # ligne d'esquisse hors axe
    )

    def __init__(self):
        self.nb_supprimes = 0
        self._ids = None

    def _ids_cibles(self):
        """Resout (une fois) les FailureDefinitionId a masquer."""
        if self._ids is None:
            ids = []
            try:
                from Autodesk.Revit.DB import BuiltInFailures
                for nom in _MasquerAvertissements._NOMS_CIBLES:
                    try:
                        ids.append(getattr(BuiltInFailures.InaccurateFailures, nom))
                    except Exception:
                        pass
            except Exception:
                pass
            self._ids = ids
        return self._ids

    def PreprocessFailures(self, fa):
        try:
            from Autodesk.Revit.DB import FailureProcessingResult, FailureSeverity
        except Exception:
            from Autodesk.Revit.DB import FailureProcessingResult
            return FailureProcessingResult.Continue

        cibles = self._ids_cibles()
        for msg in list(fa.GetFailureMessages()):
            try:
                if msg.GetSeverity() != FailureSeverity.Warning:
                    continue
                fid = msg.GetFailureDefinitionId()
                for cible in cibles:
                    if fid == cible:
                        fa.DeleteWarning(msg)
                        self.nb_supprimes += 1
                        break
            except Exception:
                pass
        return FailureProcessingResult.Continue


# ── Palette principale ───────────────────────────────────────────────────────

class FenetrePalette(forms.WPFWindow):
    """Palette non modale : convertit la selection courante a la demande."""

    def __init__(self):
        # handle_esc=False : par defaut, forms.WPFWindow ferme la fenetre sur
        # Echap. Cette palette reste ouverte pendant que l'utilisateur compose
        # sa selection dans la vue, ou Echap sert a sortir d'un outil ou a
        # vider la selection — elle ne doit pas se fermer pour autant.
        forms.WPFWindow.__init__(self, os.path.join(_HERE, 'WPFWindow.xaml'),
                                 handle_esc=False)

        # Maintient le namespace IronPython en vie via le GC .NET, et garde
        # les references ExternalEvent comme attributs d'instance : garantit
        # leur survie meme apres la sortie du thread script.
        self._module_globals = globals()
        self._dir            = _HERE
        self._action_handler = _action_handler
        self._ext_event      = _ext_event

        self._timer    = None
        self._uiapp    = None
        self._abonne   = False

        # Empreinte de la derniere selection convertie — interdit un second
        # clic sur la meme selection, qui doublerait les separateurs.
        self._selection_convertie = None

        # Instancie ICI, puis conserve comme attribut d'instance : _convertir()
        # tourne dans un callback ou les globals du module peuvent avoir ete
        # vides, la classe n'y serait plus resoluble par son nom.
        self._masqueur = _MasquerAvertissements()

        self.btn_convertir.Click += self.btn_convertir_Click
        self.btn_aide.Click      += self.btn_aide_Click
        self.btn_fermer.Click    += self.btn_fermer_Click
        self.Closed              += self._on_closed

        self._positionner_a_droite()
        self._abonner_selection_changed()
        self._demarrer_timer()
        self._rafraichir_selection()

    # ------------------------------------------------------------------
    # Positionnement
    # ------------------------------------------------------------------

    def _positionner_a_droite(self, marge=12):
        """
        Ancre la palette contre le bord droit de la zone de travail de l'ecran
        qui heberge Revit (Revit etant quasi toujours maximise, cela revient au
        bord droit de sa fenetre).

        Piege DPI : proc_screen_workarea est en PIXELS PHYSIQUES alors que
        Window.Left/Top sont en unites independantes du peripherique (DIP).
        Sans division par le facteur d'echelle, la palette part hors ecran des
        que l'affichage est a 125 % ou plus.
        """
        zone_gauche = zone_droite = zone_haut = None

        # 1) Voie principale : ecran hebergeant Revit (gere le multi-ecran).
        try:
            from pyrevit import HOST_APP as _HOST
            zone = _HOST.proc_screen_workarea
            if zone is not None:
                facteur = 1.0
                try:
                    f = _HOST.proc_screen_scalefactor
                    if f:
                        facteur = float(f)
                except Exception:
                    pass
                if facteur <= 0:
                    facteur = 1.0
                zone_gauche = zone.Left  / facteur
                zone_droite = zone.Right / facteur
                zone_haut   = zone.Top   / facteur
        except Exception:
            pass

        # 2) Repli : zone de travail WPF, deja exprimee en DIP (ecran principal).
        if zone_droite is None:
            try:
                from System.Windows import SystemParameters
                wa = SystemParameters.WorkArea
                zone_gauche = wa.Left
                zone_droite = wa.Right
                zone_haut   = wa.Top
            except Exception:
                return

        try:
            largeur = self.Width
            if not largeur or largeur <= 0:
                largeur = 460
            gauche = zone_droite - largeur - marge
            if gauche < zone_gauche:
                gauche = zone_gauche
            self.Left = gauche
            self.Top  = zone_haut + marge
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Lecture de la selection
    # ------------------------------------------------------------------
    #
    # METHODE et non fonction module : apres le retour de
    # IExternalCommand.Execute(), IronPython/pyRevit vide les globals du
    # module. Une fonction appelee par son nom global depuis un callback
    # (timer, evenement Revit, clic bouton) leve alors
    # « NameError: name '...' is not defined ». Une methode est resolue via
    # la classe, maintenue vivante par l'instance : elle reste appelable.
    # Meme raison pour les imports, faits en local a chaque appel.

    def _lire_selection(self):
        """
        Lit et trie la selection Revit courante.

        Lecture seule : ne demarre aucune transaction, donc appelable depuis
        le thread UI (timer / evenement) comme depuis le thread Revit API.

        Le document est pris sur l'UIDocument lui-meme : doc et selection
        viennent ainsi toujours de la meme source, sinon GetElement() renvoie
        None pour des ElementId pourtant valides.

        Retourne un dict : ok, erreur, nb_ids, courbes, nb_lignes,
        nb_ignores, uidoc, doc, vue.
        """
        info = {
            'ok': False, 'erreur': None, 'nb_ids': 0,
            'courbes': [], 'nb_lignes': 0, 'nb_ignores': 0,
            'uidoc': None, 'doc': None, 'vue': None, 'signature': None,
        }
        try:
            from pyrevit import HOST_APP as _HOST
            from Autodesk.Revit.DB import CurveElement as _CurveElement

            uidoc = _HOST.uidoc
            if uidoc is None:
                info['erreur'] = u"aucun document actif"
                return info

            doc = uidoc.Document
            info['uidoc'] = uidoc
            info['doc']   = doc
            info['vue']   = doc.ActiveView

            ids = list(uidoc.Selection.GetElementIds())
            info['nb_ids'] = len(ids)

            # Empreinte de la selection : sert a reconnaitre une selection deja
            # convertie et a interdire un second clic, qui creerait des
            # separateurs en double par-dessus les premiers.
            try:
                info['signature'] = frozenset(e.IntegerValue for e in ids)
            except Exception:
                info['signature'] = None

            for eid in ids:
                elem = doc.GetElement(eid)
                if elem is None:
                    info['nb_ignores'] += 1
                    continue
                if isinstance(elem, _CurveElement):
                    try:
                        crv = elem.GeometryCurve
                    except Exception:
                        crv = None
                    if crv is not None:
                        info['courbes'].append(crv)
                    else:
                        info['nb_ignores'] += 1
                else:
                    info['nb_ignores'] += 1

            info['nb_lignes'] = len(info['courbes'])
            info['ok'] = True
            return info

        except Exception as ex:
            info['erreur'] = str(ex)
            return info

    # ------------------------------------------------------------------
    # Suivi de la selection
    # ------------------------------------------------------------------

    def _abonner_selection_changed(self):
        """
        S'abonne a UIApplication.SelectionChanged (Revit >= 2024) : signal
        instantane, evite d'attendre le prochain tick du timer.
        """
        try:
            from pyrevit import HOST_APP as _HOST
            self._uiapp = _HOST.uiapp
            self._uiapp.SelectionChanged += self._on_selection_changed
            self._abonne = True
        except Exception:
            # API absente ou abonnement refuse : le timer prend le relais.
            self._abonne = False

    def _on_selection_changed(self, sender, args):
        self._rafraichir_selection()

    def _demarrer_timer(self):
        """
        DispatcherTimer de secours, rattache EXPLICITEMENT au Dispatcher de
        cette fenetre. Sans ce rattachement, DispatcherTimer() s'accroche au
        Dispatcher.CurrentDispatcher du thread appelant : si ce thread ne
        pompe pas les messages, le Tick ne se declenche jamais.
        """
        try:
            from System.Windows.Threading import DispatcherTimer, DispatcherPriority
            from System import TimeSpan
            self._timer = DispatcherTimer(DispatcherPriority.Background,
                                          self.Dispatcher)
            self._timer.Interval = TimeSpan.FromMilliseconds(400)
            self._timer.Tick += self._on_tick
            self._timer.Start()
        except Exception:
            self._timer = None

    def _on_tick(self, sender, args):
        self._rafraichir_selection()

    @staticmethod
    def _pluriel(nombre, mot):
        """« 1 séparateur », « 3 séparateurs » — accord simple."""
        return u"{} {}{}".format(nombre, mot, u"s" if nombre > 1 else u"")

    def _rafraichir_selection(self):
        """Met a jour le libelle de selection, le bouton et son etat."""
        try:
            info = self._lire_selection()

            if not info['ok']:
                self.txtSelection.Text = u"Sélection : lecture impossible"
                self.btn_convertir.IsEnabled = False
                return

            nb_ids     = info['nb_ids']
            nb_lignes  = info['nb_lignes']
            nb_ignores = info['nb_ignores']

            # Une selection deja convertie ne doit pas pouvoir l'etre a nouveau :
            # les separateurs se superposeraient en double. Le blocage se leve
            # de lui-meme des que la selection change.
            deja_faite = (self._selection_convertie is not None
                          and info['signature'] is not None
                          and info['signature'] == self._selection_convertie)

            if deja_faite:
                self.txtSelection.Text = u"Sélection déjà convertie"
            elif nb_ids == 0:
                self.txtSelection.Text = u"Sélection : aucun élément sélectionné"
            elif nb_ignores == 0:
                self.txtSelection.Text = u"Sélection : {}".format(
                    self._pluriel(nb_lignes, u"ligne"))
            else:
                self.txtSelection.Text = u"Sélection : {} — {}".format(
                    self._pluriel(nb_lignes, u"ligne"),
                    self._pluriel(nb_ignores, u"ignoré"))

            # ▶ (U+25B6) en echappement plutot qu'en caractere litteral, pour
            # survivre a un editeur qui re-encoderait le fichier.
            self.btn_convertir.Content = u"▶  Convertir en {}".format(
                u"séparateurs" if nb_lignes > 1 else u"séparateur")
            self.btn_convertir.IsEnabled = (nb_lignes > 0) and not deja_faite

        except Exception:
            try:
                self.txtSelection.Text = u"Sélection : erreur de lecture"
            except Exception:
                pass

    def _statut(self, message):
        try:
            self.txtStatut.Text = message
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Handlers boutons
    # ------------------------------------------------------------------

    def btn_convertir_Click(self, sender, args):
        """
        Planifie la conversion sur le thread Revit API.

        La selection n'est PAS capturee ici : elle est relue dans _convertir(),
        cote thread Revit, pour refleter l'etat reel au moment de l'execution.
        """
        _self = [self]

        def _action():
            _self[0]._convertir()

        self._statut(u"Conversion en cours…")
        self._action_handler.planifier(_action)
        self._ext_event.Raise()

    # ------------------------------------------------------------------
    # Aide
    # ------------------------------------------------------------------
    # Le texte occupait auparavant le haut de la palette en permanence, alors
    # qu'on ne le lit qu'une fois. Il est desormais a la demande.

    _AIDE = (
        u"Recopie des lignes de la vue en séparateurs de pièce.\n\n"
        u"Cette fenêtre reste ouverte pendant que vous travaillez : "
        u"sélectionnez vos lignes dans la vue avec tous les outils Revit "
        u"habituels — filtre de sélection, sélection par catégorie, "
        u"« sélectionner toutes les occurrences », Visibilité/Graphismes, "
        u"masquage dans la vue…\n\n"
        u"Le décompte se met à jour tout seul. Cliquez ensuite sur "
        u"« Convertir » : seules les lignes sont converties, les autres "
        u"éléments sélectionnés sont ignorés.\n\n"
        u"Les lignes d'origine ne sont pas supprimées : les séparateurs sont "
        u"créés par-dessus."
    )

    def btn_aide_Click(self, sender, args):
        try:
            from dialogs.dialogs_styles_loader import show_alert
            show_alert(u"NM-BATII — Lignes → Séparateurs", self._AIDE)
        except Exception:
            pass

    def btn_fermer_Click(self, sender, args):
        self.Close()

    def _on_closed(self, sender, args):
        try:
            if self._timer is not None:
                self._timer.Stop()
        except Exception:
            pass
        try:
            if self._abonne and self._uiapp is not None:
                self._uiapp.SelectionChanged -= self._on_selection_changed
                self._abonne = False
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Conversion (thread Revit API)
    # ------------------------------------------------------------------

    def _convertir(self):
        """Cree les separateurs de piece depuis la selection courante."""
        try:
            from Autodesk.Revit.DB import (
                ViewPlan    as _ViewPlan,
                Plane       as _Plane,
                SketchPlane as _SketchPlane,
                Transaction as _Transaction,
                CurveArray  as _CurveArray,
            )
        except Exception as ex:
            self._statut(u"✖ Imports Revit indisponibles : {}".format(str(ex)))
            return

        info = self._lire_selection()
        if not info['ok']:
            self._statut(u"✖ Lecture de la sélection impossible : {}".format(
                info['erreur']))
            return

        doc = info['doc']

        # La vue active peut avoir change depuis l'ouverture de la palette :
        # on la relit et on la revalide a chaque conversion.
        vue = info['vue']
        if not isinstance(vue, _ViewPlan):
            self._statut(u"✖ La vue active doit être un plan d'étage (Floor Plan).")
            return

        courbes = info['courbes']
        if not courbes:
            self._statut(u"✖ Aucune ligne exploitable dans la sélection.")
            return

        tx = _Transaction(doc, u"Créer des séparateurs de pièce")

        # Masque les avertissements « ligne legerement hors axe » emis par
        # NewRoomBoundaryLines : sans cela Revit ouvre une boite modale par
        # ligne convertie. Doit etre pose AVANT tx.Start().
        self._masqueur.nb_supprimes = 0
        try:
            opts = tx.GetFailureHandlingOptions()
            opts.SetFailuresPreprocessor(self._masqueur)
            opts.SetClearAfterRollback(True)
            try:
                # Contexte non modal : laisse Revit traiter les eventuels
                # echecs restants sans forcer une boite modale immediate.
                opts.SetForcedModalHandling(False)
            except Exception:
                pass
            tx.SetFailureHandlingOptions(opts)
        except Exception:
            pass   # a defaut, Revit affichera ses avertissements normalement

        tx.Start()
        try:
            plane        = _Plane.CreateByNormalAndOrigin(vue.ViewDirection, vue.Origin)
            sketch_plane = _SketchPlane.Create(doc, plane)

            curve_array = _CurveArray()
            for crv in courbes:
                curve_array.Append(crv)

            nb_crees = 0
            lines = doc.Create.NewRoomBoundaryLines(sketch_plane, curve_array, vue)
            if lines:
                for _ in lines:
                    nb_crees += 1

            tx.Commit()

            # Compte-rendu volontairement minimal : le nom de la vue et le
            # nombre d'avertissements masques encombraient sans rien apprendre.
            # Memorise la selection traitee : le bouton restera grise tant
            # qu'elle n'aura pas change (voir _rafraichir_selection).
            self._selection_convertie = info['signature']

            msg = u"{} créé{}".format(
                self._pluriel(nb_crees, u"séparateur"),
                u"s" if nb_crees > 1 else u"")
            if info['nb_ignores']:
                msg += u"\n{} ignoré{}".format(
                    self._pluriel(info['nb_ignores'], u"élément"),
                    u"s" if info['nb_ignores'] > 1 else u"")
            self._statut(msg)

        except Exception as ex:
            try:
                tx.RollBack()
            except Exception:
                pass
            self._statut(u"✖ Erreur pendant la création :\n{}".format(str(ex)))


# ── Corps du script ──────────────────────────────────────────────────────────

try:
    # Pas de verification bloquante de la vue active ici : la palette reste
    # ouverte pendant que l'utilisateur navigue, la vue est validee a chaque
    # conversion (voir FenetrePalette._convertir).
    _palette = FenetrePalette()
    _set_revit_owner(_palette)
    _palette.Show()

except Exception as e:
    ResultWindow.show(
        u"Erreur NM-BATII : {}".format(str(e)),
        title=u"Échec"
    )
