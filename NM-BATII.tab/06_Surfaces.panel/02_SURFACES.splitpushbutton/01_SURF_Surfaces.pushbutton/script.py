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


#__title__ = 'Surfaces'
#__author__ = 'data8bim (d8b)'


"""
NM-BATII — Palette d'attribution des cles de style aux surfaces.

But : remplacer l'aller-retour « selectionner une surface → ouvrir les
proprietes → derouler la liste de la cle de style » par un clic unique, et
faire de la pose d'une nouvelle surface une operation deja stylee.

Source des styles :
  Une nomenclature de CLES (Key Schedule) du projet — « SURFACES  - 1 - Tables
  de style » par defaut — dont chaque ligne est un style. Trois colonnes sont
  exploitees, toutes parametrables dans 01_Parametres > Surfaces :
    - le nom de la cle          → libelle du bouton ;
    - la colonne « type de calcul » (« ANS - SURFACE - Calcul ») → range chaque
      style sous un calcul reglementaire (SP, SHON/SHOB, CBS...), c'est le
      filtre de la liste deroulante ;
    - la colonne « commentaire » (« Commentaires ») → infobulle du bouton.
  Le parametre de cle porte par les surfaces (« SURFACE - Style ») est ecrit
  avec l'ElementId de la ligne : c'est ainsi qu'une nomenclature de cles se
  renseigne par l'API. Le cas d'un parametre TEXTE est neanmoins gere, un
  projet pouvant avoir converti la table en simple liste de valeurs.

Perimetre : la palette ne vit que dans une vue de la famille systeme « Plan de
surface ». Le bouton du ruban est grise ailleurs (« context: active-area-plan »
du bundle.yaml), et la palette se ferme d'elle-meme si l'utilisateur active une
autre vue (voir _on_view_activated). Passer d'un plan de surface a un autre ne
la ferme pas : elle se recale sur le type de calcul de la nouvelle vue.

Le type de calcul est deduit de la vue active — d'abord par le nom de son AREA
SCHEME, puis, a defaut, par le nom de son TYPE de vue (voir
_candidats_type_calcul).

Deux parcours, selon qu'une surface est selectionnee ou non :
  - selection non vide  → le style est applique aux surfaces selectionnees ;
  - selection vide      → l'outil natif Revit « Surface » est lance, et TOUTES
    les surfaces posees jusqu'a Echap recoivent le style (voir _demarrer_pose).

Pourquoi la pose n'est stylee qu'a la sortie de l'outil : Revit ne depeche un
ExternalEvent que lorsque aucune commande n'est active. Les surfaces creees sont
donc mises en file, puis toutes ecrites d'un coup quand l'utilisateur quitte
l'outil. Ecrire au fil de l'eau supposerait d'ouvrir une transaction pendant une
commande Revit : ni possible, ni souhaitable.

Corollaire direct — LES LOTS. Comme rien n'est ecrit avant que Revit ne rende la
main, cliquer un autre style en cours de pose ne peut pas se contenter de
« changer le style courant » : les surfaces deja posees attendent encore. La file
est donc decoupee en LOTS, un par style clique (self._lots). Chaque lot conserve
son style, et tous sont ecrits ensemble. Une file unique remise a zero a chaque
changement de style — la premiere version — laissait les surfaces du style
precedent sans aucune valeur.

Second corollaire — LE MODE POSE EST PERSISTANT. Cliquer sur la palette fait
rendre la main a l'outil « Surface » (le focus quitte Revit), donc declenche une
ecriture. Tant que _vider_lots() en profitait pour desarmer la surveillance, la
commande repostee redemarrait dans le vide : plus rien n'ecoutait, et les
surfaces posees apres le changement de style restaient sans valeur. Le mode ne
s'arrete donc que sur : action sur une selection preexistante, changement de vue,
fermeture de la palette.

PAS DE BOUTON D'ARRET DANS LA PALETTE, volontairement. C'est ECHAP, dans Revit,
qui met fin au placement. Une version precedente offrait un bouton ✖ qui tentait
de quitter l'outil en simulant Echap : aucune API Revit ne permet d'interrompre
la commande active (les 567 membres de PostableCommand ne comportent ni Modify
ni Cancel, et RevitAPIUI n'expose rien de tel), et la frappe simulee obligeait a
rendre d'abord le focus a Revit — ce qui le lui retirait au passage. Voie
abandonnee.

La sortie de l'outil n'est pas non plus observable directement : ni l'etat de la
commande active, ni la frappe d'Echap ne sont exposes. Elle est DEDUITE de
l'emission d'Idling, que Revit suspend tant qu'une commande tourne — voir
_surveiller_fin_de_pose. Le mode se clot donc de lui-meme peu apres Echap, et la
zone d'etat revient a son invite de depart.

COMMENT LES SURFACES SONT RATTACHEES A UN LOT. Le mecanisme principal est une
COMPARAISON D'INVENTAIRE (_capturer_nouvelles_surfaces) : une photo des surfaces
du document est prise au demarrage de la pose, et rejouee a chaque POINT DE
CONTROLE — changement de style, arret du mode, fermeture de la palette — plus
periodiquement sur Idling. Tout ce qui est apparu depuis la photo precedente
appartient au lot en cours a ce moment-la.

Le point capital est que la capture ait lieu AU MOMENT du changement de style, et
non seulement sur Idling : Idling n'est pas emis tant qu'une commande Revit est
active, si bien que les surfaces posees sous un style etaient encore invisibles
quand l'utilisateur en choisissait un autre, et finissaient rangees sous le
mauvais. C'est exactement le defaut observe en production.

L'evenement DocumentChanged reste branche quand il le peut : il rattache chaque
surface des sa creation, donc plus finement. Mais il n'est pas garanti — sur
certaines installations son abonnement leve une TargetInvocationException — et
rien ne doit en dependre. Son echec est journalise avec l'InnerException, seule
a porter le motif reel.

Aucune exception n'est avalee en silence, et les comptes rendus ont leur propre
zone (_message), distincte du bandeau de selection (_selection) que Idling
reecrit plusieurs fois par seconde — c'est la regle de
[[palette-non-modale-globals-ironpython]].

Contraintes techniques d'une fenetre non modale : voir
[[palette-non-modale-globals-ironpython]] — apres le retour de
IExternalCommand.Execute() IronPython vide les globals du module. Tout ce qu'un
callback utilise doit etre une methode, un attribut d'instance, ou un import
fait en local. C'est la raison des imports repetes en tete de chaque methode :
ils ne sont pas redondants, ils sont la seule liaison de nom qui survit.
"""

import os
import sys

from pyrevit import forms
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent

_HERE = os.path.dirname(__file__)


def _dossier_lib():
    """<extension>/lib, trouve en REMONTANT jusqu'au dossier .extension.

    Et non par un nombre de « .. » en dur : celui-ci depend de la profondeur du
    bouton dans le ruban, et se casse en silence des qu'on le range dans un
    pulldown ou un splitpushbutton — ce qui est arrive en deplacant ce bouton
    sous 02_SURFACES.splitpushbutton.
    """
    courant = os.path.dirname(os.path.abspath(__file__))
    while not courant.lower().endswith('.extension'):
        parent = os.path.dirname(courant)
        if parent == courant:
            return None
        courant = parent
    return os.path.join(courant, 'lib')


_lib = _dossier_lib()
if _lib and _lib not in sys.path:
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

    Pattern obligatoire pour les fenetres non modales : ecrire un parametre
    ouvre une transaction, impossible depuis le thread WPF.
    """

    def __init__(self):
        self._fn     = [None]   # mutable — pas de nonlocal en IronPython 2.7
        self._erreur = [None]   # dernier echec, pour l'afficher cote palette

    def planifier(self, fn):
        self._fn[0] = fn

    def Execute(self, uiapp):
        fn = self._fn[0]
        self._fn[0] = None
        if fn:
            try:
                fn()
            except Exception:
                # NE PAS avaler : une action planifiee qui echoue ici est
                # invisible partout ailleurs — c'est le piege decrit dans
                # [[palette-non-modale-globals-ironpython]]. La trace est
                # deposee pour que la palette la relise et l'affiche.
                import traceback
                self._erreur[0] = traceback.format_exc()

    def dernier_echec(self):
        """Recupere et efface la derniere trace d'erreur."""
        trace = self._erreur[0]
        self._erreur[0] = None
        return trace

    def GetName(self):
        return u"NM-BATII — Surfaces"


_action_handler = _ActionHandler()
_ext_event      = ExternalEvent.Create(_action_handler)


# ── Palette principale ───────────────────────────────────────────────────────

