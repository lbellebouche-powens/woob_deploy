# woob-deploy

Script d'automatisation pour mettre à jour la dépendance Woob et créer une release bugfix sur le dépôt backend Budgea.

## Prérequis

### Outils systeme requis

| Outil       | Usage                                    |
|-------------|------------------------------------------|
| `git`       | Gestion des branches, commits et tags    |
| `make`      | Exécution de `make update-lock/woob`     |
| `uv`        | Gestionnaire de paquets Python           |
| `debchange` | Mise à jour du changelog Debian (`devscripts`) |
| `gh`        | Création des PRs GitHub (optionnel)      |

Installation des outils Debian :
```bash
apt install devscripts
```

### Python >= 3.9

## Installation

```bash
git clone <repo-url> woob_deploy
cd woob_deploy
uv sync
```

## Utilisation

### Commande de base (version auto-incrementée)

Incrémente automatiquement le patch de la version courante (`11.8.18` → `11.8.19`) :

```bash
uv run woob-update-release --repo ~/dev/backend
```

### Spécifier une version cible

```bash
uv run woob-update-release --repo ~/dev/backend --version 11.8.19
```

### Sans installation (exécution directe)

```bash
uv run python woob_update_release.py --repo ~/dev/backend
```

## Workflow automatisé

Le script exécute 6 étapes dans l'ordre :

| Etape | Description |
|-------|-------------|
| **1 - Initialisation** | Vérifie que le working tree est propre, checkout `master`, pull, crée la branche `hotfix/X.Y.Z` |
| **2 - Version bump** | Met à jour la version dans `pyproject.toml`, `setup.py`, `budgea/__init__.py` |
| **3 - Mise à jour Woob** | Lance `make update-lock/woob`, commit le `uv.lock` avec la nouvelle version Woob |
| **4 - Changelog Debian** | Génère une entrée dans `debian/changelog` via `debchange`, pause pour relecture |
| **5 - Finalisation** | Commit les fichiers de release, crée le tag Git, propose le push de la branche et du tag |
| **6 - Pull Requests** | (Optionnel) Crée les PRs GitHub vers `master` et `develop` via `gh` |

## Options CLI

```
usage: woob-update-release [-h] --repo PATH [--version X.Y.Z]

options:
  --repo PATH      Chemin vers la racine du dépôt backend git (obligatoire)
  --version X.Y.Z  Version cible (défaut : auto-increment du patch courant)
```

## Structure du dépôt backend attendue

Le script suppose que le dépôt backend contient :

```
backend/
├── budgea/__init__.py     # __version__ = "X.Y.Z"
├── pyproject.toml         # version = "X.Y.Z"
├── setup.py               # version = "X.Y.Z"
├── debian/changelog
└── uv.lock
```

## Variables d'environnement pour le changelog Debian

Le script récupère automatiquement `user.email` et `user.name` depuis la config Git. En leur absence, il utilise les valeurs par défaut :

- `DEBEMAIL=ci@powens.com`
- `DEBFULLNAME=Powens CI`

Pour les surcharger :
```bash
DEBEMAIL=you@example.com DEBFULLNAME="Your Name" uv run woob-update-release --repo ~/dev/backend
```
