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


#__title__ = 'Mise à jour'
#__author__ = 'data8bim (d8b)'

import os
import sys
import json
import codecs
import shutil
import tempfile

# Feuille de styles WPF partagee (lib/dialogs/dialogs_styles.xaml) : rend
# disponibles les cles NMButtonAppliquer / NMButtonAnnuler utilisees par les
# pieds de dialogue. Tous les styles y sont nommes (x:Key), le chargement
# n'applique donc rien de lui-meme aux controles existants.
_lib = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'lib')
if _lib not in sys.path:
    sys.path.insert(0, _lib)
from dialogs.dialogs_styles_loader import load as _charger_styles
_charger_styles()

import clr
clr.AddReference('System')
clr.AddReference('System.Net')
import System
from System.Net import WebClient, WebException, ServicePointManager, SecurityProtocolType

# Forcer TLS 1.2 — requis par GitHub (le défaut .NET Framework est TLS 1.0)
ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12

from pyrevit import forms, script

output = script.get_output()


# ---------------------------------------------------------------------------
# Chargement config + extension.json
# ---------------------------------------------------------------------------
def _find_extension_dir():
    cur = os.path.dirname(os.path.abspath(__file__))
    while not cur.lower().endswith('.extension'):
        parent = os.path.dirname(cur)
        if parent == cur:
            raise IOError(u"Dossier .extension introuvable depuis : " + cur)
        cur = parent
    return cur


def load_config():
    ext_dir = _find_extension_dir()
    cfg_path = os.path.join(ext_dir, 'config.json')
    ext_path = os.path.join(ext_dir, 'extension.json')
    with codecs.open(cfg_path, 'r', 'utf-8') as f:
        cfg = json.load(f)
    with codecs.open(ext_path, 'r', 'utf-8') as f:
        ext_data = json.load(f)
    return ext_dir, cfg_path, cfg, ext_data


# ---------------------------------------------------------------------------
# Helpers log
# ---------------------------------------------------------------------------
_logs_actifs = [False]


def log(msg):
    if _logs_actifs[0]:
        output.print_md(msg)


# ---------------------------------------------------------------------------
# Lecture version distante
# ---------------------------------------------------------------------------
def _github_url_to_raw(github_url, branch, sub_path):
    """Convertit une URL GitHub en URL raw.githubusercontent.com."""
    base = github_url.rstrip('/')
    base = base.replace('https://github.com/', 'https://raw.githubusercontent.com/')
    return '{0}/{1}/{2}'.format(base, branch, sub_path)


def get_remote_version_github(github_url):
    """
    Lit extension.json depuis GitHub (racine du repo, branche master puis main).
    Retourne (version, branche_utilisee).

    Le repo GitHub de production a extension.json à la racine :
      https://github.com/data8bim/py-NM-BATII/blob/master/extension.json
    """
    # extension.json est à la racine du repo (pas dans un sous-dossier)
    sub = 'extension.json'
    last_errors = []
    for branch in ('master', 'main'):
        url = _github_url_to_raw(github_url, branch, sub)
        log(u"Tentative GitHub ({0}) : {1}".format(branch, url))
        try:
            wc = WebClient()
            wc.Encoding = System.Text.Encoding.UTF8
            content = wc.DownloadString(url)
            data = json.loads(content)
            version = data.get('templates', {}).get('version', u'?')
            log(u"Version distante trouvee ({0}) : {1}".format(branch, version))
            return version, branch
        except WebException as wex:
            detail = str(wex.Message) if hasattr(wex, 'Message') else str(wex)
            last_errors.append(u"[{0}] {1}".format(branch, detail))
            log(u"WebException branche {0} : {1}".format(branch, detail))
            continue
        except Exception as ex:
            raise Exception(u"Erreur lecture GitHub ({0}) : {1}".format(branch, str(ex)))
    raise Exception(
        u"Impossible de lire extension.json depuis GitHub.\n\n"
        u"URL testée :\n"
        u"  {0}\n\n"
        u"Détail :\n{1}\n\n"
        u"Vérifiez l'URL et votre connexion internet."
        .format(
            _github_url_to_raw(github_url, 'master', sub),
            u"\n".join(last_errors)
        )
    )


def get_remote_version_serveur(serveur_path):
    """Lit extension.json depuis un chemin réseau/local."""
    ext_json = os.path.join(serveur_path, 'PyNM-BATII.extension', 'extension.json')
    log(u"Lecture version serveur : " + ext_json)
    if not os.path.isfile(ext_json):
        raise Exception(
            u"Fichier introuvable :\n{0}\n\nVérifiez le chemin configuré.".format(ext_json)
        )
    with codecs.open(ext_json, 'r', 'utf-8') as f:
        data = json.load(f)
    version = data.get('templates', {}).get('version', u'?')
    log(u"Version distante trouvee : " + version)
    return version, None


# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------
def _copy_tree(src, dst):
    """Copie récursive src → dst, écrase les fichiers existants."""
    for root, dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        dst_dir = os.path.join(dst, rel) if rel != '.' else dst
        if not os.path.exists(dst_dir):
            os.makedirs(dst_dir)
        for fname in files:
            src_file = os.path.join(root, fname)
            dst_file = os.path.join(dst_dir, fname)
            shutil.copy2(src_file, dst_file)
            log(u"  Copie : " + os.path.join(rel, fname))


# Dossiers/fichiers gérés par la MAJ (config.json exclu — sauvegardé séparément)
_MANAGED_ITEMS = ['lib', 'NM-BATII.tab', 'extension.json']


def _clean_install(source_dir, extension_dir):
    """
    Installation propre :
    1. Sauvegarde config.json → config.json_OLD (écrase si existant)
    2. Supprime les dossiers/fichiers gérés par la MAJ
    3. Copie les nouveaux fichiers (config.json inclus — version de la MAJ)
    """
    # 1. Sauvegarde config.json utilisateur
    cfg_path = os.path.join(extension_dir, 'config.json')
    cfg_old_path = cfg_path + '_OLD'
    if os.path.isfile(cfg_path):
        shutil.copy2(cfg_path, cfg_old_path)
        log(u"config.json sauvegardé → config.json_OLD")

    # 2. Suppression propre des anciens fichiers gérés
    for item in _MANAGED_ITEMS:
        item_path = os.path.join(extension_dir, item)
        if os.path.isdir(item_path):
            shutil.rmtree(item_path)
            log(u"Supprimé (dossier) : " + item)
        elif os.path.isfile(item_path):
            os.remove(item_path)
            log(u"Supprimé (fichier) : " + item)

    # 3. Copie de la nouvelle version complète
    log(u"Copie des nouveaux fichiers...")
    _copy_tree(source_dir, extension_dir)


def install_from_github(github_url, branch, extension_dir):
    """Télécharge le ZIP GitHub et l'installe proprement dans extension_dir."""
    zip_url = github_url.rstrip('/') + '/archive/refs/heads/{0}.zip'.format(branch)
    log(u"Téléchargement : " + zip_url)

    tmp_dir = tempfile.mkdtemp(prefix='nm_batii_maj_')
    try:
        zip_path = os.path.join(tmp_dir, 'update.zip')
        wc = WebClient()
        wc.DownloadFile(zip_url, zip_path)
        log(u"Archive téléchargée : " + zip_path)

        clr.AddReference('System.IO.Compression.FileSystem')
        from System.IO.Compression import ZipFile
        extract_dir = os.path.join(tmp_dir, 'extracted')
        ZipFile.ExtractToDirectory(zip_path, extract_dir)
        log(u"Archive extraite dans : " + extract_dir)

        # Dans le ZIP GitHub la structure est : {repo}-{branch}/ contenant
        # directement les fichiers de l'extension (extension.json, lib/, NM-BATII.tab/, ...)
        repo_name = github_url.rstrip('/').split('/')[-1]
        source_dir = os.path.join(extract_dir, '{0}-{1}'.format(repo_name, branch))
        if not os.path.isdir(source_dir):
            raise Exception(
                u"Dossier introuvable dans l'archive.\n"
                u"Structure attendue : {0}-{1}/".format(repo_name, branch)
            )

        _clean_install(source_dir, extension_dir)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def install_from_serveur(serveur_path, extension_dir):
    """Installe proprement l'extension depuis un chemin réseau/local."""
    source_dir = os.path.join(serveur_path, 'PyNM-BATII.extension')
    if not os.path.isdir(source_dir):
        raise Exception(
            u"Dossier PyNM-BATII.extension introuvable dans :\n{0}".format(serveur_path)
        )
    log(u"Source serveur : " + source_dir)
    _clean_install(source_dir, extension_dir)