class FenetreStyles(forms.WPFWindow):
    """Palette non modale : liste des cles de style, filtree par type de calcul."""

    def __init__(self):
        # handle_esc=False : par defaut forms.WPFWindow branche PreviewKeyDown et
        # FERME la fenetre sur Echap. Or Echap est ici la touche qui met fin a
        # l'outil « Surface » de Revit, et la palette a souvent le focus a ce
        # moment-la. Sans ce parametre, sortir de l'outil fermait la palette —
        # donc annulait la pose stylee en cours.
        from pyrevit.forms import WPFWindow as _W
        _W.__init__(self, os.path.join(_HERE, 'WPFWindow.xaml'), handle_esc=False)

        # Dossier du bouton, capture MAINTENANT. __file__ et _HERE sont des
        # globals du module, et pyRevit vide les globals des le retour
        # d'Execute() : un callback de la palette qui les lirait leverait
        # NameError. C'est ce qui rendait le bouton « engrenage » muet.
        self._ici = os.path.dirname(os.path.abspath(__file__))

        from pyrevit import HOST_APP as _HOST

        self._action_handler = _action_handler
        self._ext_event      = _ext_event

        # ── Contexte Revit, capture pendant Execute() (globals encore vivants).
        # Le document est fige ici — il sert de reference pour filtrer
        # DocumentChanged et pour la transaction —, mais l'UIDocument est
        # toujours relu via self._uiapp.ActiveUIDocument : c'est lui qui porte
        # la selection, et la vue active peut changer sous la palette.
        self._uiapp = _HOST.uiapp
        self._doc   = _HOST.doc
        self._app   = self._doc.Application

        # ── Etat — tout porte par l'instance
        self._ferme          = False
        self._styles         = []      # dicts {nom, calcul, commentaire, id}
        self._erreur_table   = u""
        self._pose_active    = False
        self._abonne_doc     = False
        self._abonne_idling  = False
        self._style_pose     = None    # style du lot ouvert
        # Lots de pose : [{'style': <dict style>, 'ids': [ElementId, ...]}, ...]
        # Un lot PAR style clique. Une file unique perdait les surfaces posees
        # sous le style precedent des que l'utilisateur en choisissait un autre
        # sans etre sorti de l'outil (l'ExternalEvent n'ayant pas encore pu etre
        # depeche, rien n'avait ete ecrit).
        self._lots           = []
        self._sig_selection  = None    # signature de la derniere selection lue
        self._forcer_relecture = False # relire sans degeler (apres ecriture)
        # Zone d'etat unique : trois sources, une priorite (_rafraichir_message)
        self._txt_selection  = None    # etat derive de la selection
        self._txt_pose       = None    # etat du mode pose
        self._dernier_etat   = None    # dernier texte reellement affiche
        self._msg_gele       = None    # compte rendu / erreur imposant la zone
        self._msg_gele_t     = None
        self._msg_gele_duree = None
        self._ids_avant      = None    # photo des surfaces avant la pose
        self._dernier_scan   = None    # bride du detecteur de repli
        self._derniere_activite = None # dernier signe de vie de l'outil de pose

        # Handlers .NET conserves tels quels : en IronPython, `self.methode`
        # fabrique un nouvel objet a chaque acces, et un `-=` sur un objet
        # different ne desabonne rien. Une seule reference, gardee ici.
        self._h_doc_changed    = self._on_doc_changed
        self._h_idling         = self._on_idling
        self._h_view_activated = self._on_view_activated
        self._abonne_vue       = False

        # ── Logs pyRevit — convention de l'extension : rien ne s'affiche si
        # « Activer les logs des scripts » est decoche dans 01_Parametres.
        #
        # DEUX consoles apparaissaient, et c'est propre aux palettes : pyRevit
        # en ouvre une pour la duree de l'execution du script, mais la palette
        # survit a `Execute()`. Un log ecrit plus tard depuis un callback ne
        # retrouve donc plus cette console-la et en ouvre une SECONDE, durable.
        # La premiere ne recevait que les quelques lignes de __init__.
        #
        # La console d'execution est donc fermee d'entree par le corps du
        # script, et les messages de demarrage sont mis de cote : _ouvrir_journal
        # les reverse dans la console durable au premier Idling, soit juste
        # apres la fin du script. Une seule fenetre, sans rien perdre au passage.
        self._log_actif    = False
        self._output       = None
        self._sortie_prete = False
        self._journal      = []
        try:
            from utils.config_loader import load_config
            self._log_actif = bool(load_config().get('activer_logs_scripts', False))
        except Exception:
            pass

        self._lire_config()
        self._charger_table()

        # Etat initial de la case AVANT l'abonnement : la poser ensuite
        # declencherait Checked/Unchecked, donc une reecriture de config.json au
        # simple lancement de la palette.
        self.chkEtiqueter.IsChecked  = self._etiq_actif
        self.cboEtiquette.IsEnabled  = self._etiq_actif
        self.chkRepere.IsEnabled     = self._etiq_actif
        # Verrou de reconstruction de la liste des etiquettes (voir
        # _maj_liste_etiquettes). Pose ici pour que les callbacks n'aient
        # jamais a le decouvrir absent.
        self._maj_etiq = False

        self.cboCalcul.SelectionChanged += self.cbo_calcul_change
        self.txtRecherche.TextChanged    += self.txt_recherche_change
        self.btnEffacer.Click            += self.btn_effacer_click
        self.btnAide.Click               += self.btn_aide_click
        self.btnConfig.Click             += self.btn_config_click
        self.chkEtiqueter.Checked        += self.chk_etiqueter_change
        self.chkEtiqueter.Unchecked      += self.chk_etiqueter_change
        self.cboEtiquette.SelectionChanged += self.cbo_etiquette_change
        self.Closed                      += self._on_closed
        self.Loaded                      += self._on_loaded

        self._remplir_calculs()
        self._synchroniser_type_calcul()
        self._maj_liste_etiquettes()
        self._abonner_idling()
        self._abonner_vue()

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def _lire_config(self):
        """Lit la section « surface » de config.json (noms de table et colonnes)."""
        cfg = {}
        try:
            from utils.config_loader import load_config
            cfg = load_config().get('surface', {}) or {}
        except Exception:
            cfg = {}
        self._nom_table      = cfg.get('table_styles_schedule', u'') or u''
        self._param_style    = cfg.get('param_style', u'') or u''
        self._col_calcul     = cfg.get('col_calcul_style', u'') or u''

        # Ordre et couleurs des boutons — regles dans 01_Parametres, stockes
        # dans config.json et NON dans la nomenclature : les projets existants
        # n'ont pas de colonne d'ordre, et leur en ajouter une serait
        # irrealiste. L'identification se fait sur le seul nom de cle.
        # { nom : (rang, couleur) } ; le rang est la position dans la liste.
        # Couleurs de PLAN, pour le choix de couleurs Revit — a ne pas
        # confondre avec le repere du bouton ci-dessus, qui code l'article
        # reglementaire. Voir _colorer_schemas.
        self._couleurs_plan = {}
        self._motifs_plan   = {}
        self._reglages_styles = {}
        # None = pas encore lu ; renseigne a la premiere pastille dessinee.
        self._infos_motifs  = None
        try:
            rang = 0
            for e in (cfg.get('styles_palette', []) or []):
                nom = (e.get('nom') or u'').strip()
                if not nom or nom in self._reglages_styles:
                    continue
                self._reglages_styles[nom] = (rang,
                                              (e.get('couleur') or u'').strip())
                plan = (e.get('couleur_plan') or u'').strip()
                if plan:
                    self._couleurs_plan[nom] = plan
                motif = (e.get('motif_plan') or u'').strip()
                if motif:
                    self._motifs_plan[nom] = motif
                rang += 1
        except Exception as ex:
            # Reglage illisible : la palette retombe sur l'ordre alphabetique
            # sans couleur, plutot que de ne pas s'ouvrir.
            self._reglages_styles = {}
            self._couleurs_plan = {}
            self._motifs_plan = {}
            self._log(u"⚠ Ordre des styles illisible : {0}".format(ex))
        # « Commentaires » est le nom francais du parametre natif de commentaire
        # d'occurrence : defaut raisonnable, mais la colonne reste parametrable.
        self._col_commentaire = cfg.get('col_commentaire_style', u'') or u'Commentaires'

        # Etiquetage. Le mappage se regle dans 01_Parametres et vaut referentiel ;
        # l'interrupteur, lui, est la case de la palette — la decision se prend
        # en travaillant. Identification par « Famille : Type » et non par
        # ElementId, meme raison que pour les couleurs et les motifs.
        self._etiq_actif      = bool(cfg.get('etiquettes_actif', False))
        self._etiq_defaut     = {u'etiquette': u'', u'repere': False}
        self._etiq_par_calcul = {}
        try:
            d = cfg.get('etiquette_defaut')
            if isinstance(d, dict):
                self._etiq_defaut = {
                    u'etiquette': (d.get('etiquette') or u'').strip(),
                    u'repere':    bool(d.get('repere')),
                }
            for e in (cfg.get('etiquettes_par_calcul', []) or []):
                if not isinstance(e, dict):
                    continue
                calcul = (e.get('calcul') or u'').strip()
                nom    = (e.get('etiquette') or u'').strip()
                repere = bool(e.get('repere'))
                # Meme regle que dans les parametres : une ligne de repere sans
                # etiquette est un reglage valable. Filtrer differemment ici
                # ferait diverger ce que la palette applique de ce que le
                # dialogue affiche.
                if calcul and (nom or repere):
                    self._etiq_par_calcul[calcul] = {u'etiquette': nom,
                                                     u'repere':    repere}
        except Exception as ex:
            # Mappage illisible : la palette continue sans etiqueter, plutot
            # que de ne pas s'ouvrir.
            self._etiq_defaut     = {u'etiquette': u'', u'repere': False}
            self._etiq_par_calcul = {}
            self._log(u"⚠ Mappage des étiquettes illisible : {0}".format(ex))

    # ------------------------------------------------------------------
    # Lecture de la table de style
    # ------------------------------------------------------------------

    def _charger_table(self):
        """
        Remplit self._styles depuis la nomenclature de cles configuree.

        Les lignes d'une nomenclature de cles sont de vrais elements du modele :
        elles se recuperent avec un collecteur BORNE A LA VUE de la nomenclature
        (FilteredElementCollector(doc, vue.Id)). C'est la seule voie qui rend
        l'ElementId de chaque ligne — indispensable, puisque c'est cet id qui
        s'ecrit dans le parametre de cle des surfaces. Lire les cellules du
        tableau (GetTableData) ne donnerait que du texte.
        """
        from Autodesk.Revit.DB import (FilteredElementCollector, ViewSchedule,
                                       Element, BuiltInParameter, ElementId)

        self._styles       = []
        self._erreur_table = u""
        # Parametres alimentes par la table, pour « Effacer le style ».
        self._colonnes_table = []

        if not self._nom_table:
            self._erreur_table = (
                u"Aucune table de style déclarée. Renseignez-la dans "
                u"« Paramètres > Surfaces > Table de style des surfaces ».")
            return
        if not self._param_style:
            self._erreur_table = (
                u"Aucun paramètre de clé de style déclaré. Renseignez-le dans "
                u"« Paramètres > Surfaces > Table de style des surfaces ».")
            return

        vue = None
        for vs in FilteredElementCollector(self._doc).OfClass(ViewSchedule):
            try:
                nom = vs.Name
            except Exception:
                nom = Element.Name.__get__(vs)
            if nom == self._nom_table:
                vue = vs
                break

        if vue is None:
            self._erreur_table = (
                u"Nomenclature introuvable dans le projet :\n« {0} ».".format(
                    self._nom_table))
            return

        try:
            est_cles = bool(vue.Definition.IsKeySchedule)
        except Exception:
            est_cles = False
        if not est_cles:
            # Non bloquant : le parcours « parametre texte » reste possible.
            self._log(u"⚠ « {0} » n'est pas une nomenclature de clés.".format(
                self._nom_table))

        # Colonnes de la table, cote parametres. Poser une cle fait RECOPIER par
        # Revit la valeur de chaque colonne dans le parametre de meme nom sur la
        # surface ; « Effacer le style » doit donc savoir lesquels vider.
        # Les champs calcules et combines n'ont pas de parametre derriere eux.
        try:
            definition = vue.Definition
            for i in range(definition.GetFieldCount()):
                champ = definition.GetField(i)
                try:
                    if champ.IsCalculatedField or champ.IsCombinedParameterField:
                        continue
                except Exception:
                    pass
                try:
                    pid = champ.ParameterId
                except Exception:
                    continue
                if pid is None or pid == ElementId.InvalidElementId:
                    continue
                try:
                    nom_col = champ.GetName()
                except Exception:
                    nom_col = u''
                self._colonnes_table.append((pid, nom_col))
            # Les colonnes sont NOMMEES dans le journal, pas seulement comptees :
            # c'est la liste exacte de ce que « Effacer le style » videra, et le
            # seul moyen de le verifier sans ouvrir la nomenclature.
            self._log(u"▶ {0} colonne(s) de valeurs dans « {1} » : {2}".format(
                len(self._colonnes_table), self._nom_table,
                u", ".join(u"« {0} »".format(n or u'?')
                           for _pid, n in self._colonnes_table)))
        except Exception as ex:
            # Non bloquant : sans les colonnes, « Effacer le style » se contente
            # de vider la cle, comme avant.
            self._colonnes_table = []
            self._log(u"⚠ Colonnes de la table illisibles : {0}".format(ex))

        for elem in FilteredElementCollector(self._doc, vue.Id).ToElements():
            try:
                # Element.Name est implemente en interface explicite : sur
                # certains types, elem.Name leve AttributeError en IronPython.
                nom = Element.Name.__get__(elem)
            except Exception:
                continue
            if not nom:
                continue

            calcul = self._valeur_texte(elem, self._col_calcul)
            comm   = self._valeur_texte(elem, self._col_commentaire)
            if not comm:
                # Repli sur le parametre natif de commentaire : un projet peut
                # avoir laisse la colonne configuree vide.
                try:
                    p = elem.get_Parameter(
                        BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
                    comm = p.AsString() if p is not None else u""
                except Exception:
                    comm = u""

            self._styles.append({
                'nom':         nom,
                'calcul':      calcul or u"",
                'commentaire': comm or u"",
                'id':          elem.Id,
            })

        # Tri : d'abord le type de calcul (la palette filtre dessus), puis le
        # rang defini dans les parametres. Un style non classe passe apres les
        # classes, par ordre alphabetique — un reglage partiel reste donc
        # utilisable, et rien ne disparait faute d'avoir ete range.
        _NON_CLASSE = 10 ** 9

        def _cle_tri(s):
            reglage = self._reglages_styles.get(s['nom'])
            rang = reglage[0] if reglage else _NON_CLASSE
            return (s['calcul'].lower(), rang, s['nom'].lower())

        self._styles.sort(key=_cle_tri)

        if not self._styles:
            self._erreur_table = (
                u"La nomenclature « {0} » ne contient aucune ligne "
                u"exploitable.".format(self._nom_table))

    def _valeur_texte(self, elem, nom_param):
        """Valeur texte d'un parametre, quelle que soit sa nature de stockage."""
        from Autodesk.Revit.DB import StorageType
        if not nom_param:
            return u""
        try:
            p = elem.LookupParameter(nom_param)
            if p is None:
                return u""
            if p.StorageType == StorageType.String:
                return p.AsString() or u""
            return p.AsValueString() or u""
        except Exception:
            return u""

    # ------------------------------------------------------------------
    # Construction de l'interface
    # ------------------------------------------------------------------

    _TOUS = u"< Tous les types >"

    def _remplir_calculs(self):
        """
        Alimente la liste deroulante avec les types de calcul rencontres.

        Tri alphabetique, volontairement : la liste n'est plus parcourue a la
        main depuis que _synchroniser_type_calcul la cale sur le plan de surface
        actif. Un ordre metier configurable a existe ici, il a ete retire faute
        d'usage — l'ordre alphabetique rend simplement une valeur trouvable.
        """
        try:
            valeurs = []
            for s in self._styles:
                if s['calcul'] and s['calcul'] not in valeurs:
                    valeurs.append(s['calcul'])
            valeurs.sort(key=lambda v: v.lower())

            self.cboCalcul.Items.Clear()
            self.cboCalcul.Items.Add(self._TOUS)
            for v in valeurs:
                self.cboCalcul.Items.Add(v)
            # Un seul type de calcul : le presenter d'emblee plutot que
            # d'obliger a le choisir dans une liste a une entree utile.
            self.cboCalcul.SelectedIndex = 1 if len(valeurs) == 1 else 0
        except Exception as ex:
            self._echec(u"Liste des types de calcul indisponible : {0}".format(ex))

        self._reconstruire_boutons()

    # ------------------------------------------------------------------
    # Synchronisation avec le plan de surface actif
    # ------------------------------------------------------------------

    def _normaliser(self, texte):
        """Clef de comparaison souple : casse, espaces et accents ecartes."""
        if not texte:
            return u""
        # import DANS le try : unicodedata est present dans l'IronPython de
        # pyRevit, mais son absence ne doit pas couter la comparaison — sans
        # accents, elle reste juste un peu plus stricte.
        try:
            import unicodedata
            plat = unicodedata.normalize('NFKD', texte)
            plat = u"".join(c for c in plat if not unicodedata.combining(c))
        except Exception:
            plat = texte
        return u" ".join(plat.split()).strip().lower()

    def _candidats_type_calcul(self, vue):
        """
        Noms susceptibles de designer le type de calcul de la vue, par ordre de
        preference.

        1. Le nom de l'AREA SCHEME de la vue. C'est le porteur SEMANTIQUE :
           une surface appartient a un et un seul schema, et c'est lui qui
           determine ce que la vue peut contenir. Un nom de type de vue, lui,
           n'est qu'une convention de nommage, que n'importe qui peut renommer
           sans consequence pour Revit.
        2. Le nom du TYPE de la vue (ViewFamilyType) — la convention en place
           dans le projet actuel, conservee en repli.

        Renvoyer les deux et laisser l'appelant retenir celui qui correspond
        evite d'avoir a trancher : si les schemas portent les noms Revit par
        defaut, seul le nom de type correspondra, et inversement.
        """
        from Autodesk.Revit.DB import Element
        noms = []
        try:
            schema = vue.AreaScheme
            if schema is not None:
                noms.append(Element.Name.__get__(schema))
        except Exception:
            pass
        try:
            vft = self._doc.GetElement(vue.GetTypeId())
            if vft is not None:
                noms.append(Element.Name.__get__(vft))
        except Exception:
            pass
        return [n for n in noms if n]

    def _synchroniser_type_calcul(self, vue=None):
        """Cale la liste deroulante sur le type de calcul du plan de surface actif."""
        try:
            if vue is None:
                vue = self._uiapp.ActiveUIDocument.ActiveView
            if vue is None:
                return

            candidats = self._candidats_type_calcul(vue)
            if not candidats:
                return

            # Index des entrees de la liste, hors « Tous les types ».
            entrees = {}
            for i in range(self.cboCalcul.Items.Count):
                item = self.cboCalcul.Items[i]
                if item == self._TOUS:
                    continue
                entrees[self._normaliser(item)] = i

            for nom in candidats:
                idx = entrees.get(self._normaliser(nom))
                if idx is not None:
                    if self.cboCalcul.SelectedIndex != idx:
                        self.cboCalcul.SelectedIndex = idx
                    self._log(u"▶ Type de calcul calé sur « {0} » d'après la "
                              u"vue.".format(nom))
                    return

            self._log(u"⚠ Aucun type de calcul ne correspond à la vue "
                      u"(essayé : {0}).".format(u", ".join(candidats)))
        except Exception as ex:
            self._log(u"⚠ Synchronisation du type de calcul impossible : "
                      u"{0}".format(ex))

    def _reconstruire_boutons(self):
        """Recree les boutons de style selon le type de calcul et la recherche."""
        from System.Windows.Controls import Button, TextBlock
        from System.Windows import Thickness, HorizontalAlignment, TextWrapping

        try:
            self.pnlStyles.Children.Clear()
        except Exception:
            return

        if self._erreur_table:
            msg = TextBlock()
            msg.Text = self._erreur_table
            msg.TextWrapping = TextWrapping.Wrap
            msg.FontSize = 12
            msg.Margin = Thickness(6)
            self.pnlStyles.Children.Add(msg)
            return

        calcul = None
        try:
            sel = self.cboCalcul.SelectedItem
            if sel is not None and sel != self._TOUS:
                calcul = sel
        except Exception:
            calcul = None

        recherche = u""
        try:
            recherche = (self.txtRecherche.Text or u"").strip().lower()
        except Exception:
            recherche = u""
        try:
            from System.Windows import Visibility
            self.txtInvite.Visibility = (Visibility.Collapsed if recherche
                                         else Visibility.Visible)
        except Exception:
            pass

        visibles = []
        for s in self._styles:
            if calcul is not None and s['calcul'] != calcul:
                continue
            if recherche and recherche not in s['nom'].lower():
                continue
            visibles.append(s)

        if not visibles:
            msg = TextBlock()
            msg.Text = u"Aucun style ne correspond."
            msg.TextWrapping = TextWrapping.Wrap
            msg.FontSize = 12
            msg.Margin = Thickness(6)
            self.pnlStyles.Children.Add(msg)
            return

        # Style resolu UNE fois : TryFindResource part de la fenetre et remonte
        # jusqu'aux ressources de l'application, donc trouve bien celui declare
        # dans <Window.Resources>. Resolution explicite plutot que
        # SetResourceReference : le bouton n'est pas encore dans l'arbre visuel
        # au moment ou on le configure.
        style_bouton = None
        try:
            style_bouton = self.TryFindResource('NMButtonStyleListe')
        except Exception:
            style_bouton = None

        for s in visibles:
            b = Button()
            b.Content = self._contenu_bouton(s)
            b.Margin = Thickness(2)
            # Padding a ZERO, contrairement au reste de la palette : le contenu
            # doit atteindre le bord gauche du bouton, sinon la bande de couleur
            # flotterait a l'interieur. Les marges sont reportees sur le libelle
            # dans _contenu_bouton.
            b.Padding = Thickness(0)
            b.MinWidth = 0
            b.MinHeight = 0
            b.FontSize = 13
            b.HorizontalAlignment = HorizontalAlignment.Stretch
            # Stretch (et non le Left du style) : le contenu doit occuper toute
            # la largeur pour que la bande soit calee au bord. Une valeur locale
            # prime sur le Setter du style.
            b.HorizontalContentAlignment = HorizontalAlignment.Stretch
            # NMButtonStyleListe (declare dans le XAML de cette palette) relaie
            # HorizontalContentAlignment jusqu'au ContentPresenter, ce que
            # NMButtonStandard ne fait pas.
            if style_bouton is not None:
                b.Style = style_bouton
            # Infobulle = colonne commentaire de la ligne. Sans commentaire,
            # pas d'infobulle vide : on rappelle au moins le type de calcul.
            b.ToolTip = self._infobulle(
                s['commentaire'] or (
                    u"Type de calcul : {0}".format(s['calcul']) if s['calcul']
                    else u"Aucun commentaire renseigné."))
            b.Tag = s
            b.Click += self._on_style_click
            self.pnlStyles.Children.Add(b)

    # Largeur du repere colore, en pixels.
    _LARGEUR_REPERE = 5

    # Cote de la pastille de couleur de surface, en pixels.
    _COTE_PASTILLE = 14

    def _contenu_bouton(self, style):
        """
        Contenu d'un bouton : bande a gauche, libelle, pastille a droite.

        DEUX temoins, de formes differentes, pour deux couleurs qui n'ont rien
        a voir — memes conventions que le dialogue « Ordre et couleurs » :
          - la BANDE porte le repere, codage semantique de l'article
            reglementaire (compte / deduit / hors perimetre) ;
          - la PASTILLE montre la couleur de surface, celle que prendra la surface
            dans le choix de couleurs de Revit.

        Une bande plutot qu'un fond colore : elle se repere en balayage rapide
        sans toucher a la lisibilite du libelle, ni obliger a retravailler les
        etats de survol et d'appui du bouton.

        Les deux couleurs viennent des parametres de l'extension (config.json),
        jamais du modele : voir _lire_config.
        """
        from System.Windows.Controls import Grid, ColumnDefinition, TextBlock, Border
        from System.Windows import (Thickness, GridLength, GridUnitType,
                                    TextWrapping, CornerRadius, VerticalAlignment)
        from System.Windows.Media import Brushes

        reglage = self._reglages_styles.get(style['nom'])
        couleur = reglage[1] if reglage else u''
        couleur_plan = self._couleurs_plan.get(style['nom'], u'')

        grille = Grid()
        for largeur in (GridLength(self._LARGEUR_REPERE),
                        GridLength(1, GridUnitType.Star),
                        GridLength(0, GridUnitType.Auto)):
            cd = ColumnDefinition()
            cd.Width = largeur
            grille.ColumnDefinitions.Add(cd)

        bande = Border()
        bande.Background = self._brosse(couleur) or Brushes.Transparent
        # Arrondi cote gauche seulement, pour epouser le coin du bouton.
        bande.CornerRadius = CornerRadius(3, 0, 0, 3)
        Grid.SetColumn(bande, 0)
        grille.Children.Add(bande)

        libelle = TextBlock()
        libelle.Text = style['nom']
        libelle.TextWrapping = TextWrapping.Wrap
        libelle.Margin = Thickness(8, 6, 8, 6)
        Grid.SetColumn(libelle, 1)
        grille.Children.Add(libelle)

        # Pastille toujours presente, meme sans couleur : sa bordure marque
        # l'emplacement et signale qu'aucune couleur de surface n'est definie,
        # plutot que de laisser croire a un oubli d'affichage.
        #
        # Le rendu reprend le MOTIF de remplissage, pas seulement la couleur :
        # c'est ce couple que Revit applique a une entree, et deux styles de
        # meme teinte ne se distinguent que par la.
        motif_plan = self._motifs_plan.get(style['nom'], u'')
        pastille = Border()
        pastille.Width = self._COTE_PASTILLE
        pastille.Height = self._COTE_PASTILLE
        pastille.Background = self._pinceau_plan(
            couleur_plan, motif_plan,
            self._COTE_PASTILLE, self._COTE_PASTILLE) or Brushes.Transparent
        pastille.BorderBrush = Brushes.LightGray
        pastille.BorderThickness = Thickness(1)
        pastille.CornerRadius = CornerRadius(2)
        pastille.Margin = Thickness(0, 0, 8, 0)
        pastille.VerticalAlignment = VerticalAlignment.Center
        pastille.ToolTip = (
            u"Couleur de surface : {0}{1}".format(
                couleur_plan,
                u"" if not motif_plan else u"  •  motif : {0}".format(motif_plan))
            if couleur_plan else u"Aucune couleur de surface définie")
        Grid.SetColumn(pastille, 2)
        grille.Children.Add(pastille)

        return grille

    def _pinceau_plan(self, hexa, nom_motif, largeur, hauteur):
        """
        Pinceau de la pastille : couleur ET motif de remplissage.

        Les motifs du document sont lus a la PREMIERE demande et conserves :
        la liste de boutons se reconstruit a chaque filtre, et relire le
        document a chaque fois serait inutilement couteux.

        Repli sur un aplat si le rendu n'est pas disponible : une pastille
        approximative reste plus parlante qu'une pastille vide.
        """
        try:
            if self._infos_motifs is None:
                import dialogs.apercu_motifs as _m
                reload(_m)
                from dialogs.apercu_motifs import infos_motifs
                self._infos_motifs = infos_motifs(self._doc)
            from dialogs.apercu_motifs import pinceau_apercu
            return pinceau_apercu(hexa, self._infos_motifs.get(nom_motif or u''),
                                  largeur, hauteur)
        except Exception as ex:
            self._log(u"⚠ Aperçu des motifs indisponible : {0}".format(ex))
            self._infos_motifs = {}
            return self._brosse(hexa)

    def _brosse(self, hexa):
        """Pinceau WPF depuis '#RRGGBB', ou None si la valeur est inexploitable."""
        if not hexa:
            return None
        try:
            from System.Windows.Media import ColorConverter, SolidColorBrush
            return SolidColorBrush(ColorConverter.ConvertFromString(hexa))
        except Exception:
            return None

    _LARGEUR_INFOBULLE = 300

    def _infobulle(self, texte):
        """
        Construit une infobulle qui se replie sur plusieurs lignes.

        Une chaine passee directement a ToolTip s'affiche sur UNE seule ligne,
        aussi longue que le texte : les commentaires de la table de style
        produisaient des bulles traversant l'ecran. WPF n'offre aucune propriete
        de largeur maximale sur l'infobulle elle-meme — il faut lui donner pour
        contenu un TextBlock borne, qui replie le texte.
        """
        from System.Windows.Controls import ToolTip, TextBlock
        from System.Windows import TextWrapping
        try:
            corps = TextBlock()
            corps.Text = texte
            corps.TextWrapping = TextWrapping.Wrap
            corps.MaxWidth = self._LARGEUR_INFOBULLE
            bulle = ToolTip()
            bulle.Content = corps
            return bulle
        except Exception:
            return texte   # repli : bulle sur une ligne, mais bulle quand meme

    def _on_loaded(self, sender, args):
        self._positionner_a_droite()
        self._rafraichir_selection(force=True)
        self._rafraichir_message()

    def _zone_revit(self):
        """
        (gauche, haut, droite, bas) de la fenetre Revit, en unites WPF.

        MainWindowExtents rend des PIXELS ECRAN, alors que Left/Top/Width d'une
        fenetre WPF sont des unites independantes de la resolution. Les deux ne
        coincident qu'a 100 % de mise a l'echelle : sans conversion, la palette
        se retrouve hors champ des qu'un ecran est a 125 ou 150 %. D'ou le
        passage par la matrice de la fenetre.

        Retourne None si Revit ne se laisse pas interroger, l'appelant se
        rabattant alors sur la zone de travail de l'ecran.
        """
        from System.Windows import Point, PresentationSource
        try:
            r = self._uiapp.MainWindowExtents
            coins = (float(r.Left), float(r.Top), float(r.Right), float(r.Bottom))
        except Exception:
            return None
        try:
            source = PresentationSource.FromVisual(self)
            m = source.CompositionTarget.TransformFromDevice
            hg = m.Transform(Point(coins[0], coins[1]))
            bd = m.Transform(Point(coins[2], coins[3]))
            return hg.X, hg.Y, bd.X, bd.Y
        except Exception:
            # Fenetre pas encore rendue, ou source indisponible : les pixels
            # bruts valent mieux que rien, ils sont justes a 100 %.
            return coins

    def _positionner_a_droite(self, marge=12):
        """
        Cale la palette au bord droit de la fenetre REVIT, centree en hauteur.

        Sur la fenetre de Revit et non sur l'ecran : un second ecran, ou une
        fenetre Revit qui n'est pas maximisee, placaient la palette loin de la
        zone de travail.

        La hauteur est bornee a ce que la fenetre offre : le XAML la demande
        genereuse pour montrer un maximum de styles, mais elle ne doit pas
        deborder sur un ecran court.
        """
        try:
            zone = self._zone_revit()
            if zone is None:
                from System.Windows import SystemParameters
                z = SystemParameters.WorkArea
                zone = (z.Left, z.Top, z.Right, z.Bottom)
            gauche, haut, droite, bas = zone

            hauteur = self.Height
            dispo = (bas - haut) - 2 * marge
            if dispo > 0 and hauteur > dispo:
                hauteur = max(dispo, self.MinHeight)
                self.Height = hauteur

            self.Left = droite - self.Width - marge
            self.Top  = haut + ((bas - haut) - hauteur) / 2.0
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Filtres
    # ------------------------------------------------------------------

    def cbo_calcul_change(self, sender, args):
        self._reconstruire_boutons()
        # Le libelle de la case annonce l'etiquette du type de calcul affiche :
        # il suit donc le filtre.
        self._maj_liste_etiquettes()

    def txt_recherche_change(self, sender, args):
        self._reconstruire_boutons()

    # ------------------------------------------------------------------
    # Etiquetage
    # ------------------------------------------------------------------

    def chk_etiqueter_change(self, sender, args):
        """Marche/arret de l'etiquetage, memorise dans config.json."""
        self._etiq_actif = bool(self.chkEtiqueter.IsChecked)
        try:
            # reload() : le moteur IronPython est partage et garde en cache la
            # version de config_loader chargee au premier lancement.
            import utils.config_loader as _c
            reload(_c)
            _c.set_valeur('surface', 'etiquettes_actif', self._etiq_actif)
        except Exception as ex:
            # Non bloquant : l'etiquetage marche pour cette session, seule sa
            # memorisation a echoue. Le dire, mais ne pas s'arreter la-dessus.
            self._log(u"⚠ État de l'étiquetage non mémorisé : {0}".format(ex))
        # Liste et ligne de repere grisees quand la case est decochee : sans
        # cela elles invitent a un choix qui ne servira a rien.
        try:
            self.cboEtiquette.IsEnabled = self._etiq_actif
            self.chkRepere.IsEnabled    = self._etiq_actif
        except Exception:
            pass
        self._maj_alerte_etiquette()

    # Entree de tete de la liste deroulante : suivre le mappage des parametres,
    # type de calcul par type de calcul. Indispensable sous « Tous les types »,
    # ou aucune etiquette unique ne peut etre annoncee a l'avance, et seul moyen
    # de revenir au reglage apres un choix manuel.
    _ETIQ_PARAMETRES = u"< Selon les paramètres >"

    def _etiquette_pour(self, calcul):
        """
        (nom « Famille : Type », ligne de repere) pour un type de calcul.

        Le repli « autres types de calcul » sert les projets qui apportent un
        type que personne n'a encore regle : mieux vaut une etiquette generique
        qu'aucune.
        """
        cle = (calcul or u'').strip()
        v = self._etiq_par_calcul.get(cle) if cle else None
        if v is None:
            v = self._etiq_defaut
        return (v.get(u'etiquette') or u''), bool(v.get(u'repere'))

    def _etiquette_a_poser(self, style):
        """
        (nom, ligne de repere) reellement retenus pour ce style.

        La liste deroulante prime sur les parametres — c'est sa raison d'etre —
        sauf quand elle est laissee sur « Selon les paramètres ». La case
        « Ligne de repère », elle, tranche toujours : elle affiche deja le
        reglage du type de calcul courant, la lire revient donc a suivre les
        parametres tant que personne n'y a touche.
        """
        nom_config, _repere = self._etiquette_pour(style.get('calcul'))
        choix = self._etiquette_choisie()
        try:
            repere = bool(self.chkRepere.IsChecked)
        except Exception:
            repere = _repere
        return (choix if choix else nom_config), repere

    def _etiquette_choisie(self):
        """Nom complet selectionne dans la liste, ou u'' si « Selon les paramètres »."""
        try:
            item = self.cboEtiquette.SelectedItem
            return (item.Tag or u'') if item is not None else u''
        except Exception:
            return u''

    def _maj_liste_etiquettes(self):
        """
        Reconstruit la liste des etiquettes et la recale sur les parametres.

        Appelee au demarrage et a chaque changement de type de calcul : le
        reglage reste la reference, un choix manuel ne survit donc pas au
        passage a un autre type de calcul. Sans ce recalage, on etiquetterait
        des SHON/SHOB avec l'etiquette choisie pour la surface de plancher sans
        que rien ne le signale.
        """
        from System.Windows.Controls import ComboBoxItem

        # Reconstruire la liste redeclenche SelectionChanged : sans ce verrou,
        # chaque reconstruction relancerait _maj_alerte_etiquette a vide.
        if getattr(self, '_maj_etiq', False):
            return
        self._maj_etiq = True
        try:
            try:
                import utils.surfaces_etiquettes as _m
                reload(_m)
                types = [n for n, _id in _m.types_etiquettes(self._doc)]
            except Exception as ex:
                types = []
                self._log(u"⚠ Types d'étiquette illisibles : {0}".format(ex))

            try:
                calcul = self.cboCalcul.SelectedItem
            except Exception:
                calcul = None
            # Sans filtre, aucun type de calcul ne commande : la ligne de repere
            # part alors du repli « autres types de calcul », seul reglage qui
            # vaille pour tous.
            attendu = u''
            if calcul is not None and calcul != self._TOUS:
                attendu, repere_voulu = self._etiquette_pour(calcul)
            else:
                repere_voulu = bool(self._etiq_defaut.get(u'repere'))
            self.chkRepere.IsChecked = bool(repere_voulu)

            self.cboEtiquette.Items.Clear()
            tete = ComboBoxItem()
            tete.Content = self._ETIQ_PARAMETRES
            tete.Tag = u''
            tete.ToolTip = (u"L'étiquette est choisie d'après le type de calcul "
                            u"de chaque style, selon le mappage des paramètres.")
            self.cboEtiquette.Items.Add(tete)

            # Une etiquette configuree mais absente du projet reste proposee et
            # signalee : la faire disparaitre laisserait croire a un mappage
            # vide, alors que c'est la famille qui n'est pas chargee.
            noms = list(types)
            if attendu and attendu not in noms:
                noms.append(attendu)

            a_selectionner = None
            for nom in noms:
                item = ComboBoxItem()
                # « Famille : Type » en entier, comme dans le dialogue des
                # parametres : deux types de meme nom dans deux familles
                # differentes etaient indistinguables. La liste deroulee
                # s'elargit d'elle-meme au contenu ; c'est seulement la ligne
                # fermee, a la largeur de la palette, qui tronque — l'infobulle
                # y supplee.
                item.Content = nom
                item.Tag = nom
                item.ToolTip = nom
                if nom not in types:
                    item.ToolTip = (u"{0}\n\nCette famille n'est pas chargée "
                                    u"dans le projet.".format(nom))
                self.cboEtiquette.Items.Add(item)
                if nom == attendu:
                    a_selectionner = item

            self.cboEtiquette.SelectedItem = a_selectionner or tete
        finally:
            self._maj_etiq = False
        self._maj_alerte_etiquette()

    def cbo_etiquette_change(self, sender, args):
        self._maj_alerte_etiquette()

    def _maj_alerte_etiquette(self):
        """
        Signale en rouge qu'aucune étiquette ne sera posee.

        Le cas se produit sous « Selon les paramètres » quand le type de calcul
        courant n'a pas de mappage. Rien ne serait pose, et sans ce signal on ne
        s'en apercevrait qu'en regardant le plan.
        """
        try:
            from System.Windows.Media import Brushes
        except Exception:
            return
        if getattr(self, '_maj_etiq', False):
            return

        muet = False
        if not self._etiquette_choisie():
            try:
                calcul = self.cboCalcul.SelectedItem
            except Exception:
                calcul = None
            if calcul is not None and calcul != self._TOUS:
                nom, _repere = self._etiquette_pour(calcul)
                muet = not nom

        try:
            self.cboEtiquette.Foreground = (Brushes.Firebrick if muet
                                            else Brushes.Black)
            self.cboEtiquette.ToolTip = (
                u"Aucune étiquette n'est configurée pour ce type de calcul : "
                u"choisissez-en une ci-dessus, ou réglez le mappage dans "
                u"« Paramètres > Surfaces »." if muet else None)
        except Exception:
            pass

    def _vue_pour_etiquettes(self):
        """Plan de surface actif, seul endroit ou poser une etiquette."""
        from Autodesk.Revit.DB import ViewPlan
        try:
            vue = self._uiapp.ActiveUIDocument.ActiveView
        except Exception:
            return None
        return vue if isinstance(vue, ViewPlan) else None

    def _effacer_valeurs_de_style(self, surfaces):
        """
        Vide, sur les surfaces, les parametres alimentes par la table de style.

        Retirer la seule cle ne suffit pas. Poser une cle fait RECOPIER par
        Revit la valeur de chaque colonne dans le parametre correspondant de la
        surface, et ces copies SURVIVENT au retrait de la cle : la surface
        gardait toutes ses donnees, sans plus rien pour dire d'ou elles
        venaient — pire qu'un style franchement pose.

        Les parametres sont rapproches par leur ID, pas par leur nom : un ID ne
        se traduit pas et ne se confond pas avec un homonyme d'une autre
        discipline. Ceux que la surface ne porte pas sont simplement absents de
        sa collection, il n'y a donc rien a filtrer.

        Appelee DANS la transaction d'effacement, apres la mise a vide de la
        cle : tant que la cle pointe une ligne, Revit reecrirait les valeurs.

        Returns:
            tuple: (nombre de valeurs vidées, noms des colonnes refusées)
        """
        from Autodesk.Revit.DB import StorageType, ElementId

        colonnes = getattr(self, '_colonnes_table', None) or []
        if not colonnes or not surfaces:
            return 0, []

        par_id = {}
        for pid, nom_col in colonnes:
            try:
                par_id[pid.IntegerValue] = nom_col
            except Exception:
                continue
        if not par_id:
            return 0, []

        vides = 0
        refus = set()
        for surface in surfaces:
            try:
                parametres = surface.Parameters
            except Exception:
                continue
            for p in parametres:
                try:
                    nom_col = par_id.get(p.Id.IntegerValue)
                except Exception:
                    continue
                if nom_col is None:
                    continue
                try:
                    # La cle elle-meme a deja ete videe par l'appelant.
                    if p.Definition.Name == self._param_style:
                        continue
                except Exception:
                    pass
                try:
                    if p.IsReadOnly:
                        refus.add(nom_col)
                        continue
                    type_stock = p.StorageType
                    if type_stock == StorageType.String:
                        ok = p.Set(u"")
                    elif type_stock == StorageType.ElementId:
                        ok = p.Set(ElementId.InvalidElementId)
                    elif type_stock == StorageType.Integer:
                        # Revit n'a pas de « vide » pour un nombre : zero est ce
                        # qui s'en approche le plus, et c'est ce qu'affiche une
                        # surface sans style.
                        ok = p.Set(0)
                    elif type_stock == StorageType.Double:
                        ok = p.Set(0.0)
                    else:
                        continue
                    if ok:
                        vides += 1
                except Exception:
                    refus.add(nom_col)

        return vides, sorted(refus)

    def _etiqueter(self, surfaces, style):
        """
        Etiquette les surfaces qui viennent de recevoir `style`.

        Appelee DANS la transaction d'ecriture des cles : une etiquette est un
        element neuf, rien n'oblige a la transaction separee qu'imposent les
        couleurs. Un seul Ctrl+Z defait donc le style ET son etiquetage.

        Returns:
            dict: compteurs d'etiquetage, vide si rien n'a ete fait.
        """
        if not self._etiq_actif or not surfaces or style is None:
            return {}

        nom, repere = self._etiquette_a_poser(style)
        if not nom:
            self._log(u"▶ Étiquetage : aucune étiquette configurée pour "
                      u"« {0} ».".format(style.get('calcul') or u'—'))
            return {}

        vue = self._vue_pour_etiquettes()
        if vue is None:
            self._log(u"⚠ Étiquetage impossible : la vue active n'est pas un "
                      u"plan.")
            return {}

        try:
            import utils.surfaces_etiquettes as _m
            reload(_m)
        except Exception as ex:
            self._log(u"⚠ Module d'étiquetage indisponible : {0}".format(ex))
            return {}

        type_id = _m.type_par_nom(self._doc, nom)
        if type_id is None:
            self._log(u"⚠ Étiquette « {0} » absente de ce projet : chargez la "
                      u"famille, ou corrigez le mappage dans les "
                      u"paramètres.".format(nom))
            return {}

        try:
            return _m.etiqueter(self._doc, vue, surfaces, type_id, repere)
        except Exception as ex:
            # Jamais bloquant pour l'ecriture du style, qui doit aboutir. Et
            # jamais silencieux : c'est en avalant l'echec de la lecture des
            # etiquettes existantes qu'on se retrouvait a en empiler une de plus
            # a chaque changement de style.
            self._echec(u"Étiquetage abandonné — voir les logs.")
            self._log(u"⚠ Étiquetage abandonné : {0}".format(ex))
            return {}

    # ------------------------------------------------------------------
    # Action principale
    # ------------------------------------------------------------------

    def _surfaces_selectionnees(self):
        """ElementId des surfaces (Area) actuellement selectionnees."""
        from Autodesk.Revit.DB import Area
        ids = []
        try:
            uidoc = self._uiapp.ActiveUIDocument
            if uidoc is None:
                return ids
            doc = uidoc.Document
            for eid in uidoc.Selection.GetElementIds():
                el = doc.GetElement(eid)
                if isinstance(el, Area):
                    ids.append(eid)
        except Exception:
            pass
        return ids

    def _issues_de_la_pose(self, ids):
        """
        Vrai si TOUTES les surfaces donnees ont ete posees pendant cette pose.

        Sert a distinguer une selection voulue par l'utilisateur de celle que
        Revit laisse derriere lui apres une creation.
        """
        connus = set()
        for l in self._lots:
            for i in l['ids']:
                connus.add(str(i))
        if not connus:
            return False
        for eid in ids:
            if str(eid) not in connus:
                return False
        return True

    def _on_style_click(self, sender, args):
        """
        Applique le style aux surfaces selectionnees, ou lance/poursuit la pose.

        La selection commande, avec une nuance pendant le mode pose : une
        selection composee UNIQUEMENT de surfaces que l'on vient de poser est
        ignoree, et le clic change simplement le style de pose.

        Pourquoi : Revit laisse volontiers selectionnee la surface qu'il vient
        de creer. Sans cette nuance, changer de style en cours de placement
        partait dans la branche « appliquer a la selection », qui ARRETE le
        mode — l'utilisateur se retrouvait sorti du mode au moment precis ou il
        voulait continuer a poser.

        Selectionner une surface PREEXISTANTE reste donc le moyen de sortir du
        mode pose et de revenir a l'attribution sur selection.
        """
        try:
            style = sender.Tag
            if style is None:
                return

            ids = self._surfaces_selectionnees()
            if ids and self._pose_active and self._issues_de_la_pose(ids):
                ids = []
            if ids:
                # Une pose pouvait etre en cours : ses lots sont ecrits AVANT de
                # traiter la selection, jamais abandonnes.
                self._arreter_pose()
                _self, _ids, _st = [self], [ids], [style]

                def _action():
                    _self[0]._traiter(_ids[0], _st[0])

                self._action_handler.planifier(_action)
                self._ext_event.Raise()
            else:
                self._demarrer_pose(style)
        except Exception as ex:
            self._echec(u"Application impossible : {0}".format(ex))

    def btn_effacer_click(self, sender, args):
        """Vide le parametre de cle de style sur les surfaces selectionnees."""
        try:
            ids = self._surfaces_selectionnees()
            if not ids:
                from dialogs.dialogs_styles_loader import show_alert
                show_alert(u"NM-BATII — Surfaces",
                           u"Sélectionnez d'abord une ou plusieurs surfaces "
                           u"dans la vue active.")
                return
            self._arreter_pose()
            _self, _ids = [self], [ids]

            def _action():
                _self[0]._traiter(_ids[0], None)

            self._action_handler.planifier(_action)
            self._ext_event.Raise()
        except Exception as ex:
            self._echec(u"Effacement impossible : {0}".format(ex))

    # ------------------------------------------------------------------
    # Ecriture (contexte API Revit — via l'ExternalEvent uniquement)
    # ------------------------------------------------------------------

    def _appliquer(self, ids, style):
        """
        Ecrit la cle de style sur les surfaces ; style=None efface la valeur.

        Transaction explicite plutot que revit.Transaction : le module pyrevit
        resout son document a l'import, et cette methode s'execute depuis un
        ExternalEvent longtemps apres. Le document est ici celui capture sur
        l'instance, sans ambiguite.

        Returns:
            tuple: (nb_ecrites, nb_ignorees, compteurs d'etiquetage,
                    (valeurs de table vidées, colonnes refusées))
                Le dernier terme ne vaut que pour l'effacement (style=None).
        """
        from Autodesk.Revit.DB import Transaction, StorageType, ElementId

        doc = self._doc
        ecrites  = 0
        ignorees = 0
        # Surfaces reellement ecrites : ce sont elles, et elles seules, qu'on
        # etiquette. Une surface dont le parametre est absent n'a pas recu le
        # style, elle n'a pas a en porter l'etiquette.
        traitees = []
        etiq = {}
        nettoyes = 0
        refuses  = []

        t = Transaction(doc, u"NM-BATII — Clé de style de surface")
        t.Start()
        try:
            for eid in ids:
                el = doc.GetElement(eid)
                if el is None:
                    ignorees += 1
                    continue
                p = el.LookupParameter(self._param_style)
                if p is None or p.IsReadOnly:
                    ignorees += 1
                    continue
                try:
                    if p.StorageType == StorageType.ElementId:
                        p.Set(style['id'] if style else ElementId.InvalidElementId)
                    else:
                        # Table convertie en simple liste de valeurs texte.
                        p.Set(style['nom'] if style else u"")
                    ecrites += 1
                    traitees.append(el)
                except Exception:
                    ignorees += 1
            # Meme transaction : un seul Ctrl+Z defait le style ET son
            # etiquetage. « Effacer le style » (style=None) ne touche pas aux
            # etiquettes, le bouton fait ce que son nom dit.
            etiq = self._etiqueter(traitees, style)
            if style is None:
                # APRES la mise a vide de la cle : tant qu'elle pointe une
                # ligne, Revit reecrit les valeurs qu'on vient d'effacer.
                nettoyes, refuses = self._effacer_valeurs_de_style(traitees)
            t.Commit()
        except Exception:
            try:
                t.RollBack()
            except Exception:
                pass
            raise
        return ecrites, ignorees, etiq, (nettoyes, refuses)

    def _resume_application(self, ids, style):
        """
        Ecrit un groupe de surfaces et rend le compte rendu, sans l'afficher.

        Separer l'ecriture de l'affichage permet de composer un message unique
        quand plusieurs groupes sont traites d'affilee (plusieurs lots de pose,
        ou des lots suivis d'une selection).

        Returns:
            unicode: phrase de compte rendu, ou u"" si rien a dire.
        """
        try:
            ecrites, ignorees, etiq, menage = self._appliquer(ids, style)
        except Exception as ex:
            return u"✖ Écriture impossible : {0}".format(ex)

        if style is None:
            base = u"Style effacé sur {0} surface(s).".format(ecrites)
            nettoyes, refuses = menage
            if nettoyes:
                base += u" {0} valeur(s) de la table vidée(s).".format(nettoyes)
            if refuses:
                base += u" {0} colonne(s) non modifiable(s) : {1}.".format(
                    len(refuses), u", ".join(refuses[:3]))
        else:
            base = u"« {0} » appliqué à {1} surface(s).".format(
                style['nom'], ecrites)
        if ignorees:
            base += u" {0} ignorée(s) — paramètre « {1} » absent ou en lecture " \
                    u"seule.".format(ignorees, self._param_style)
        if etiq:
            try:
                import utils.surfaces_etiquettes as _m
                phrase = _m.resume(etiq)
            except Exception:
                phrase = u""
            if phrase:
                base += u" " + phrase
        return base

    def _appliquer_lots(self):
        """
        Ecrit chaque lot de pose avec SON style, puis vide la liste des lots.

        Chaque lot garde le style sous lequel ses surfaces ont ete posees :
        c'est tout l'interet du decoupage. Les lots vides (un style clique sans
        qu'aucune surface ne suive) sont ignores sans bruit.

        Returns:
            list: phrases de compte rendu, une par lot ecrit.
        """
        lots = [l for l in self._lots if l['ids']]
        self._lots = []
        resumes = []
        for lot in lots:
            self._log(u"▶ Écriture de {0} surface(s) posée(s) sous « {1} ».".format(
                len(lot['ids']), lot['style']['nom']))
            resumes.append(self._resume_application(lot['ids'], lot['style']))
        return [r for r in resumes if r]

    def _colorer_schemas(self):
        """
        Applique les couleurs standard aux choix de couleurs du projet.

        Appele APRES l'ecriture des cles de style, et dans une transaction
        SEPAREE : une entree de choix de couleurs n'existe que pour une valeur
        reellement employee, et Revit ne la cree qu'une fois la precedente
        transaction validee. Colorer dans la meme transaction ne trouverait
        rien pour un style employe pour la premiere fois.

        Jamais bloquant : un echec de coloration ne doit pas remettre en cause
        l'attribution du style, qui, elle, est deja validee.

        Returns:
            unicode: fragment de compte rendu, ou u"" si rien a signaler.
        """
        from Autodesk.Revit.DB import Transaction

        couleurs = getattr(self, '_couleurs_plan', None)
        if not couleurs or not self._styles:
            return u""

        try:
            import utils.surfaces_couleurs as _m
            reload(_m)
            from utils.surfaces_couleurs import appliquer_couleurs
        except Exception as ex:
            self._log(u"⚠ Module de couleurs indisponible : {0}".format(ex))
            return u""

        doc = self._doc
        lignes = []
        for s in self._styles:
            el = doc.GetElement(s['id'])
            if el is not None:
                lignes.append((el, s['nom']))
        if not lignes:
            return u""

        t = Transaction(doc, u"NM-BATII — Couleurs des surfaces")
        t.Start()
        try:
            # _param_style ouvre le rapprochement par les surfaces (la cle de
            # style est unique, donc sans ambiguite) ; _col_calcul restreint le
            # repli par la table au bon type de calcul.
            total, _details = appliquer_couleurs(doc, lignes, couleurs,
                                                 self._col_calcul,
                                                 self._param_style,
                                                 self._motifs_plan)
            t.Commit()
        except Exception as ex:
            try:
                t.RollBack()
            except Exception:
                pass
            self._log(u"⚠ Couleurs non appliquées : {0}".format(ex))
            return u""

        if not total:
            return u""
        self._log(u"▶ {0} entrée(s) de choix de couleurs mise(s) à "
                  u"jour.".format(total))
        return u"{0} couleur(s) de surface mise(s) à jour.".format(total)

    def _traiter(self, ids=None, style=None):
        """
        Point d'entree unique des ecritures, en contexte API Revit.

        Vide d'abord les lots de pose en attente — ils precedent toujours
        l'action courante dans le temps —, puis applique le style demande a la
        selection s'il y en a une. Un seul message resume l'ensemble : sans
        cela, le compte rendu de la selection effacerait celui des poses.
        """
        parties = self._appliquer_lots()
        if ids:
            r = self._resume_application(ids, style)
            if r:
                parties.append(r)
        if parties:
            # Les valeurs viennent d'etre ecrites : c'est maintenant, et pas
            # avant, que Revit connait les entrees correspondantes du choix de
            # couleurs. Voir _colorer_schemas.
            r = self._colorer_schemas()
            if r:
                parties.append(r)
            texte = u"  ".join(parties)
            self._message(texte)
            self._log(texte)
        # Force la relecture au prochain Idling : les valeurs viennent de
        # changer. PAS via _sig_selection : ce serait vu comme un changement de
        # selection, qui degele la zone et effacerait le compte rendu ci-dessus.
        self._forcer_relecture = True

    # ------------------------------------------------------------------
    # Pose d'une nouvelle surface (outil natif Revit)
    # ------------------------------------------------------------------

    def _demarrer_pose(self, style):
        """
        Lance l'outil natif « Surface » et arme la surveillance des creations.

        PostCommand est prevu pour etre appele depuis une fenetre non modale, et
        Area est bien un membre de l'enumeration PostableCommand — donc
        reellement postable, contrairement aux identifiants ID_* internes.

        CHANGEMENT DE STYLE EN COURS DE POSE : si une pose est deja armee, le
        lot courant est simplement CLOS et un nouveau lot s'ouvre. Les surfaces
        deja posees conservent leur style, et seront ecrites en meme temps que
        les suivantes — a la sortie de l'outil, seul moment ou Revit depeche
        l'ExternalEvent. Une version precedente rearmait tout a zero ici, ce qui
        jetait les surfaces du style precedent : elles restaient sans valeur.
        """
        from Autodesk.Revit.UI import RevitCommandId, PostableCommand
        from Autodesk.Revit.DB import ViewType
        from System.Windows import Visibility

        vue = None
        try:
            vue = self._uiapp.ActiveUIDocument.ActiveView
        except Exception:
            vue = None
        if vue is None or vue.ViewType != ViewType.AreaPlan:
            nom_vue = u"?"
            type_vue = u"?"
            try:
                nom_vue  = vue.Name
                type_vue = str(vue.ViewType)
            except Exception:
                pass
            # Trace dans la zone persistante EN PLUS de la boite : c'est le
            # premier refus possible du mode pose, il doit rester lisible apres
            # avoir ferme la boite.
            # Gele sans duree : un refus n'a pas a s'effacer tout seul.
            self._geler_message(
                u"Pose refusée : la vue active « {0} » est de type {1}, pas un "
                u"plan de surface.".format(nom_vue, type_vue))
            self._log(u"✖ Pose refusée — vue « {0} », ViewType={1}.".format(
                nom_vue, type_vue))
            from dialogs.dialogs_styles_loader import show_alert
            show_alert(
                u"NM-BATII — Surfaces",
                u"Aucune surface n'est sélectionnée, et la vue active n'est pas "
                u"un plan de surface : Revit ne peut pas y placer de surface.\n\n"
                u"Vue active : « {0} » (type {1}).\n\n"
                u"Ouvrez un plan de surface, ou sélectionnez des surfaces "
                u"existantes avant de cliquer sur un style.".format(
                    nom_vue, type_vue))
            return

        deja_armee = self._pose_active

        captures = 0
        if not deja_armee:
            # Photo des surfaces existantes AVANT la pose.
            self._ids_avant = set(self._inventaire_surfaces().keys())

            # Detecteur immediat, en plus de la photo. S'il echoue a s'abonner,
            # ce n'est pas bloquant : la capture au changement de lot suffit.
            try:
                self._app.DocumentChanged += self._h_doc_changed
                self._abonne_doc = True
            except Exception as ex:
                self._abonne_doc = False
                # « Exception has been thrown by the target of an invocation »
                # ne dit rien : le motif reel est dans l'InnerException. Selon
                # la facon dont IronPython enveloppe l'exception .NET, elle est
                # exposee directement ou via clsException — on tente les deux.
                detail = str(ex)
                for source in (ex, getattr(ex, 'clsException', None)):
                    try:
                        interne = source.InnerException
                        if interne is not None:
                            detail = u"{0} / {1}".format(detail, interne.Message)
                            break
                    except Exception:
                        continue
                self._log(u"⚠ DocumentChanged indisponible ({0}) — repli sur la "
                          u"comparaison d'inventaire.".format(detail))
            self._pose_active = True
        else:
            # CRUCIAL sans DocumentChanged : tout ce qui a ete pose depuis le
            # dernier point de controle appartient au style QUI S'ACHEVE. Cette
            # capture doit avoir lieu AVANT d'ouvrir le lot suivant.
            captures = self._capturer_nouvelles_surfaces()

        # Nouveau lot, sauf si c'est le meme style qu'on reclique : inutile de
        # decouper, autant continuer a remplir le lot ouvert.
        if self._style_pose is not style:
            self._lots.append({'style': style, 'ids': []})
            self._style_pose = style

        # Etat du mode pose : affiche tant que la pose dure, sauf compte rendu
        # ou erreur qui prennent temporairement la place.
        # Balisage **gras** interprete par _poser_texte.
        self._txt_pose = (
            u"Création de surfaces de style « {0} » en cours.\n"
            u"**Cliquez un autre style pour en changer**\n"
            u"**ECHAP** pour terminer.".format(style['nom']))
        self._degeler_message()
        self._rafraichir_message()

        # Point de depart du compte a rebours de cloture automatique : l'outil
        # va demarrer, il ne faut pas conclure a sa fin dans la seconde.
        from System import DateTime
        self._derniere_activite = DateTime.Now

        if deja_armee:
            self._log(u"▶ Nouveau lot — style « {0} » ; {1} surface(s) rattachée(s) "
                      u"au style précédent, {2} en attente d'écriture.".format(
                          style['nom'], captures,
                          sum(len(l['ids']) for l in self._lots)))
            if captures:
                self._planifier_vidage()
        else:
            self._log(u"▶ Pose armée — style « {0} », {1} surface(s) déjà "
                      u"présentes, DocumentChanged={2}.".format(
                          style['nom'], len(self._ids_avant), self._abonne_doc))

        try:
            cmd = RevitCommandId.LookupPostableCommandId(PostableCommand.Area)
            self._uiapp.PostCommand(cmd)
        except Exception as ex:
            # Reposter alors que l'outil tourne deja peut etre refuse par Revit :
            # sans consequence, l'outil voulu est deja actif. On ne desarme donc
            # la pose que si elle venait d'etre montee.
            self._log(u"⚠ PostCommand(Area) : {0}".format(ex))
            if not deja_armee:
                self._arreter_pose()
                self._echec(u"Lancement de l'outil « Surface » impossible : "
                            u"{0}".format(ex))

    def _inventaire_surfaces(self):
        """
        Toutes les surfaces du document : { identifiant texte: ElementId }.

        La comparaison se fait sur du texte (les ElementId ne se comparent pas
        en ensemble de facon fiable d'une lecture a l'autre), mais l'ecriture
        exige le vrai ElementId : le dictionnaire porte les deux, en un seul
        parcours du collecteur.
        """
        from Autodesk.Revit.DB import (FilteredElementCollector, BuiltInCategory)
        inv = {}
        try:
            col = FilteredElementCollector(self._doc) \
                .OfCategory(BuiltInCategory.OST_Areas) \
                .WhereElementIsNotElementType()
            for eid in col.ToElementIds():
                inv[str(eid)] = eid
        except Exception as ex:
            self._log(u"⚠ Inventaire des surfaces impossible : {0}".format(ex))
        return inv

    def _capturer_nouvelles_surfaces(self):
        """
        Range dans le lot COURANT les surfaces apparues depuis la derniere photo.

        Methode centrale du mode pose des lors que DocumentChanged n'est pas
        disponible — ce qui est le cas sur certaines installations, ou
        l'abonnement leve une TargetInvocationException. Elle doit donc etre
        appelee a CHAQUE instant ou le lot courant s'apprete a changer :
        changement de style, arret du mode, fermeture de la palette. L'appeler
        seulement depuis Idling ne suffisait pas — Idling n'est pas emis tant
        qu'une commande Revit est active, si bien que les surfaces posees sous
        un style etaient encore invisibles au moment ou l'utilisateur en
        choisissait un autre, et finissaient rangees sous le mauvais.

        Lecture seule : aucun contexte API particulier n'est requis, elle est
        donc appelable depuis le fil WPF comme depuis un evenement Revit.

        Returns:
            int: nombre de surfaces ajoutees au lot courant.
        """
        if not self._lots or self._ids_avant is None:
            return 0

        inventaire = self._inventaire_surfaces()
        cles       = set(inventaire.keys())
        nouveaux   = cles - self._ids_avant
        self._ids_avant = cles
        if not nouveaux:
            return 0

        # Dedoublonnage sur TOUS les lots : une surface deja rangee sous un
        # style precedent ne doit jamais etre reprise, elle changerait de style.
        deja = set()
        for l in self._lots:
            for i in l['ids']:
                deja.add(str(i))

        lot     = self._lots[-1]
        ajoutes = 0
        for cle in nouveaux:
            if cle in deja:
                continue
            lot['ids'].append(inventaire[cle])
            ajoutes += 1
        if ajoutes:
            # Signe de vie de l'outil : repousse la cloture automatique du mode
            # (voir _surveiller_fin_de_pose).
            from System import DateTime
            self._derniere_activite = DateTime.Now
        return ajoutes

    def _arreter_pose(self):
        """
        Coupe la surveillance des creations.

        NE TOUCHE PAS aux lots en attente : eux ne sont vides que par
        _appliquer_lots(), c'est-a-dire une fois ECRITS. C'est precisement ce
        que faisait la version precedente — remettre la file a zero ici — et qui
        faisait perdre les surfaces posees sous le style precedent.
        """
        if self._abonne_doc:
            try:
                self._app.DocumentChanged -= self._h_doc_changed
            except Exception:
                pass
            self._abonne_doc = False
        self._pose_active  = False
        self._style_pose   = None
        self._ids_avant    = None
        self._dernier_scan = None
        self._txt_pose     = None
        self._derniere_activite = None

    def _on_doc_changed(self, sender, args):
        """
        Met en file les surfaces creees, et demande leur ecriture.

        Interdiction absolue de modifier le document ici : DocumentChanged est
        emis en fin de transaction, dans un contexte en lecture seule. D'ou le
        passage par l'ExternalEvent, que Revit depechera a la sortie de l'outil.
        """
        from Autodesk.Revit.DB import Area
        try:
            if not self._pose_active or not self._lots:
                return
            doc = args.GetDocument()
            if doc is None or not doc.Equals(self._doc):
                return
            # Toujours le DERNIER lot : c'est celui du style actuellement
            # selectionne. C'est ici, et nulle part ailleurs, que se joue
            # l'affectation d'une surface au bon style.
            lot = self._lots[-1]
            nouveau = False
            for eid in args.GetAddedElementIds():
                el = doc.GetElement(eid)
                if isinstance(el, Area):
                    lot['ids'].append(eid)
                    nouveau = True
            if nouveau:
                self._planifier_vidage()
        except Exception:
            # Un handler d'evenement Revit qui leve fait echouer la transaction
            # de l'utilisateur : ne jamais laisser remonter. La trace part
            # neanmoins dans les logs, elle ne disparait pas.
            try:
                import traceback
                self._log(u"✖ DocumentChanged : {0}".format(traceback.format_exc()))
            except Exception:
                pass

    def _planifier_vidage(self):
        """Demande l'ecriture des lots de pose en attente."""
        _self = [self]

        def _action():
            _self[0]._vider_lots()

        self._action_handler.planifier(_action)
        self._ext_event.Raise()

    def _vider_lots(self):
        """
        Ecrit tous les lots de pose. NE DESARME PAS le mode.

        Point critique, et source du defaut precedent : cette methode s'execute
        des que Revit depeche l'ExternalEvent, c'est-a-dire des que plus aucune
        commande n'est active. Or CLIQUER SUR LA PALETTE suffit a faire rendre
        la main a l'outil « Surface » — le focus quitte Revit. Un changement de
        style declenchait donc une ecriture, et la version precedente en
        profitait pour couper la surveillance : la commande « Surface »
        repostee redemarrait, mais plus rien n'ecoutait, et les surfaces posees
        apres le changement de style restaient sans valeur.

        Le mode ne s'arrete donc pas ICI. Il prend fin ailleurs : cloture
        automatique quand l'outil Revit rend la main (_surveiller_fin_de_pose),
        action sur une selection preexistante, changement de vue, ou fermeture
        de la palette.
        """
        if not any(l['ids'] for l in self._lots):
            return
        self._traiter()

        if not self._pose_active:
            self._arreter_pose()
            return

        # Le mode continue : on repart d'un inventaire a jour (les surfaces qui
        # viennent d'etre ecrites ne doivent plus etre vues comme nouvelles par
        # le detecteur de repli) et d'un lot vide au style courant.
        self._ids_avant    = set(self._inventaire_surfaces().keys())
        self._dernier_scan = None
        if self._style_pose is not None:
            self._lots.append({'style': self._style_pose, 'ids': []})

    # ------------------------------------------------------------------
    # Suivi de la selection (evenement Idling)
    # ------------------------------------------------------------------

    def _abonner_idling(self):
        try:
            self._uiapp.Idling += self._h_idling
            self._abonne_idling = True
        except Exception:
            self._abonne_idling = False

    # ------------------------------------------------------------------
    # Verrou de vue : la palette ne vit que dans un plan de surface
    # ------------------------------------------------------------------

    def _abonner_vue(self):
        try:
            self._uiapp.ViewActivated += self._h_view_activated
            self._abonne_vue = True
        except Exception as ex:
            self._abonne_vue = False
            self._log(u"⚠ Verrou de vue indisponible : {0}".format(ex))

    def _on_view_activated(self, sender, args):
        """
        Ferme la palette des que la vue active n'est plus un plan de surface.

        ViewActivated et non ViewActivating : le second ne sert qu'a refuser un
        changement, ce qui n'est pas le besoin ici — et Revit 2025 ignore de
        toute facon son Cancel (cf. [[revit-events-cancel-piege]]). On agit
        donc apres coup, sur la vue reellement activee.

        Rester ouverte sur une vue sans surfaces serait trompeur : les boutons
        n'auraient plus de cible, et un clic lancerait un outil « Surface » que
        Revit refuse hors plan de surface.
        """
        try:
            vue = args.CurrentActiveView
            if self._est_plan_surface(vue):
                # Autre plan de surface : la palette reste, mais se recale sur
                # le type de calcul de la nouvelle vue.
                self._synchroniser_type_calcul(vue)
                return
            self._log(u"▶ Vue non « plan de surface » activée : fermeture de la "
                      u"palette.")
            self._fermer_depuis_revit()
        except Exception as ex:
            self._log(u"⚠ Verrou de vue : {0}".format(ex))

    def _est_plan_surface(self, vue):
        """Vrai si la vue est de la famille système « Plan de surface »."""
        from Autodesk.Revit.DB import ViewType
        try:
            return vue is not None and vue.ViewType == ViewType.AreaPlan
        except Exception:
            return False

    def _fermer_depuis_revit(self):
        """Ferme la fenetre en repassant par son Dispatcher si necessaire."""
        try:
            if self.Dispatcher.CheckAccess():
                self.Close()
                return
        except Exception:
            pass
        try:
            from System import Action
            self.Dispatcher.BeginInvoke(Action(self.Close))
        except Exception:
            pass

    def _on_idling(self, sender, args):
        """
        Rafraichit le bandeau de selection, surveille les poses, remonte les
        echecs de l'ExternalEvent.

        Idling est emis tres souvent : chaque tache sort immediatement si rien
        n'a bouge. C'est le seul point d'observation fiable depuis une fenetre
        non modale — Revit n'emet aucun evenement de changement de selection, et
        un timer WPF interrogerait l'API hors de son thread.
        """
        # Premier Idling : le script est termine, les logs peuvent partir vers
        # la console durable sans qu'une seconde vienne s'ouvrir a cote.
        try:
            self._ouvrir_journal()
        except Exception:
            pass
        # Ordre significatif : detecter les poses AVANT de juger de la fin du
        # mode (une surface fraichement detectee repousse l'echeance), et
        # rafraichir la zone d'etat EN DERNIER, pour qu'elle reflete deja la
        # cloture eventuelle.
        try:
            self._rafraichir_selection()
        except Exception:
            pass
        try:
            self._surveiller_poses()
        except Exception:
            pass
        try:
            self._surveiller_fin_de_pose()
        except Exception:
            pass
        try:
            self._rafraichir_message()
        except Exception:
            pass
        # Une action planifiee qui a echoue a depose sa trace : l'afficher ici,
        # sans quoi elle resterait invisible (cf. _ActionHandler.Execute).
        try:
            trace = self._action_handler.dernier_echec()
            if trace:
                self._echec(u"Action interrompue — voir les logs.")
                self._log(u"```\n{0}\n```".format(trace))
        except Exception:
            pass

    def _surveiller_poses(self):
        """
        Point de controle periodique du mode pose.

        Complete les captures faites aux changements de lot : celles-ci rangent
        au bon style, mais ne surviennent qu'au moment ou l'utilisateur agit sur
        la palette. Ce passage-ci ecrit au fil de l'eau, des que Revit rend la
        main, sans attendre le clic suivant.
        """
        if not self._pose_active or self._ids_avant is None or not self._lots:
            return

        # Bride a un passage par seconde : le collecteur parcourt toutes les
        # surfaces du document, et Idling est emis des dizaines de fois par
        # seconde des que Revit est au repos. Sans cette bride, un mode pose
        # laisse actif ferait ramer le modele.
        from System import DateTime
        maintenant = DateTime.Now
        if self._dernier_scan is not None:
            if (maintenant - self._dernier_scan).TotalMilliseconds < 1000:
                return
        self._dernier_scan = maintenant

        ajoutes = self._capturer_nouvelles_surfaces()
        # Ne replanifier que sur une vraie nouveaute : Idling repasse ici bien
        # avant que l'ExternalEvent n'ait ete depeche.
        if ajoutes:
            self._log(u"▶ {0} surface(s) détectée(s) par comparaison "
                      u"d'inventaire.".format(ajoutes))
            self._planifier_vidage()

    # Delai sans aucune pose au-dela duquel le mode est considere termine.
    # Doit rester nettement superieur a la bride d'une seconde de
    # _surveiller_poses, sans quoi le mode s'arreterait pendant que des
    # surfaces sont encore en cours de detection.
    _DELAI_FIN_POSE = 3

    def _surveiller_fin_de_pose(self):
        """
        Clot le mode pose quand l'outil Revit a rendu la main (Echap, ou autre).

        Revit n'expose NI l'etat de la commande active, NI la frappe d'Echap :
        aucun evenement ne signale la sortie de l'outil. Le signal utilise ici
        est indirect mais fiable — Idling n'est pas emis tant qu'une commande
        est active. C'est verifiable dans les traces : _surveiller_poses, qui
        n'est appele que depuis Idling, ne detecte jamais rien pendant le
        placement ; toutes les surfaces sont rattrapees par les captures faites
        aux clics, puis une derniere fois a la sortie de l'outil.

        Un Idling qui survient alors qu'aucune surface n'est apparue depuis
        _DELAI_FIN_POSE signifie donc que l'outil est termine.

        Le delai protege les deux bords :
          - au demarrage, Revit est brievement au repos entre notre PostCommand
            et le lancement effectif de l'outil ;
          - si une installation emettait malgre tout des Idling pendant le
            placement, chaque surface posee repousse l'echeance et le mode
            survit.
        """
        if not self._pose_active or self._derniere_activite is None:
            return
        from System import DateTime
        if (DateTime.Now - self._derniere_activite).TotalSeconds < self._DELAI_FIN_POSE:
            return

        # Filet : une derniere capture avant de desarmer, pour ne rien laisser
        # sur le carreau.
        self._capturer_nouvelles_surfaces()
        if any(l['ids'] for l in self._lots):
            self._planifier_vidage()
        self._arreter_pose()
        self._log(u"▶ Mode pose terminé — l'outil Revit a rendu la main.")

    def _rafraichir_selection(self, force=False):
        """Recalcule le texte de selection si elle a change depuis le dernier appel."""
        uidoc = self._uiapp.ActiveUIDocument
        if uidoc is None:
            return
        ids = list(uidoc.Selection.GetElementIds())

        # Signature bon marche : au-dela de 200 elements, le seul compte suffit
        # a detecter un changement sans parcourir toute la selection a chaque
        # passage d'Idling.
        if len(ids) > 200:
            sig = u"n:{0}".format(len(ids))
        else:
            sig = u";".join(sorted(str(i) for i in ids))
        # Deux raisons distinctes de recalculer, a ne surtout pas confondre :
        #   - la SELECTION a change  -> le texte change ET un compte rendu
        #     affiche devient caduc ;
        #   - une ECRITURE vient d'avoir lieu -> le texte change (les styles ne
        #     sont plus les memes) mais le compte rendu, lui, doit rester.
        # Melanger les deux effacait le compte rendu au premier Idling suivant,
        # c'est-a-dire aussitot.
        change = (sig != self._sig_selection)
        if not force and not change and not self._forcer_relecture:
            return
        self._forcer_relecture = False
        self._sig_selection    = sig

        from Autodesk.Revit.DB import Area, StorageType, Element

        doc      = uidoc.Document
        surfaces = []
        for eid in ids:
            el = doc.GetElement(eid)
            if isinstance(el, Area):
                surfaces.append(el)

        if change:
            self._degeler_message()

        if not surfaces:
            if ids:
                self._txt_selection = (
                    u"Aucune surface dans la sélection ({0} autre{1} "
                    u"élément{1}).\nCliquez sur un style pour créer des "
                    u"surfaces de ce style.".format(
                        len(ids), self._s(len(ids))))
            else:
                self._txt_selection = self._SANS_SELECTION
            return

        valeurs = []
        for el in surfaces:
            v = u""
            try:
                p = el.LookupParameter(self._param_style)
                if p is not None:
                    if p.StorageType == StorageType.ElementId:
                        cible = doc.GetElement(p.AsElementId())
                        if cible is not None:
                            v = Element.Name.__get__(cible)
                    else:
                        v = p.AsString() or u""
            except Exception:
                v = u""
            if v not in valeurs:
                valeurs.append(v)

        n = len(surfaces)
        if len(valeurs) == 1:
            styles = valeurs[0] or u"aucun style"
        else:
            styles = u"styles multiples"

        txt = u"{0} surface{1} sélectionnée{1} — {2}".format(n, self._s(n), styles)
        if len(ids) != n:
            txt += u" ({0} autre{1} élément{1} ignoré{1})".format(
                len(ids) - n, self._s(len(ids) - n))
        txt += u"\nCliquez sur un style pour l'attribuer {0}".format(
            u"à la surface" if n < 2 else u"aux surfaces")
        self._txt_selection = txt

    # ------------------------------------------------------------------
    # Sorties utilisateur
    # ------------------------------------------------------------------

    def _poser_texte(self, controle, texte):
        """
        Pose le texte dans un TextBlock en interpretant les segments **gras**.

        _set_rich_text vient de la bibliotheque partagee de l'extension : meme
        convention de balisage que les boites de dialogue, aucune duplication.
        Repli sur du texte brut si le module n'est pas la — un gras manquant ne
        doit jamais couter le message lui-meme.
        """
        try:
            from dialogs.dialogs_styles_loader import _set_rich_text
            _set_rich_text(controle, texte)
        except Exception:
            try:
                controle.Text = texte.replace(u'**', u'')
            except Exception:
                pass

    def _ecrire(self, controle, texte):
        """
        Ecrit dans un TextBlock depuis n'importe quel thread.

        Les appelants sont de deux natures : les clics WPF, et les callbacks
        Revit (Idling, ExternalEvent). Les seconds tournent sur le thread de
        Revit — le meme que celui de la palette dans le cas general, mais rien
        ne le garantit, et un acces croise leverait sans rien afficher.
        """
        try:
            if self.Dispatcher.CheckAccess():
                self._poser_texte(controle, texte)
                return
        except Exception:
            pass
        try:
            from System import Action
            self.Dispatcher.BeginInvoke(
                Action(lambda: self._poser_texte(controle, texte)))
        except Exception:
            pass

    # ── Zone d'etat unique ────────────────────────────────────────────────
    #
    # Un seul TextBlock dit la situation ET l'action possible. Trois sources
    # se disputent la place, d'ou une priorite explicite (voir
    # _rafraichir_message) :
    #   1. un message GELE — compte rendu ou erreur : il doit rester lisible ;
    #   2. le mode pose, s'il est actif ;
    #   3. l'etat de la selection, recalcule par Idling.
    # Sans cette priorite, Idling — qui passe plusieurs fois par seconde —
    # effacerait tout compte rendu avant qu'on ait pu le lire. C'est le defaut
    # qui avait impose deux zones separees ; la priorite permet de revenir a
    # une seule.

    _SANS_SELECTION = u"Cliquez sur un style pour créer des surfaces de ce style."

    # Duree d'affichage d'un compte rendu, en secondes. Les erreurs, elles, ne
    # s'effacent jamais toutes seules (duree None).
    _DUREE_COMPTE_RENDU = 6

    def _s(self, n):
        """Marque du pluriel : u'' ou u's'."""
        return u"" if n < 2 else u"s"

    def _geler_message(self, texte, duree=None):
        """Impose un texte a la zone d'etat ; duree=None pour qu'il y reste."""
        from System import DateTime
        self._msg_gele       = texte
        self._msg_gele_t     = DateTime.Now
        self._msg_gele_duree = duree
        self._ecrire(self.txtEtat, texte)
        self._dernier_etat = texte

    def _degeler_message(self):
        """Libere la zone d'etat : l'etat courant reprend la main."""
        self._msg_gele = None

    def _message(self, texte):
        """Compte rendu d'une action — visible quelques secondes, puis efface."""
        self._geler_message(texte, self._DUREE_COMPTE_RENDU)

    def _rafraichir_message(self):
        """
        Applique la priorite d'affichage. Appele a chaque Idling.

        Idling sert ici d'horloge : il fait expirer les comptes rendus sans
        qu'aucun DispatcherTimer ne soit necessaire.
        """
        if self._msg_gele is not None:
            if self._msg_gele_duree is None:
                return                       # erreur : reste jusqu'a la suite
            from System import DateTime
            ecoule = (DateTime.Now - self._msg_gele_t).TotalSeconds
            if ecoule < self._msg_gele_duree:
                return
            self._msg_gele = None

        if self._pose_active and self._txt_pose:
            texte = self._txt_pose
        else:
            texte = self._txt_selection or self._SANS_SELECTION

        if texte != self._dernier_etat:
            self._ecrire(self.txtEtat, texte)
            self._dernier_etat = texte

    def _ouvrir_journal(self):
        """
        Autorise l'ecriture des logs, et reverse les messages de demarrage.

        Appelee au premier Idling, donc APRES la fin du script : la console
        obtenue a partir de la est la console durable, celle qui recevra tout
        le reste. C'est ce decalage qui evite la seconde fenetre.
        """
        if self._sortie_prete or not self._log_actif:
            return
        self._sortie_prete = True
        en_attente, self._journal = self._journal, []
        for m in en_attente:
            self._log(m)

    def _log(self, message):
        if not self._log_actif or not message:
            return
        # Tant que le script s'execute, les messages attendent : les ecrire ici
        # les enverrait dans la console d'execution, qu'on vient de fermer.
        if not self._sortie_prete:
            self._journal.append(message)
            return
        try:
            # Resolue au PREMIER message reel, pas des l'ouverture de la
            # palette : sans quoi une console vide s'afficherait alors qu'il n'y
            # a rien a lire.
            if self._output is None:
                from pyrevit import script as _script
                self._output = _script.get_output()
            self._output.print_md(message)
        except Exception:
            pass

    def _echec(self, message):
        """
        Erreur visible : un callback muet est indebogable (cf. mémoire).

        Gelee SANS duree : une erreur qui s'efface toute seule au bout de
        quelques secondes n'a pas rempli son office.
        """
        self._geler_message(u"✖ " + message)
        self._log(u"✖ " + message)

    # ------------------------------------------------------------------
    # Aide
    # ------------------------------------------------------------------

    _AIDE = (
        u"Cette palette attribue aux surfaces la clé de style définie dans la "
        u"nomenclature de clés du projet.\n\n"
        u"• La liste déroulante filtre les styles par type de calcul "
        u"réglementaire ; le champ de recherche filtre par nom.\n"
        u"• Elle se cale automatiquement sur le plan de surface actif, d'après "
        u"le nom de son schéma de surface ou, à défaut, de son type de vue. "
        u"Vous restez libre d'en choisir un autre.\n"
        u"• La palette n'existe que dans un plan de surface : elle se ferme si "
        u"vous activez une autre vue.\n"
        u"• Survolez un bouton : son infobulle affiche le commentaire de la "
        u"ligne correspondante.\n\n"
        u"Deux comportements selon la sélection :\n"
        u"• des surfaces sont sélectionnées → le style leur est appliqué "
        u"immédiatement ;\n"
        u"• rien n'est sélectionné → le MODE POSE s'active et l'outil natif "
        u"Revit « Surface » démarre. La pose n'est possible que dans un plan "
        u"de surface.\n\n"
        u"Enchaînez les poses, et cliquez un autre style quand vous voulez "
        u"changer : chaque surface garde le style qui était sélectionné au "
        u"moment où vous l'avez placée. L'écriture se fait dès que Revit rend "
        u"la main.\n\n"
        u"C'est ÉCHAP, dans Revit, qui met fin au placement — la palette n'a "
        u"pas de bouton d'arrêt, il faudrait cliquer hors de Revit et lui "
        u"retirer le focus. Le message revient de lui-même à son invite de "
        u"départ quelques secondes après votre sortie de l'outil.\n\n"
        u"« Effacer le style » vide le paramètre de clé sur les surfaces "
        u"sélectionnées, ET les valeurs que la table y avait recopiées. Poser "
        u"une clé fait en effet recopier par Revit chaque colonne dans le "
        u"paramètre correspondant de la surface, et ces copies survivent au "
        u"retrait de la clé : la surface garderait toutes ses données sans "
        u"plus rien pour dire d'où elles viennent. Les étiquettes, elles, ne "
        u"sont pas touchées.\n\n"
        u"ÉTIQUETAGE — cochez « Étiqueter » pour que chaque surface traitée "
        u"reçoive son étiquette dans la vue courante. La liste déroulante "
        u"montre celle qui sera posée et permet d'en choisir une autre pour "
        u"l'instant présent ; elle passe en rouge quand aucune n'est prévue "
        u"pour le type de calcul affiché.\n"
        u"Elle se recale sur le réglage des paramètres dès que vous changez de "
        u"type de calcul : un choix fait à la main ne s'installe jamais à "
        u"l'insu de tous. « Selon les paramètres » y revient à tout moment, et "
        u"c'est le seul choix qui vaille sous « Tous les types », chaque style "
        u"pouvant alors relever d'un type de calcul différent.\n"
        u"Les entrées portent le nom complet, « Famille : Type ». Seule la "
        u"ligne fermée est tronquée, à la largeur de la palette ; l'infobulle "
        u"donne le nom entier.\n"
        u"« Ligne de repère » suit la même règle : elle affiche le réglage du "
        u"type de calcul affiché et s'y recale quand vous en changez. "
        u"Contrairement à la liste, elle tranche toujours — sous « Tous les "
        u"types », elle part du réglage « autres types de calcul » et vaut "
        u"alors pour toutes les surfaces posées.\n"
        u"Une surface déjà étiquetée n'en reçoit jamais une seconde : "
        u"l'étiquette en place est simplement remise au bon type, sa position "
        u"étant conservée. L'option native de Revit « Étiqueter au moment du "
        u"placement » peut donc rester active.\n"
        u"L'état de la case est mémorisé. Le choix de l'étiquette par type de "
        u"calcul se règle dans « Paramètres > Surfaces > Étiquettes par type "
        u"de calcul… ».\n\n"
        u"Le nom de la nomenclature, le paramètre de clé et les colonnes "
        u"utilisées se règlent dans « Paramètres > Surfaces > Table de style "
        u"des surfaces »."
    )

    # ------------------------------------------------------------------
    # Referentiel des styles, ouvert depuis la palette
    # ------------------------------------------------------------------

    # Cle sous laquelle le module du bouton Parametres est garde en cache.
    # sys.modules survit a la session Revit : le fichier n'est relu qu'une fois.
    _CLE_MODULE_PARAM = '__nm_batii_parametres_script__'

    def _module_parametres(self):
        """
        Charge le script du bouton « Parametres » comme un module.

        Son `main()` est garde par `if __name__ == '__main__'` : charge sous un
        autre nom, il ne s'execute pas, et seules les definitions arrivent —
        dont _dialogue_ordre_styles, qu'on vient chercher ici.

        Le chemin est ecrit en dur, faute de mieux : ce dialogue vit dans un
        bouton, pas dans lib/. Un deplacement du bouton Parametres casserait ce
        lien, d'ou le message explicite si le fichier manque.
        """
        import sys as _sys
        import os as _os
        import imp as _imp

        module = _sys.modules.get(self._CLE_MODULE_PARAM)
        if module is not None:
            return module

        # self._ici et non __file__ : cette methode part d'un clic, donc APRES
        # le retour d'Execute(), quand les globals du module sont vides.
        chemin = _os.path.abspath(_os.path.join(
            self._ici, '..', '..', '..',
            '01_Parametres.panel', '01_Parametres.splitpushbutton',
            '01_Parametres.pushbutton', 'script.py'))
        if not _os.path.isfile(chemin):
            raise IOError(u"Script des paramètres introuvable :\n{0}".format(
                chemin))
        return _imp.load_source(self._CLE_MODULE_PARAM, chemin)

    def btn_config_click(self, sender, args):
        """
        Ouvre « Gestion de types de calculs » et enregistre ce qui en sort.

        La fenetre des parametres n'est pas dans la boucle : c'est donc ICI
        qu'il faut ecrire config.json, sans quoi valider le dialogue ne
        laisserait aucune trace. La palette se rafraichit ensuite, l'ordre et
        les couleurs venant peut-etre de changer.
        """
        try:
            module = self._module_parametres()

            import utils.config_loader as _c
            reload(_c)
            cfg = _c.load_config()
            sf = cfg.get('surface')
            if not isinstance(sf, dict):
                sf = {}
                cfg['surface'] = sf

            ordre = []
            for e in (sf.get('styles_palette', []) or []):
                if not isinstance(e, dict):
                    continue
                nom = (e.get('nom') or u'').strip()
                if nom:
                    ordre.append({u'nom':          nom,
                                  u'couleur':      (e.get('couleur') or u'').strip(),
                                  u'couleur_plan': (e.get('couleur_plan') or u'').strip(),
                                  u'motif_plan':   (e.get('motif_plan') or u'').strip()})

            resultat = module._dialogue_ordre_styles(
                self,
                ordre,
                module._etiquettes_depuis_config(sf),
                sf.get('table_styles_schedule', u'') or u'',
                sf.get('col_calcul_style', u'') or u'')
            if resultat is None:
                return

            nouvel_ordre, etiquettes = resultat
            defaut, par_calcul = module._etiquettes_vers_config(etiquettes)
            sf['styles_palette']        = list(nouvel_ordre)
            sf['etiquette_defaut']      = defaut
            sf['etiquettes_par_calcul'] = par_calcul

            if not _c.save_config(cfg):
                self._echec(u"Réglages non enregistrés : écriture de "
                            u"config.json impossible.")
                return

            self.rafraichir()
            self._message(u"Référentiel enregistré — {0} style(s).".format(
                len(nouvel_ordre)))
        except Exception as ex:
            # Boite de dialogue et pas seulement la zone d'etat : l'utilisateur
            # vient de cliquer pour OUVRIR une fenetre. S'il ne se passe rien,
            # un bandeau discret en bas de la palette ne se remarque pas.
            import traceback
            self._log(u"```\n{0}\n```".format(traceback.format_exc()))
            self._echec(u"Référentiel indisponible : {0}".format(ex))
            try:
                from dialogs.dialogs_styles_loader import show_alert
                show_alert(u"NM-BATII — Styles de surfaces",
                           u"Ouverture impossible :\n\n{0}".format(
                               traceback.format_exc()))
            except Exception:
                pass

    def btn_aide_click(self, sender, args):
        try:
            from dialogs.dialogs_styles_loader import show_alert
            show_alert(u"NM-BATII — Surfaces", self._AIDE)
        except Exception as ex:
            self._echec(u"Aide indisponible : {0}".format(ex))

    # ------------------------------------------------------------------
    # Fermeture
    # ------------------------------------------------------------------

    def _on_closed(self, sender, args):
        """Ne jamais laisser d'abonnement derriere soi : ils survivraient a la fenetre."""
        self._ferme = True
        # Des surfaces posees peuvent attendre leur style — typiquement quand la
        # palette se ferme sur un changement de vue. L'ecriture est planifiee
        # avant de tout demonter : l'ExternalEvent et son handler vivent au
        # niveau module, ils survivent a la fenetre et la depecheront.
        try:
            self._capturer_nouvelles_surfaces()
        except Exception:
            pass
        en_attente = any(l['ids'] for l in self._lots)
        self._arreter_pose()
        if en_attente:
            try:
                self._planifier_vidage()
            except Exception:
                pass
        if self._abonne_idling:
            try:
                self._uiapp.Idling -= self._h_idling
            except Exception:
                pass
            self._abonne_idling = False
        if self._abonne_vue:
            try:
                self._uiapp.ViewActivated -= self._h_view_activated
            except Exception:
                pass
            self._abonne_vue = False

    # ------------------------------------------------------------------
    # Reouverture
    # ------------------------------------------------------------------

    def rafraichir(self):
        """Relit config et table de style — le projet actif a pu changer."""
        try:
            from pyrevit import HOST_APP as _HOST
            self._doc   = _HOST.doc
            self._app   = self._doc.Application
            self._lire_config()
            self._charger_table()
            self._remplir_calculs()
            self._synchroniser_type_calcul()
            # Le mappage des etiquettes vient d'etre relu : la case et son
            # libelle doivent suivre, sans quoi la palette annoncerait encore
            # l'ancien reglage.
            self.chkEtiqueter.IsChecked = self._etiq_actif
            self.cboEtiquette.IsEnabled = self._etiq_actif
            self.chkRepere.IsEnabled    = self._etiq_actif
            self._maj_liste_etiquettes()
            self._rafraichir_selection(force=True)
            self._rafraichir_message()
        except Exception as ex:
            self._echec(u"Rafraîchissement impossible : {0}".format(ex))


# ── Etat partage entre deux appuis sur le bouton du ruban ────────────────────
#
# Les globals du script sont vides apres Execute() : impossible d'y garder la
# reference de la palette. sys.modules, lui, survit a la session Revit.

_CLE_ETAT = '__nm_batii_styles_surfaces_etat__'


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
    # Console d'execution fermee d'entree, a chaque appui sur le bouton. Elle ne
    # vit que le temps du script, alors que la palette lui survit : la laisser
    # ouverte revenait a afficher une premiere fenetre de logs, figee sur les
    # lignes du demarrage, a cote de la console durable ou tout le reste
    # s'ecrit. Voir _ouvrir_journal et _log.
    try:
        from pyrevit import script as _script_console
        _script_console.get_output().close()
    except Exception:
        pass

    # Filet de securite doublant « context: active-area-plan » du bundle.yaml.
    # Le contexte pyRevit grise le bouton du ruban, mais un raccourci clavier ou
    # un appel programmatique passent a cote : la palette ne doit jamais s'ouvrir
    # hors plan de surface, elle s'y refermerait aussitot.
    from Autodesk.Revit.DB import ViewType as _ViewType
    from pyrevit import HOST_APP as _HOST_CHK

    _vue_active = None
    try:
        _vue_active = _HOST_CHK.uidoc.ActiveView
    except Exception:
        _vue_active = None

    _vue_ok = (_vue_active is not None
               and _vue_active.ViewType == _ViewType.AreaPlan)

    if not _vue_ok:
        # Pas de `raise` ici : SystemExit derive de BaseException, il traverserait
        # le `except Exception` ci-dessous et remonterait tel quel a pyRevit.
        from dialogs.dialogs_styles_loader import show_alert
        show_alert(
            u"NM-BATII — Surfaces",
            u"Cet outil ne fonctionne que sur une vue de la famille système "
            u"« Plan de surface ».\n\nOuvrez un plan de surface, puis relancez "
            u"le bouton.")
    else:
        _etat = _etat_partage()
        _existante = getattr(_etat, 'palette', None)

        _vivante = False
        if _existante is not None:
            try:
                _vivante = not _existante._ferme
            except Exception:
                _vivante = False

        if _vivante:
            # Palette deja ouverte : la ramener devant et relire la table de
            # style, le projet actif ayant pu changer entre deux appuis.
            _existante.rafraichir()
            try:
                _existante.Activate()
            except Exception:
                pass
        else:
            _palette = FenetreStyles()
            _set_revit_owner(_palette)
            _etat.palette = _palette
            _palette.Show()

except Exception as e:
    try:
        from dialogs.dialogs_styles_loader import show_alert
        show_alert(u"NM-BATII — Échec", u"Erreur : {}".format(str(e)))
    except Exception:
        pass
