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


#__title__ = 'Edition séparateurs'
#__author__ = 'data8bim (d8b)'


"""
NM-BATII — Mode edition des separateurs de pieces.

But : corriger rapidement les separateurs de piece sans risquer de deplacer ou
supprimer un mur, un DWG ou quoi que ce soit d'autre.

Mecanisme — epinglage :
  Revit n'offre AUCUNE API « visible mais non selectionnable » par categorie.
  La seule combinaison qui donne ce resultat est :
    1. epingler tous les autres elements de la vue -> non modifiables ;
    2. SelectionUIOptions.SelectPinned = False    -> non selectionnables.
  Les elements restent VISIBLES : le contexte (murs, DWG) necessaire a
  l'alignement des separateurs est conserve.

  Le cout est inherent : Revit n'expose pas d'epinglage en masse, il faut N
  modifications de document. L'activation n'est donc pas instantanee sur une
  vue chargee. Le tri par categorie est confie au filtre natif pour limiter la
  casse (voir _activer).

Reversibilite :
  - Seuls les elements epingles PAR LE SCRIPT sont dépingles a la sortie : les
    ids sont memorises. Un element deja epingle par l'utilisateur avant
    l'activation n'est jamais touche.
  - Les options de selection modifiees sont relues avant changement et
    restaurees telles quelles.
  - Un fichier de recuperation est ecrit a l'activation et supprime a la
    desactivation. S'il subsiste au lancement suivant (Revit ferme brutalement,
    palette tuee...), le script propose de dépingler les elements orphelins.

Pendant le mode, le changement de vue est empeche : le mode ne protege que la
vue ou il a ete arme, basculer ailleurs ferait croire a une protection
inexistante. Voir _abonner_verrou_vue — c'est un RETOUR FORCE apres coup, et
non une annulation, car Revit 2025 ignore ViewActivating.Cancel().

Contraintes techniques d'une fenetre non modale : voir
[[palette-non-modale-globals-ironpython]] — apres le retour de
IExternalCommand.Execute() IronPython vide les globals du module. Tout ce
qu'un callback utilise doit etre une methode, un attribut d'instance, ou un
import fait en local.
"""

import os
import sys

from pyrevit import forms
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent

_HERE = os.path.dirname(__file__)

_lib = os.path.join(_HERE, '..', '..', '..', '..', 'lib')
if _lib not in sys.path:
    sys.path.insert(0, _lib)
from dialogs.dialogs_styles_loader import load as _charger_styles
_charger_styles()


def _set_revit_owner(window):
    """Attache la fenetre WPF comme enfant Win32 de la fenetre principale Revit."""
    try:
        from System.Windows.Interop import WindowInteropHelper
        from pyrevit import HOST_APP as _HOST
        WindowInteropHelper(window).Owner = _HOST.uiapp.MainWindowHandle
    except Exception:
        pass


# ── External event ───────────────────────────────────────────────────────────

class _ActionHandler(IExternalEventHandler):
    """
    Delegue les appels Revit API au thread principal Revit (contexte sur).
    Pattern obligatoire pour les fenetres non modales : l'epinglage ouvre une
    transaction, impossible depuis le thread WPF.
    """

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
                pass   # les erreurs sont gerees a l'interieur de fn()

    def GetName(self):
        return u"NM-BATII — Mode édition des séparateurs de pièces"


_action_handler = _ActionHandler()
_ext_event      = ExternalEvent.Create(_action_handler)


# ── Palette principale ───────────────────────────────────────────────────────

