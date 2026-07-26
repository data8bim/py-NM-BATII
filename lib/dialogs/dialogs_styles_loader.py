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
import os

# Les assemblies WPF/WinForms ne sont PAS chargees par defaut dans le moteur
# IronPython de pyRevit : elles n'arrivent que si un module tiers les a deja
# referencees (typiquement 'pyrevit.forms'). Comme ce module partage peut etre
# importe en tout premier par un script (ex. 02_Mises_a_jour), on les reference
# explicitement ici, sinon : ImportError: No module named Windows.
import clr
clr.AddReference('PresentationFramework')   # Application, Controls, Documents, Markup.XamlReader
clr.AddReference('PresentationCore')        # Visibility, TextAlignment
clr.AddReference('WindowsBase')             # GridLength, GridUnitType
clr.AddReference('System.Windows.Forms')    # MessageBox (fallback ultime)

from System.IO import StreamReader
from System.Windows.Markup import XamlReader
from System.Windows import Application, Visibility, FrameworkElement, TextAlignment
from System.Windows.Controls import Grid, Button, ColumnDefinition
from System.Windows.Documents import Run, Bold
from System.Windows import GridLength, GridUnitType
from System.Windows.Forms import MessageBox, MessageBoxButtons, DialogResult as WinDialogResult
from pyrevit import forms

_ALERT_XAML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "AlertWindow.xaml")


def _set_rich_text(text_block, message):
    """
    Affecte 'message' à un TextBlock en interprétant les segments encadrés
    par '**' comme du texte en gras (léger sous-ensemble Markdown). Les
    messages sans '**' s'affichent exactement comme avec 'Text = message'.
    """
    text_block.Inlines.Clear()
    segments = message.split(u'**')
    for i, part in enumerate(segments):
        if not part:
            continue
        if i % 2 == 1:
            b = Bold()
            b.Inlines.Add(Run(part))
            text_block.Inlines.Add(b)
        else:
            text_block.Inlines.Add(Run(part))


def show_alert(title, message, close_label=None, centrer=False):
    """
    Affiche un message dans le style graphique de l'extension NM-BATII.

    close_label : libellé du bouton de fermeture. Si None (par défaut), le
        libellé défini dans AlertWindow.xaml ("Fermer") est conservé — ne rien
        changer aux scripts existants. Passer par ex. u'Retour' quand le
        message ne met pas fin à l'opération et que l'utilisateur revient à
        un dialogue resté ouvert.
    centrer : True pour centrer le texte. Réservé aux messages courts d'une
        ou deux lignes. Laisser False (défaut) pour tout message multi-lignes
        ou en colonnes — les diagnostics de convention de nommage, par
        exemple, deviendraient illisibles une fois centrés.
    """
    try:
        w = forms.WPFWindow(_ALERT_XAML)
        w.Title = title
        _set_rich_text(w.txtMessage, message)
        if close_label:
            w.btnClose.Content = close_label
        if centrer:
            w.txtMessage.TextAlignment = TextAlignment.Center
        w.btnClose.Click += lambda s, e: setattr(w, 'DialogResult', True)
        w.ShowDialog()
    except Exception:
        # Dernier recours : boîte de dialogue Windows native (pas pyRevit).
        MessageBox.Show(message, title)


