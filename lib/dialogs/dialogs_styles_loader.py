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
from System.IO import StreamReader
from System.Windows.Markup import XamlReader
from System.Windows import Application
from pyrevit import forms

_ALERT_XAML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "AlertWindow.xaml")


def show_alert(title, message):
    """Affiche un message dans le style graphique de l'extension NM-BATII."""
    try:
        w = forms.WPFWindow(_ALERT_XAML)
        w.Title = title
        w.txtMessage.Text = message
        w.btnClose.Click += lambda s, e: setattr(w, 'DialogResult', True)
        w.ShowDialog()
    except Exception:
        forms.alert(message, title=title)

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
            forms.alert(
                "💥 Erreur lors du chargement du style :\n{0}".format(str(e)),
                title="⚠️ Chargement WPF"
            )
            return False
    else:
        forms.alert(
            "📄 Fichier introuvable :\n{0}".format(style_path),
            title="⚠️ Fichier manquant"
        )
        return False