class FenetreMode(forms.WPFWindow):
    """Palette non modale pilotant l'activation / desactivation du mode."""

    # Options de la barre d'etat Revit (bas a droite) neutralisees pendant le
    # mode. Chacune est relue AVANT modification puis restauree telle quelle.
    _OPTIONS_SELECTION = ('SelectPinned', 'SelectLinks', 'SelectUnderlay')

    # NOTE — icone de la barre d'etat NON rafraichie, et c'est assume.
    #
    # Ecrire SelectionUIOptions.<option> change bien l'etat, mais Revit ne
    # repeint pas l'icone correspondante, et aucune API publique ne force ce
    # rafraichissement. Deux contournements ont ete tentes puis abandonnes :
    #
    #   - PostCommand(ID_TOGGLE_ALLOW_PINNED_SELECTION) : refuse. PostCommand
    #     n'accepte que les membres de l'enum PostableCommand ou une commande
    #     externe, et aucun ne correspond a ces bascules — alors meme que
    #     LookupCommandId les resout, d'ou un faux espoir tenace.
    #
    #   - Clic du bouton natif via UI Automation (AutomationId = RevitCommandId
    #     .Id). Fonctionnellement correct, mais INUTILISABLE EN PRODUCTION :
    #     automatiser son PROPRE processus oblige UIA a interroger les
    #     fournisseurs d'interface de Revit, ce qui remarshalle vers son thread
    #     UI. Depuis le thread Revit comme depuis un thread de fond, le
    #     parcours d'arbre gelait la vue plusieurs secondes et bloquait la
    #     desactivation. Le confort d'une icone a jour ne vaut pas ce prix.
    #
    # Ne pas re-tenter sans avoir mesure : l'ecriture de propriete est
    # instantanee et fiable, seule l'icone ment.

    def __init__(self):
        # handle_esc=False : par defaut, forms.WPFWindow branche PreviewKeyDown
        # et FERME la fenetre sur Echap. Or Echap fait partie du flux de travail
        # ici — c'est la touche qui libere l'outil Revit en cours — et la
        # palette a souvent le focus au moment ou on l'utilise. Sans ce
        # parametre, appuyer sur Echap fermait la palette au lieu de debloquer
        # la bascule.
        forms.WPFWindow.__init__(self, os.path.join(_HERE, 'WPFWindow.xaml'),
                                 handle_esc=False)

        self._module_globals = globals()
        self._action_handler = _action_handler
        self._ext_event      = _ext_event

        # Etat — tout est porte par l'instance : un callback ne peut pas
        # dependre des globals du module (vides apres Execute()).
        self._actif         = False
        self._ids_epingles  = []     # ids (int) epingles PAR LE SCRIPT
        self._options_avant = {}     # valeurs d'origine des options selection
        self._nom_vue       = u""
        self._vue_id        = None
        self._ferme         = False
        self._uiapp         = None
        self._abonne_vue    = False
        self._retour_en_cours = False   # garde anti-boucle du repli
        self._diag_vue      = u""       # trace du verrou, affichee dans l'UI
        self._etat_texte    = u"Mode inactif \U0001F513"
        self._fermeture_demandee = False   # fermeture en attente de desactivation
        self._timer_fermeture    = None
        self._action_en_attente  = False   # bascule planifiee, pas encore executee
        self._timer_attente      = None
        self._cache_ui           = {}      # AutomationElement par option

        # Logs pyRevit — convention de l'extension : rien ne s'affiche si
        # « Activer les logs des scripts » est decoche dans 01_Parametres.
        # Resolus ICI (globals encore vivants) et portes par l'instance, les
        # callbacks ne pouvant pas dependre des globals du module.
        self._log_actif = False
        self._output    = None
        try:
            from pyrevit import script as _script
            self._output = _script.get_output()
            from utils.config_loader import load_config
            self._log_actif = bool(load_config().get('activer_logs_scripts', False))
        except Exception:
            pass
        if not self._log_actif and self._output is not None:
            try:
                self._output.close()
            except Exception:
                pass

        self.btn_bascule.Click    += self.btn_bascule_Click
        self.btn_separateur.Click += self.btn_separateur_Click
        self.btn_aide.Click       += self.btn_aide_Click
        self.Closing              += self._on_closing
        self.Closed               += self._on_closed
        # Le placement attend la mesure : avec SizeToContent, les dimensions
        # ne sont connues qu'une fois la fenetre chargee.
        self.Loaded               += self._on_loaded

        # Bouton carre : icone seule, le libelle passe par l'infobulle du XAML.
        # 56 px dans un bouton de 64 : meme proportion que sur le bouton du
        # ruban, ou l'icone occupe quasiment toute la surface. Necessite le
        # Padding="2" pose dans le XAML (voir le commentaire du bouton).
        self._contenu_icone(self.btn_separateur, 'icone_separateur.png', taille=56)

        self._rafraichir_etat()
        self._verifier_recuperation()

    _LIBELLE_ACTIVER    = u"▶  Activer édition"
    _LIBELLE_DESACTIVER = u"✖  Désactiver édition"

    def _on_loaded(self, sender, args):
        self._ajuster_largeur()
        self._positionner_a_droite()

    def _ajuster_largeur(self):
        """
        Cale la largeur de la palette sur le plus long des deux libelles, une
        fois pour toutes.

        Methode : mesurer le TEXTE dans un TextBlock hors arbre visuel, puis en
        deduire la largeur de fenetre. Deterministe et sans effet de bord.

        Deux approches ont echoue avant celle-ci :
          - SizeToContent laisse actif : la fenetre se redimensionnait a chaque
            bascule, les deux libelles n'ayant pas la meme largeur ;
          - SizeToContent active puis remise a Manual dans la foulee : le
            redimensionnement n'a pas lieu dans le meme cycle de layout, la
            fenetre se figeait sur l'ANCIENNE largeur et le libelle le plus
            long se retrouvait tronque.
        """
        try:
            from System import Double
            from System.Windows import Size
            from System.Windows.Controls import TextBlock

            # Mesure hors arbre : ne perturbe pas la mise en page en cours,
            # contrairement a un Measure() sur le bouton reel.
            sonde = TextBlock()
            sonde.Text       = self._LIBELLE_DESACTIVER
            sonde.FontFamily = self.btn_bascule.FontFamily
            sonde.FontSize   = self.btn_bascule.FontSize
            sonde.FontWeight = self.btn_bascule.FontWeight
            sonde.Measure(Size(Double.PositiveInfinity, Double.PositiveInfinity))
            largeur_texte = sonde.DesiredSize.Width
            if not (largeur_texte > 0):
                return

            grille = self.Content            # Grid racine
            if grille is None or not (grille.ActualWidth > 0):
                return

            # Marge de la grille et padding du bouton sont LUS, jamais codes en
            # dur : les ajuster dans le XAML fausserait sinon ce calcul en
            # silence, et le libelle le plus long serait tronque.
            marge = grille.Margin.Left + grille.Margin.Right
            pad   = self.btn_bascule.Padding.Left + self.btn_bascule.Padding.Right

            # Epaisseur du cadre de fenetre = tout ce qui n'est ni la grille,
            # ni sa marge. Mesuree plutot que supposee : elle depend du theme
            # Windows et de la mise a l'echelle.
            cadre = self.ActualWidth - grille.ActualWidth - marge

            # + 2 px de garde contre les arrondis de rendu.
            self.Width = largeur_texte + pad + 2 + marge + cadre
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Positionnement
    # ------------------------------------------------------------------

    def _positionner_a_droite(self, marge=12):
        """
        Ancre la palette contre le bord droit de la zone de travail de l'ecran
        hebergeant Revit, CENTREE VERTICALEMENT.

        Piege DPI : proc_screen_workarea est en PIXELS PHYSIQUES alors que
        Window.Left/Top sont en DIP — sans division par le facteur d'echelle la
        fenetre part hors ecran des 125 %.
        """
        zone_gauche = zone_droite = zone_haut = zone_bas = None
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
                zone_gauche = zone.Left   / facteur
                zone_droite = zone.Right  / facteur
                zone_haut   = zone.Top    / facteur
                zone_bas    = zone.Bottom / facteur
        except Exception:
            pass

        if zone_droite is None:
            try:
                from System.Windows import SystemParameters
                wa = SystemParameters.WorkArea
                zone_gauche, zone_droite = wa.Left, wa.Right
                zone_haut,   zone_bas    = wa.Top,  wa.Bottom
            except Exception:
                return

        try:
            # ActualWidth/Height d'abord : avec SizeToContent, Width et Height
            # valent NaN tant que la fenetre n'est pas mesuree. C'est pourquoi
            # ce calcul est declenche depuis l'evenement Loaded.
            largeur = self.ActualWidth  or self.Width  or 260
            hauteur = self.ActualHeight or self.Height or 196
            if not (largeur > 0):
                largeur = 260
            if not (hauteur > 0):
                hauteur = 196

            gauche = zone_droite - largeur - marge
            if gauche < zone_gauche:
                gauche = zone_gauche
            self.Left = gauche

            haut = zone_haut + ((zone_bas - zone_haut) - hauteur) / 2.0
            if haut < zone_haut:
                haut = zone_haut
            self.Top = haut
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Acces Revit
    # ------------------------------------------------------------------

    def _contexte(self):
        """Retourne (uidoc, doc, vue) resolus en live, ou (None, None, None)."""
        try:
            from pyrevit import HOST_APP as _HOST
            uidoc = _HOST.uidoc
            if uidoc is None:
                return None, None, None
            doc = uidoc.Document
            return uidoc, doc, doc.ActiveView
        except Exception:
            return None, None, None

    def _options_selection(self):
        """
        Retourne l'objet SelectionUIOptions (options de la barre d'etat Revit,
        en bas a droite), ou None si indisponible.

        Le namespace est bien Autodesk.Revit.UI et NON
        Autodesk.Revit.UI.Selection — verifie par lecture des metadonnees de
        RevitAPIUI.dll (Revit 2025). L'accesseur est la methode statique
        SelectionUIOptions.GetSelectionUIOptions(). L'import errone faisait
        echouer silencieusement toute la neutralisation des options.
        """
        try:
            from Autodesk.Revit.UI import SelectionUIOptions
            return SelectionUIOptions.GetSelectionUIOptions()
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Verrouillage de la vue active
    # ------------------------------------------------------------------
    #
    # Le mode n'epingle QUE les elements de la vue ou il a ete arme. Si
    # l'utilisateur bascule sur une autre vue, plus rien n'y est protege alors
    # que la palette affiche toujours « ACTIF » : il croirait etre couvert et
    # pourrait deplacer un mur sans s'en rendre compte. ViewActivating est un
    # evenement PRE-action : args.Cancel = True empeche le basculement.

    def _abonner_verrou_vue(self):
        """
        Deux lignes de defense :
          1. ViewActivating + Cancel() — tentative de blocage propre. MESUREE
             INOPERANTE en Revit 2025 : l'appel passe sans erreur, la vue
             change quand meme. Conservee au cas ou (cout nul).
          2. ViewActivated + retour force — c'est CE mecanisme qui assure
             reellement le verrou : on constate que la vue courante n'est plus
             celle du mode et on y revient via uidoc.ActiveView.
        """
        try:
            from pyrevit import HOST_APP as _HOST
            if self._abonne_vue:
                return
            self._uiapp = _HOST.uiapp
            if self._uiapp is None:
                self._abonne_vue = False
                self._diag_vue = u"HOST_APP.uiapp est None"
                return
            self._uiapp.ViewActivating += self._on_view_activating
            self._uiapp.ViewActivated  += self._on_view_activated
            self._abonne_vue = True
            self._diag_vue = u"abonné"
        except Exception as ex:
            self._abonne_vue = False
            self._diag_vue = u"abonnement refusé : {}".format(str(ex))

    def _desabonner_verrou_vue(self):
        try:
            if self._abonne_vue and self._uiapp is not None:
                self._uiapp.ViewActivating -= self._on_view_activating
                self._uiapp.ViewActivated  -= self._on_view_activated
        except Exception:
            pass
        self._abonne_vue = False
        self._uiapp      = None

    def _on_view_activating(self, sender, args):
        if not self._actif:
            return
        try:
            # Reactiver la meme vue reste autorise, sinon Revit peut se
            # retrouver coince au retour sur la vue du mode.
            nouvelle = args.NewActiveView
            if (nouvelle is not None and self._vue_id is not None
                    and nouvelle.Id.IntegerValue == self._vue_id):
                return

            # PIEGE : sur RevitAPIPreEventArgs, Cancel est une METHODE et non
            # une propriete (verifie dans les metadonnees de RevitAPI.dll).
            # Ecrire « args.Cancel = True » ne fait que poser un attribut
            # Python sur l'objet : aucun effet, aucune erreur, la vue change
            # quand meme. Il faut appeler args.Cancel().
            annulable = True
            try:
                annulable = bool(args.Cancellable)
            except Exception:
                pass

            if not annulable:
                self._log(
                    u"⚠ Revit n'autorise pas l'annulation de ce changement de "
                    u"vue.\nLe mode ne protège que « {} ».".format(self._nom_vue)
                )
                return

            # CONSTAT TERRAIN (Revit 2025) : Cancel() s'execute sans lever
            # d'exception mais Revit l'IGNORE pour l'activation de vue — le
            # basculement a lieu quand meme. On le tente tout de meme (cout
            # nul, et une version future pourrait l'honorer, ce qui donnerait
            # un refus plus net), mais on n'affiche AUCUN message ici : ce
            # serait annoncer un blocage qui n'a pas lieu. C'est le repli
            # _on_view_activated qui fait le travail et qui informe.
            args.Cancel()
            self._diag_vue = u"Cancel() appelé (ignoré par Revit 2025)"
        except Exception as ex:
            self._diag_vue = u"exception : {}".format(str(ex))

    # -- Repli : Revit a laisse passer le changement, on revient de force -----

    def _on_view_activated(self, sender, args):
        """
        Filet apres coup. Si la vue courante n'est plus celle du mode, c'est
        que l'annulation n'a pas ete honoree : on replanifie un retour via
        l'ExternalEvent (changer de vue exige le contexte API Revit).
        """
        if not self._actif or self._retour_en_cours:
            return
        try:
            from pyrevit import HOST_APP as _HOST
            uidoc = _HOST.uidoc
            if uidoc is None or self._vue_id is None:
                return
            courante = uidoc.ActiveView
            if courante is None or courante.Id.IntegerValue == self._vue_id:
                return

            self._retour_en_cours = True
            _self = [self]

            def _action():
                try:
                    _self[0]._revenir_vue_mode()
                finally:
                    _self[0]._retour_en_cours = False

            self._action_handler.planifier(_action)
            self._ext_event.Raise()
        except Exception as ex:
            self._retour_en_cours = False
            self._diag_vue = u"repli KO : {}".format(str(ex))

    def _revenir_vue_mode(self):
        """Reactive la vue du mode (thread Revit API)."""
        try:
            from pyrevit import HOST_APP as _HOST
            from Autodesk.Revit.DB import ElementId as _ElementId
            uidoc = _HOST.uidoc
            if uidoc is None or self._vue_id is None:
                return
            vue = uidoc.Document.GetElement(_ElementId(self._vue_id))
            if vue is None:
                return
            uidoc.ActiveView = vue
            self._diag_vue = u"retour forcé"
            self._log(
                u"⛔ Changement de vue bloqué.\n"
                u"Désactivez l'édition pour changer de vue."
            )
        except Exception as ex:
            self._diag_vue = u"retour KO : {}".format(str(ex))
            self._log(u"⚠ Impossible de revenir sur « {} » : {}".format(
                self._nom_vue, str(ex)))

    # ------------------------------------------------------------------
    # Fichier de recuperation
    # ------------------------------------------------------------------

    def _chemin_recuperation(self, doc):
        """Chemin du fichier d'etat, propre au document courant."""
        try:
            import os          # local : globals du module vides en callback
            import re
            import tempfile
            cle = doc.PathName or doc.Title or u"sans-nom"
            nom = re.sub(r'[^A-Za-z0-9_-]', u'_', cle)[-60:]
            return os.path.join(tempfile.gettempdir(),
                                u"NM-BATII_mode-limites_{}.json".format(nom))
        except Exception:
            return None

    def _ecrire_recuperation(self, doc, ids):
        try:
            import json
            import io
            chemin = self._chemin_recuperation(doc)
            if not chemin:
                return
            donnees = {
                'document': doc.PathName or doc.Title or u"",
                'vue': self._nom_vue,
                'ids': list(ids),
            }
            texte = json.dumps(donnees, ensure_ascii=False)
            if isinstance(texte, bytes):        # str en IronPython 2.7
                texte = texte.decode('utf-8')
            with io.open(chemin, 'w', encoding='utf-8') as f:
                f.write(texte)
        except Exception:
            pass   # la recuperation est un filet de securite, jamais bloquante

    def _effacer_recuperation(self, doc):
        try:
            import os          # local : globals du module vides en callback
            chemin = self._chemin_recuperation(doc)
            if chemin and os.path.exists(chemin):
                os.remove(chemin)
        except Exception:
            pass

    def _verifier_recuperation(self):
        """
        Detecte un mode precedent non desactive (crash, palette tuee) et
        propose de dépingler les elements restes epingles.
        """
        try:
            import os          # local : globals du module vides en callback
            import json
            import io
            uidoc, doc, vue = self._contexte()
            if doc is None:
                return
            chemin = self._chemin_recuperation(doc)
            if not chemin or not os.path.exists(chemin):
                return
            with io.open(chemin, 'r', encoding='utf-8') as f:
                donnees = json.loads(f.read())
            ids = [int(i) for i in donnees.get('ids', [])]
            if not ids:
                self._effacer_recuperation(doc)
                return

            from dialogs.dialogs_styles_loader import show_confirm
            reponse = show_confirm(
                u"NM-BATII — Édition des séparateurs de pièces",
                u"Un mode d'édition précédent n'a pas été désactivé "
                u"proprement.\n\n{} élément(s) sont probablement restés "
                u"épinglés dans ce document.\n\nLes dépingler maintenant ?"
                .format(len(ids)),
                yes_label=u"Dépingler",
                no_label=u"Ignorer"
            )
            if not reponse:
                return

            self._ids_epingles = ids
            _self = [self]

            def _action():
                _self[0]._restaurer(recuperation=True)

            self._action_handler.planifier(_action)
            self._ext_event.Raise()

        except Exception:
            pass

    # ------------------------------------------------------------------
    # Affichage
    # ------------------------------------------------------------------

    def _contenu_icone(self, bouton, nom_fichier, libelle=None, taille=22):
        """
        Remplace le contenu d'un bouton par une icone, suivie d'un libelle
        optionnel. Sans libelle, le bouton devient un carre a icone seule et
        c'est son ToolTip qui l'explique.

        L'icone retenue est la variante CLAIRE (icon.dark.png de l'outil natif,
        qui est blanche) : les styles NMButton* ont un fond bleu et un texte
        blanc, une icone noire y serait illisible.

        En cas d'echec, le bouton conserve simplement le libelle defini en
        XAML — un bouton sans icone reste utilisable.
        """
        try:
            from System import Uri
            from System.Windows import Thickness, VerticalAlignment
            from System.Windows.Controls import (
                StackPanel, Image, TextBlock, Orientation)
            from System.Windows.Media.Imaging import (
                BitmapImage, BitmapCacheOption)

            chemin = os.path.join(_HERE, nom_fichier)
            if not os.path.exists(chemin):
                return

            # BeginInit/EndInit + OnLoad : charge l'image en memoire et relache
            # le fichier. Sans cela le PNG reste verrouille tant que la palette
            # vit, ce qui gene toute mise a jour de l'extension.
            bmp = BitmapImage()
            bmp.BeginInit()
            bmp.UriSource = Uri(chemin)
            bmp.CacheOption = BitmapCacheOption.OnLoad
            bmp.EndInit()

            img = Image()
            img.Source = bmp
            img.Width = taille
            img.Height = taille
            img.VerticalAlignment = VerticalAlignment.Center

            if not libelle:
                bouton.Content = img
                return

            img.Margin = Thickness(0, 0, 8, 0)

            txt = TextBlock()
            txt.Text = libelle
            txt.VerticalAlignment = VerticalAlignment.Center

            pile = StackPanel()
            pile.Orientation = Orientation.Horizontal
            pile.Children.Add(img)
            pile.Children.Add(txt)

            bouton.Content = pile
        except Exception:
            pass

    def _appliquer_style(self, controle, cle):
        """
        Applique un style nomme de la feuille partagee.

        La recherche remonte Window -> Application : les styles sont charges
        dans Application.Resources par dialogs_styles_loader.load(). Un style
        introuvable laisse le controle inchange plutot que de lever.
        """
        try:
            style = controle.TryFindResource(cle)
            if style is None:
                from System.Windows import Application
                if Application.Current is not None:
                    style = Application.Current.TryFindResource(cle)
            if style is not None:
                controle.Style = style
        except Exception:
            pass

    def _rafraichir_etat(self):
        """Met a jour le libelle / style du bouton bascule et la ligne d'etat."""
        try:
            # Symboles en echappement plutot qu'en caractere litteral, pour
            # survivre a un editeur qui re-encoderait le fichier :
            #   \U0001F512 cadenas ferme   \U0001F513 cadenas ouvert
            #   ▶ lecture (play)      ✖ croix
            #
            # Couleurs : le BLEU va a l'action proposee, jamais a l'etat en
            # cours. « Activer » est la mise en avant ; une fois le mode arme,
            # « Désactiver » redevient un bouton neutre.
            if self._actif:
                self._etat_texte = u"Mode actif \U0001F512"
                self.btn_bascule.Content = self._LIBELLE_DESACTIVER
                self._appliquer_style(self.btn_bascule, u'NMButtonValide')
            else:
                self._etat_texte = u"Mode inactif \U0001F513"
                self.btn_bascule.Content = self._LIBELLE_ACTIVER
                self._appliquer_style(self.btn_bascule, u'NMButtonAppliquer')

            self.btn_bascule.IsEnabled = True
            self._afficher()
        except Exception:
            pass

    def _log(self, message):
        """
        Ecrit dans le panneau de sortie pyRevit, et NULLE PART ailleurs.

        La palette n'affiche jamais d'erreur : elle doit rester reduite aux
        quatre etats du mode. Les diagnostics partent dans les logs, visibles
        seulement si « Activer les logs des scripts » est coche dans
        01_Parametres (cle activer_logs_scripts de config.json), conformement
        a la convention de l'extension.
        """
        if not message or not self._log_actif:
            return
        try:
            self._output.print_md(message)
        except Exception:
            pass

    def _echec(self, message):
        """
        Anomalie bloquante : journalise la cause ET reactive le bouton.

        Sans la reactivation, le bouton neutralise par basculer() resterait
        grise indefiniment, l'operation n'ayant jamais atteint
        _rafraichir_etat().

        Une fermeture en attente est egalement abandonnee : l'operation ayant
        echoue, le mode reste arme et la palette doit rester ouverte pour que
        l'utilisateur puisse reessayer.
        """
        self._log(message)
        self._fermeture_demandee = False
        try:
            self.btn_bascule.IsEnabled = True
        except Exception:
            pass

    def _afficher(self):
        """Ecrit l'etat courant — seul contenu de la zone de message."""
        try:
            self.txtStatut.Text = self._etat_texte
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Aide
    # ------------------------------------------------------------------

    _AIDE = (
        u"Ce mode protège tout, sauf les séparateurs de pièces.\n\n"
        u"À l'activation :\n"
        u"• tous les autres éléments de la vue sont épinglés — ils restent "
        u"visibles, pour garder le contexte d'alignement, mais ne peuvent "
        u"plus être ni sélectionnés ni déplacés ;\n"
        u"• la sélection des éléments verrouillés, des liens et des fonds de "
        u"plan est coupée ;\n"
        u"• le changement de vue est bloqué : le mode ne protège que la vue "
        u"où il a été activé.\n\n"
        u"À la désactivation, tout revient à l'état d'origine. Seuls les "
        u"éléments épinglés par le script sont dépinglés : vos propres "
        u"épinglages sont préservés.\n\n"
        u"Le bouton à l'icône lance l'outil natif Revit « Séparateur de "
        u"pièces » pour tracer de nouveaux séparateurs."
    )

    def btn_aide_Click(self, sender, args):
        try:
            from dialogs.dialogs_styles_loader import show_alert
            show_alert(u"NM-BATII — Édition des séparateurs", self._AIDE)
        except Exception as ex:
            self._log(u"✖ Aide indisponible : {}".format(str(ex)))

    # ------------------------------------------------------------------
    # Handlers boutons + bascule
    # ------------------------------------------------------------------

    def basculer(self):
        """
        Active si inactif, desactive sinon.

        Point d'entree unique : bouton bascule de la palette ET relance du
        bouton de ruban (raccourci clavier).
        """
        _self = [self]

        # Le try/except est INDISPENSABLE : _ActionHandler.Execute avale les
        # exceptions. Sans lui, une erreur imprevue laissait la palette figee
        # sur « … en cours » sans aucun moyen d'en sortir.
        if self._actif:
            self._etat_texte = u"Désactivation en cours…"

            def _action():
                _self[0]._action_en_attente = False
                try:
                    _self[0]._restaurer()
                except Exception as ex:
                    _self[0]._log(u"✖ Désactivation interrompue : {}".format(str(ex)))
                    _self[0]._rafraichir_etat()
        else:
            self._etat_texte = u"Activation en cours…"

            def _action():
                _self[0]._action_en_attente = False
                try:
                    _self[0]._activer()
                except Exception as ex:
                    _self[0]._log(u"✖ Activation interrompue : {}".format(str(ex)))
                    _self[0]._rafraichir_etat()

        self._afficher()

        # L'epinglage peut durer plusieurs secondes : on neutralise le bouton
        # le temps de l'operation, sinon un second clic enchainerait une
        # bascule parasite. _rafraichir_etat() le reactive a la fin.
        try:
            self.btn_bascule.IsEnabled = False
        except Exception:
            pass

        # Si un outil Revit est actif, l'ExternalEvent ne s'executera qu'a sa
        # fermeture : l'action reste en file et se declenchera d'elle-meme des
        # que l'utilisateur appuiera sur Echap. _surveiller_attente le lui dit.
        #
        # NE PAS retenter d'automatiser cet Echap. Voies mesurees, toutes
        # infructueuses dans cet environnement :
        #   - PostCommand : aucune commande de sortie d'outil parmi les 566
        #     valeurs de PostableCommand ;
        #   - SendKeys.Send : leve « l'application ne gère pas les messages
        #     Windows » (journal hooks absents hors Windows Forms) ;
        #   - SendKeys.SendWait + AppActivate + temporisations : sans effet, le
        #     focus clavier restant sur le bouton WPF de la palette
        #     (diagnostic « focus:Button »).
        # Rendre le focus a la zone de dessin exigerait SetForegroundWindow ou
        # WS_EX_NOACTIVATE, donc du P/Invoke — or le moteur IronPython de
        # pyRevit n'embarque pas ctypes.
        self._action_en_attente = True
        self._action_handler.planifier(_action)
        self._ext_event.Raise()
        self._surveiller_attente()

    def _surveiller_attente(self, delai_ms=1500):
        """
        Detecte une bascule qui ne demarre pas et dit quoi faire.

        Quand un outil Revit est actif, l'ExternalEvent reste en file jusqu'a
        ce que l'utilisateur en sorte. Sans ce message, la palette semblait
        figee sur « … en cours » sans aucune indication.

        REGLAGE DU DELAI — compromis, mesure en conditions reelles :
          2500 ms : trop long, la palette paraissait plantee ;
           600 ms : trop court, Revit ne depeche pas toujours l'ExternalEvent
                    aussi vite meme sans outil actif, et le message
                    « Appuyez sur Échap » s'affichait a tort ;
          1500 ms : retour rapide sans fausse alerte.
        """
        try:
            from System.Windows.Threading import DispatcherTimer, DispatcherPriority
            from System import TimeSpan

            t = DispatcherTimer(DispatcherPriority.Background, self.Dispatcher)
            t.Interval = TimeSpan.FromMilliseconds(delai_ms)

            def _tick(s, e):
                try:
                    t.Stop()
                except Exception:
                    pass
                if self._action_en_attente:
                    # Message court : la zone tient sur UNE ligne sans retour
                    # a la ligne, un texte long y serait tronque.
                    self._etat_texte = u"⏳ Appuyez sur Échap"
                    self._afficher()

            t.Tick += _tick
            t.Start()
            self._timer_attente = t     # garde une reference vivante
        except Exception:
            pass

    def btn_bascule_Click(self, sender, args):
        self.basculer()

    def btn_separateur_Click(self, sender, args):
        """
        Lance l'outil natif Revit « Séparateur de pièces ».

        RoomSeparator est un membre de l'enumeration PostableCommand : il est
        donc reellement postable, contrairement aux identifiants ID_* de la
        barre d'etat. PostCommand est justement prevu pour etre appele depuis
        une fenetre non modale.
        """
        try:
            from pyrevit import HOST_APP as _HOST
            from Autodesk.Revit.UI import RevitCommandId, PostableCommand

            cmd = RevitCommandId.LookupPostableCommandId(
                PostableCommand.RoomSeparator)
            _HOST.uiapp.PostCommand(cmd)
            self._log(u"")   # succes silencieux : l'outil est visible dans Revit
        except Exception as ex:
            self._log(u"✖ Lancement du séparateur impossible : {}".format(str(ex)))

    def _on_closing(self, sender, args):
        """
        Retarde la fermeture tant que le mode est actif.

        Fermer immediatement escamotait la desactivation : la fenetre
        disparaissait avant que le depinglage n'ait lieu, et l'utilisateur ne
        voyait jamais le message. Ici on ANNULE la fermeture, on lance la
        desactivation, et c'est _restaurer() qui refermera une fois fini.

        args est un CancelEventArgs WPF : Cancel y est bien une PROPRIETE,
        contrairement aux evenements Revit ou c'est une methode (voir
        _on_view_activating).
        """
        if not self._actif:
            return                      # rien a defaire : fermeture immediate
        args.Cancel = True
        if not self._fermeture_demandee:
            self._fermeture_demandee = True
            self.basculer()             # declenche la desactivation

    def _fermer_apres_delai(self, delai_ms=1500):
        """Laisse le message de desactivation a l'ecran, puis ferme."""
        try:
            from System.Windows.Threading import DispatcherTimer, DispatcherPriority
            from System import TimeSpan

            t = DispatcherTimer(DispatcherPriority.Background, self.Dispatcher)
            t.Interval = TimeSpan.FromMilliseconds(delai_ms)

            def _tick(s, e):
                try:
                    t.Stop()
                except Exception:
                    pass
                try:
                    self.Close()
                except Exception:
                    pass

            t.Tick += _tick
            t.Start()
            self._timer_fermeture = t   # garde une reference vivante
        except Exception:
            try:
                self.Close()
            except Exception:
                pass

    def _on_closed(self, sender, args):
        """Filet de securite : ne jamais laisser le modele epingle derriere soi."""
        self._ferme = True
        for _t in (self._timer_attente, self._timer_fermeture):
            try:
                if _t is not None:
                    _t.Stop()
            except Exception:
                pass
        if not self._actif:
            self._desabonner_verrou_vue()
            return
        _self = [self]

        def _action():
            _self[0]._restaurer()

        self._action_handler.planifier(_action)
        self._ext_event.Raise()

    # ------------------------------------------------------------------
    # Activation / restauration (thread Revit API)
    # ------------------------------------------------------------------

    def _activer(self):
        """Epingle tout sauf les separateurs de pieces, puis coupe la selection."""
        try:
            import System as _System
            from Autodesk.Revit.DB import (
                FilteredElementCollector as _Collector,
                ElementCategoryFilter    as _CatFilter,
                BuiltInCategory          as _BIC,
                Transaction              as _Transaction,
                ViewPlan                 as _ViewPlan,
            )
        except Exception as ex:
            self._echec(u"✖ Imports Revit indisponibles : {}".format(str(ex)))
            return

        uidoc, doc, vue = self._contexte()
        if doc is None or vue is None:
            self._echec(u"✖ Aucun document ou vue active.")
            return
        if not isinstance(vue, _ViewPlan):
            self._echec(u"✖ La vue active doit être un plan d'étage (Floor Plan).")
            return

        depart = _System.Environment.TickCount

        # Options de selection d'abord : c'est instantane (simple ecriture de
        # propriete) et cela laisse la transaction d'epinglage isolee.
        detail_options = self._neutraliser_options()

        # Le tri par categorie est fait par le FILTRE NATIF (inverted=True) et
        # non dans une boucle Python : sur une vue chargee cela evite 3 appels
        # interop par element (.Category, .Id, .IntegerValue).
        try:
            filtre = _CatFilter(_BIC.OST_RoomSeparationLines, True)
            elements = list(
                _Collector(doc, vue.Id)
                .WhereElementIsNotElementType()
                .WherePasses(filtre)
                .ToElements()
            )
        except Exception as ex:
            self._echec(u"✖ Collecte impossible : {}".format(str(ex)))
            return

        if not elements:
            self._echec(u"Aucun élément à neutraliser dans cette vue.")
            return

        # Une seule boucle, une seule transaction. Le getter Pinned reste
        # indispensable : il protege les elements que VOUS aviez epingles.
        ids = []
        tx = _Transaction(doc, u"NM-BATII — Activer l’édition des séparateurs")
        tx.Start()
        try:
            for el in elements:
                try:
                    if el.Pinned:
                        continue      # deja epingle PAR L'UTILISATEUR : intouchable
                    el.Pinned = True
                    ids.append(el.Id.IntegerValue)
                except Exception:
                    pass              # element systeme / refusant l'epinglage
            tx.Commit()
        except Exception as ex:
            try:
                tx.RollBack()
            except Exception:
                pass
            self._echec(u"✖ Échec de l'épinglage : {}".format(str(ex)))
            return

        duree = abs(_System.Environment.TickCount - depart) / 1000.0

        self._ids_epingles = ids
        self._nom_vue      = vue.Name
        self._vue_id       = vue.Id.IntegerValue
        self._actif        = True

        # Verrouille la vue : plus aucun basculement tant que le mode est actif.
        self._abonner_verrou_vue()

        self._ecrire_recuperation(doc, ids)
        self._rafraichir_etat()

        # Aucun compte-rendu de reussite : la ligne d'etat dit deja « Mode
        # actif ». Seules les anomalies meritent une ligne supplementaire.
        avertissements = []
        if detail_options:
            avertissements.append(detail_options)
        if not self._abonne_vue:
            avertissements.append(u"⚠ Vue non verrouillée — {}".format(
                self._diag_vue or u"cause inconnue"))
        self._log(u"\n".join(avertissements))

    def _lire_option(self, nom):
        """
        Relit une option sur un objet SelectionUIOptions FRAICHEMENT resolu.

        Point clef : re-appeler GetSelectionUIOptions() plutot que relire
        l'objet deja en main. Si la valeur relue a change, l'ecriture est bien
        globale ; si elle n'a pas bouge, c'est que l'on ecrivait sur une copie
        sans effet — et il faut le savoir plutot que de croire l'option coupee.
        """
        try:
            opts = self._options_selection()
            if opts is None:
                return None
            return bool(getattr(opts, nom))
        except Exception:
            return None

    def _appliquer_options(self, cible_par_nom, memoriser):
        """
        Amene chaque option a la valeur voulue, par ecriture de propriete.

        cible_par_nom : dict {nom: valeur booleenne voulue}
        memoriser     : True pour enregistrer les valeurs d'origine (activation)
        Retourne un libelle d'anomalie, ou une chaine vide si tout s'est bien
        passe.
        """
        opts = self._options_selection()
        if opts is None:
            return u"⚠ SelectionUIOptions inaccessible — options non modifiées."

        if memoriser:
            self._options_avant = {}

        details = []

        for nom, voulue in cible_par_nom.items():
            voulue = bool(voulue)
            try:
                avant = bool(getattr(opts, nom))
            except Exception as ex:
                details.append(u"{} lecture KO ({})".format(nom, str(ex)))
                continue

            if memoriser:
                self._options_avant[nom] = avant

            if avant == voulue:
                continue

            # Voie bouton natif : la SEULE qui rafraichisse l'icone de la barre
            # d'etat. Reservee a SelectPinned, la seule dont l'icone compte —
            # chaque option coute une recherche dans l'arbre d'accessibilite.
            if nom in self._CMD_BASCULE and self._basculer_via_ui(nom)[0]:
                if self._lire_option(nom) == voulue:
                    continue
                # Le clic n'a pas produit l'effet attendu : on force la valeur.

            try:
                setattr(opts, nom, voulue)
            except Exception as ex:
                details.append(u"{} écriture KO ({})".format(nom, str(ex)))
                continue
            apres = self._lire_option(nom)
            if apres != voulue:
                details.append(u"{} non appliquée".format(nom))

        # Silence quand tout va bien : la palette doit rester lisible. Seules
        # les anomalies remontent, le detail complet n'interesse personne une
        # fois le mecanisme fiabilise.
        if not details:
            return u""
        return u"⚠ " + u" | ".join(details)

    # ------------------------------------------------------------------
    # Bascule d'une option via le bouton natif de la barre d'etat
    # ------------------------------------------------------------------
    #
    # Ecrire SelectionUIOptions.<option> change l'etat mais Revit ne repeint
    # pas son icone, et aucune API publique ne force ce rafraichissement.
    # PostCommand est exclu : il n'accepte que les membres de l'enum
    # PostableCommand, aucun ne correspondant a ces bascules.
    #
    # On clique donc le bouton reel via UI Automation. Le controle est cible
    # par son AutomationId, qui vaut l'identifiant NUMERIQUE de la commande
    # (RevitCommandId.Id) : ancrage stable et independant de la langue.
    # Verifie en conditions reelles : ID_TOGGLE_ALLOW_PINNED_SELECTION ->
    # « 38520 », ControlType.Button, pattern Invoke.
    #
    # COUT : FindFirst(TreeScope.Descendants) parcourt tout l'arbre de la
    # fenetre Revit. D'ou deux regles issues d'un gel constate en production :
    #   - UNE SEULE option emprunte cette voie (SelectPinned) ;
    #   - le resultat est mis en cache, y compris l'echec, pour ne jamais
    #     refaire la recherche.
    # Ne pas deporter sur un thread de fond : UIA doit alors interroger les
    # fournisseurs d'interface de Revit en cross-thread, ce qui bloque sa vue
    # pendant qu'on travaille. Essaye, mesure, abandonne.

    _CMD_BASCULE = {
        'SelectPinned': 'ID_TOGGLE_ALLOW_PINNED_SELECTION',
    }

    def _element_bascule(self, nom_option):
        """AutomationElement du bouton, resolu une fois puis mis en cache."""
        if nom_option in self._cache_ui:
            return self._cache_ui[nom_option]

        elem = None
        try:
            import clr
            clr.AddReference('UIAutomationClient')
            clr.AddReference('UIAutomationTypes')
            from System.Windows.Automation import (
                AutomationElement, PropertyCondition, TreeScope)
            from pyrevit import HOST_APP as _HOST
            from Autodesk.Revit.UI import RevitCommandId

            rid = RevitCommandId.LookupCommandId(self._CMD_BASCULE[nom_option])
            if rid is not None:
                racine = AutomationElement.FromHandle(_HOST.uiapp.MainWindowHandle)
                cond = PropertyCondition(
                    AutomationElement.AutomationIdProperty, str(rid.Id))
                elem = racine.FindFirst(TreeScope.Descendants, cond)
        except Exception:
            elem = None

        # L'echec est memorise lui aussi : sans cela chaque bascule relancerait
        # un parcours complet de l'arbre, pour rien.
        self._cache_ui[nom_option] = elem
        return elem

    def _basculer_via_ui(self, nom_option):
        """Clique le bouton natif. Retourne (succes, motif)."""
        elem = self._element_bascule(nom_option)
        if elem is None:
            return False, u"bouton introuvable"
        try:
            from System.Windows.Automation import InvokePattern
            elem.GetCurrentPattern(InvokePattern.Pattern).Invoke()
            return True, u"invoqué"
        except Exception as ex:
            self._cache_ui.pop(nom_option, None)   # element obsolete
            return False, u"Invoke KO — {}".format(str(ex))

    def _neutraliser_options(self):
        """Passe les options a False apres avoir memorise leur valeur d'origine."""
        cibles = {}
        for nom in self._OPTIONS_SELECTION:
            cibles[nom] = False
        return self._appliquer_options(cibles, memoriser=True)

    def _restaurer(self, recuperation=False):
        """Depingle ce que le script a epingle et restaure les options."""
        try:
            from Autodesk.Revit.DB import (
                Transaction as _Transaction,
                ElementId   as _ElementId,
            )
        except Exception as ex:
            self._echec(u"✖ Imports Revit indisponibles : {}".format(str(ex)))
            return

        uidoc, doc, vue = self._contexte()
        if doc is None:
            self._echec(u"✖ Aucun document actif.")
            return

        # ORDRE VOLONTAIRE, symetrique de _activer() : les options de selection
        # D'ABORD, hors transaction.
        detail_options = self._restaurer_options()

        ids = list(self._ids_epingles)
        nb_depingles = 0
        nb_absents   = 0

        if ids:
            tx = _Transaction(doc, u"NM-BATII — Désactiver l’édition des séparateurs")
            tx.Start()
            try:
                for eid_int in ids:
                    try:
                        el = doc.GetElement(_ElementId(eid_int))
                        if el is None or not el.IsValidObject:
                            nb_absents += 1
                            continue
                        if el.Pinned:
                            el.Pinned = False
                            nb_depingles += 1
                    except Exception:
                        pass
                tx.Commit()
            except Exception as ex:
                try:
                    tx.RollBack()
                except Exception:
                    pass
                self._echec(u"✖ Échec du dépinglage : {}".format(str(ex)))
                return

        # Libere la vue AVANT de retomber a l'etat inactif.
        self._desabonner_verrou_vue()

        self._ids_epingles = []
        self._vue_id       = None
        self._actif        = False
        self._effacer_recuperation(doc)
        self._rafraichir_etat()

        # Comme a l'activation : rien a dire quand tout s'est bien passe.
        # La recuperation, elle, est un evenement rare qui merite un mot.
        anomalies = []
        if recuperation:
            anomalies.append(u"Récupération terminée — {} éléments libérés.".format(
                nb_depingles))
        if nb_absents:
            anomalies.append(u"{} élément(s) supprimés depuis l'activation.".format(
                nb_absents))
        if detail_options:
            anomalies.append(detail_options)
        self._log(u"\n".join(anomalies))

        # Fermeture mise en attente par _on_closing : le mode est desarme, on
        # laisse « Mode inactif » a l'ecran un instant avant de refermer.
        if self._fermeture_demandee:
            self._fermer_apres_delai()

    def _restaurer_options(self):
        """
        Remet les options exactement dans l'etat d'avant l'activation.

        On rejoue les valeurs memorisees a l'activation, pas des valeurs
        supposees : si « Sélectionner des éléments verrouillés » etait deja
        decochee avant le mode, elle le reste apres.
        """
        if not self._options_avant:
            return u""
        cibles = dict(self._options_avant)
        detail = self._appliquer_options(cibles, memoriser=False)
        self._options_avant = {}
        # _appliquer_options ne rend une chaine que s'il y a une anomalie.
        return (u"Restauration : " + detail) if detail else u""