def show_confirm(title, message, yes_label=u'Oui', no_label=u'Non',
                  yes_style_key=u'NMButtonAppliquer',
                  no_style_key=u'NMButtonAnnuler', no_width=130):
    """
    Affiche une confirmation Oui/Non dans le style graphique de l'extension
    NM-BATII (remplace le bouton "Fermer" d'AlertWindow.xaml par deux
    boutons). Retourne True si l'utilisateur clique sur le bouton "yes_label",
    False sinon.

    yes_label / no_label : libellés des boutons (par défaut "Oui"/"Non" —
        laisser tel quel pour ne rien changer aux scripts existants).
    yes_style_key / no_style_key : nom d'un style partagé défini dans
        dialogs_styles.xaml (chargé via load()) à appliquer dynamiquement au
        bouton correspondant — ignoré si le style n'est pas trouvé. Par défaut
        'NMButtonAppliquer'/'NMButtonAnnuler', soit le pied de dialogue
        standard NM-BATII. Passer None pour n'appliquer aucun style.
    no_width : largeur fixe (en pixels) du bouton "no" ; le bouton "yes"
        occupe alors tout le reste de la largeur de la fenêtre. 130 par défaut,
        largeur du bouton de sortie standard. Passer None pour que les deux
        boutons se partagent la largeur à parts égales.
    """
    result = [False]
    try:
        w = forms.WPFWindow(_ALERT_XAML)
        w.Title = title
        _set_rich_text(w.txtMessage, message)

        btn_grid = Grid()
        c1 = ColumnDefinition(); c1.Width = GridLength(1, GridUnitType.Star)
        c2 = ColumnDefinition(); c2.Width = GridLength(8)
        c3 = ColumnDefinition()
        c3.Width = GridLength(no_width) if no_width else GridLength(1, GridUnitType.Star)
        btn_grid.ColumnDefinitions.Add(c1)
        btn_grid.ColumnDefinitions.Add(c2)
        btn_grid.ColumnDefinitions.Add(c3)

        # Pas de Height impose ici : la hauteur (40) vient des styles partages.
        btn_yes = Button(); btn_yes.Content = yes_label
        Grid.SetColumn(btn_yes, 0)
        btn_no = Button(); btn_no.Content = no_label
        Grid.SetColumn(btn_no, 2)

        if yes_style_key:
            try:
                btn_yes.SetResourceReference(FrameworkElement.StyleProperty, yes_style_key)
            except Exception:
                pass
        if no_style_key:
            try:
                btn_no.SetResourceReference(FrameworkElement.StyleProperty, no_style_key)
            except Exception:
                pass

        def _on_yes(s, e):
            result[0] = True
            setattr(w, 'DialogResult', True)

        def _on_no(s, e):
            result[0] = False
            setattr(w, 'DialogResult', False)

        btn_yes.Click += _on_yes
        btn_no.Click += _on_no
        btn_grid.Children.Add(btn_yes)
        btn_grid.Children.Add(btn_no)

        w.btnClose.Visibility = Visibility.Collapsed
        parent_grid = w.btnClose.Parent
        Grid.SetRow(btn_grid, Grid.GetRow(w.btnClose))
        parent_grid.Children.Add(btn_grid)

        w.ShowDialog()
    except Exception:
        # Dernier recours : boîte de dialogue Windows native (pas pyRevit).
        r = MessageBox.Show(message.replace(u'**', u''), title, MessageBoxButtons.YesNo)
        result[0] = (r == WinDialogResult.Yes)
    return result[0]

# ✅ FIX : chemin résolu depuis __file__ (robuste quel que soit l'emplacement
# d'installation de l'extension sur le poste).
# dialogs_styles_loader.py est dans lib\dialogs\
# dialogs_styles.xaml   est dans lib\dialogs\  → même dossier
_this_dir = os.path.dirname(os.path.abspath(__file__))


def load(file_name="dialogs_styles.xaml", subfolder="dialogs", lib_dir=None):
    """
    Charge un fichier XAML et l'ajoute aux styles WPF globaux.

    Parameters:
        file_name (str): Nom du fichier XAML à charger.
        subfolder (str): Dossier dans lib_dir où se trouve le fichier (fallback uniquement).
        lib_dir (str): Chemin racine de la bibliothèque (fallback si chemin relatif introuvable).

    Returns:
        bool: True si le chargement réussit, False sinon.
    """
    # 1) Chemin prioritaire : relatif à ce fichier (indépendant du poste)
    style_path = os.path.join(_this_dir, file_name)

    # 2) Fallback : lib_dir passé en argument (ancienne méthode)
    if not os.path.isfile(style_path) and lib_dir:
        style_path = os.path.join(lib_dir, subfolder, file_name)

    if os.path.isfile(style_path):
        try:
            with StreamReader(style_path) as reader:
                resource_dict = XamlReader.Load(reader.BaseStream)

                # Évite le doublon
                already_loaded = any(
                    hasattr(d, "Source") and d.Source == resource_dict.Source
                    for d in Application.Current.Resources.MergedDictionaries
                    if hasattr(d, "Source")
                )

                if not already_loaded:
                    Application.Current.Resources.MergedDictionaries.Add(resource_dict)

            return True
        except Exception as e:
            MessageBox.Show(
                "Erreur lors du chargement du style :\n{0}".format(str(e)),
                "Chargement WPF"
            )
            return False
    else:
        MessageBox.Show(
            "Fichier introuvable :\n{0}".format(style_path),
            "Fichier manquant"
        )
        return False