# ---------------------------------------------------------------------------
# Dialogue de résultat (post-installation)
# ---------------------------------------------------------------------------
def _show_result(title, message):
    """Affiche une MessageBox Windows native (aucune dépendance fichier)."""
    clr.AddReference('PresentationFramework')
    from System.Windows import MessageBox, MessageBoxButton, MessageBoxImage
    MessageBox.Show(message, title, MessageBoxButton.OK, MessageBoxImage.Information)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    extension_dir, cfg_path, cfg, ext_data = load_config()
    _logs_actifs[0] = cfg.get('activer_logs_scripts', False)

    version_installee = ext_data.get('templates', {}).get('version', u'?')
    log(u"Version installée : " + version_installee)

    maj_cfg = cfg.get('mises_a_jour', {})
    source_url = maj_cfg.get('source_url', u'https://github.com/data8bim/py-NM-BATII').strip()

    if not source_url:
        forms.alert(
            u"Aucune source de mise à jour configurée.\n\n"
            u"Allez dans Paramètres > onglet LOG > groupe Mises à jour "
            u"et renseignez l'URL GitHub ou le chemin réseau.",
            title=u"Configuration manquante"
        )
        return

    is_github = source_url.lower().startswith('http')
    log(u"Source : {0} ({1})".format(source_url, u'GitHub' if is_github else u'Serveur'))

    # --- Vérification de la version disponible ---
    version_dispo = None
    branch_utilisee = None
    erreur = None
    try:
        if is_github:
            version_dispo, branch_utilisee = get_remote_version_github(source_url)
        else:
            version_dispo, branch_utilisee = get_remote_version_serveur(source_url)
    except Exception as ex:
        erreur = str(ex)
        log(u"Erreur : " + erreur)

    # --- Fenêtre de résultat ---
    xaml = os.path.join(os.path.dirname(__file__), 'MajWindow.xaml')
    dlg = forms.WPFWindow(xaml)
    dlg.Title = u"Mise à jour NM-BATII"
    dlg.txtVersionInstallee.Text = version_installee

    _do_install = [False]

    if erreur:
        dlg.txtVersionDispo.Text = u"Erreur de connexion"
        dlg.txtVersionDispo.Foreground = System.Windows.Media.Brushes.Crimson
        dlg.statusBar.Background = System.Windows.Media.Brushes.Crimson
        dlg.msgBorder.Background = System.Windows.Media.SolidColorBrush(
            System.Windows.Media.Color.FromRgb(255, 240, 240))
        dlg.msgBorder.BorderBrush = System.Windows.Media.Brushes.Crimson
        dlg.txtMessage.Text = u"Impossible de vérifier la version disponible :\n\n{0}".format(erreur)
        dlg.txtMessage.Foreground = System.Windows.Media.Brushes.Crimson
        dlg.btnInstaller.IsEnabled = False

    elif version_dispo and version_dispo != version_installee:
        dlg.txtVersionDispo.Text = version_dispo
        dlg.txtVersionDispo.Foreground = System.Windows.Media.SolidColorBrush(
            System.Windows.Media.Color.FromRgb(0, 140, 0))
        dlg.statusBar.Background = System.Windows.Media.SolidColorBrush(
            System.Windows.Media.Color.FromRgb(0, 140, 0))
        dlg.txtMessage.Text = (
            u"Une nouvelle version est disponible !\n\n"
            u"Cliquez sur « Installer la mise à jour » pour lancer l'installation.\n"
            u"Après l'installation, relancez Revit pour appliquer les changements."
        )
        dlg.btnInstaller.IsEnabled = True

    else:
        dlg.txtVersionDispo.Text = version_dispo or u'?'
        dlg.txtMessage.Text = u"L'extension NM-BATII est déjà à jour."
        dlg.btnInstaller.IsEnabled = False

    def _on_installer(s, e):
        _do_install[0] = True
        setattr(dlg, 'DialogResult', True)

    dlg.btnInstaller.Click += _on_installer
    dlg.btnFermer.Click += lambda s, e: setattr(dlg, 'DialogResult', False)
    dlg.show_dialog()

    # --- Installation ---
    if not _do_install[0]:
        return

    log(u"Lancement de l'installation...")
    try:
        if is_github:
            install_from_github(source_url, branch_utilisee, extension_dir)
        else:
            install_from_serveur(source_url, extension_dir)

        msg_ok = (
            u"Mise à jour installée avec succès !\n\n"
            u"Version installée : {0}\n\n"
            u"Veuillez relancer Revit pour appliquer les changements."
        ).format(version_dispo)
        log(u"Installation terminée.")
        _show_result(u"Mise à jour réussie", msg_ok)

    except Exception as ex:
        msg_err = (
            u"Erreur lors de l'installation de la mise à jour :\n\n{0}\n\n"
            u"L'extension n'a pas été modifiée."
        ).format(str(ex))
        log(u"ERREUR installation : " + str(ex))
        _show_result(u"Erreur de mise à jour", msg_err)


if __name__ == '__main__':
    main()