# ── Singleton inter-lancements ───────────────────────────────────────────────
#
# Permet d'affecter un RACCOURCI CLAVIER Revit a ce bouton et de s'en servir
# comme bascule du MODE (et non comme simple ouverture de fenetre) : chaque
# appui active ou desactive.
#
# L'etat vit dans un module artificiel de sys.modules : contrairement aux
# globals du script (vides apres Execute()), sys.modules survit a la session.

_CLE_ETAT = '__nm_batii_edition_separateurs_etat__'


def _etat_partage():
    """Retourne le module-conteneur d'etat, cree au premier appel."""
    import sys as _sys
    etat = _sys.modules.get(_CLE_ETAT)
    if etat is None:
        import imp
        etat = imp.new_module(_CLE_ETAT)
        etat.palette = None
        _sys.modules[_CLE_ETAT] = etat
    return etat


# ── Corps du script ──────────────────────────────────────────────────────────

try:
    _etat = _etat_partage()
    _existante = getattr(_etat, 'palette', None)

    _vivante = False
    if _existante is not None:
        try:
            _vivante = not _existante._ferme
        except Exception:
            _vivante = False

    if _vivante:
        # Palette deja ouverte : le bouton (ou son raccourci) bascule le mode.
        _existante.basculer()
        try:
            _existante.Activate()
        except Exception:
            pass
    else:
        # Premiere ouverture : la palette s'ouvre ET le mode s'arme aussitot,
        # pour que le raccourci clavier se comporte des le premier appui comme
        # une bascule du mode et non comme une simple ouverture de fenetre.
        _palette = FenetreMode()
        _set_revit_owner(_palette)
        _etat.palette = _palette
        _palette.Show()
        _palette.basculer()

except Exception as e:
    try:
        from dialogs.dialogs_styles_loader import show_alert
        show_alert(u"NM-BATII — Échec", u"Erreur : {}".format(str(e)))
    except Exception:
        pass
