# 🚀 Workflow Gemini + Aider

## 📋 Prérequis

🐍 Python installé sur le poste. J'utilise ici la version 3.10.

🤖 **Aider** installé avec **pipx**. Pour rappel , la commande d'installation est la suivante :

```bash
pipx install --python C:\laragon\bin\python\python-3.10\python.exe aider-chat
```

[!IMPORTANT] NOTE : L'exécutable Python est appelé via son chemin absolu pour cibler l'environnement spécifique où sont installées toutes les dépendances du projet (**google-genai**, **pyreadline3**, etc.).
>Cela garantit l'étanchéité du workflow, même si une autre version de Python est prioritaire dans le PATH du système.

## 🛠️ Étape 1 : Installation du moteur (SDK)

L'IA utilisée par défaut est **Gemini**.
Pour installer ses bibliothèques Python :

```PowerShell
C:\laragon\bin\python\python-3.10\python.exe -m pip install -U google-genai
```

## 🔐 Étape 2 : Configuration de la sécurité (Variable d'environnement)

```PowerShell
# Définit la clé de façon permanente pour l'utilisateur
[Environment]::SetEnvironmentVariable("GEMINI_API_KEY", "LA_CLE_API_ICI", "User")
# Note : Redémarrer le terminal après cette commande
```

## 🌐 Étape 3 : Ajouter les fichiers dans le PATH

Pour que les commandes soient accessibles globalement, 
les scripts du projet doivent être déposés dans un répertoire ajouté au PATH ou dèjà inclus.
J'ai ici choisi le dossier `C:\Users\bulam\.local\bin`.

## 🧠 Fichier de prompt système

Pour que Gemini reste focalisé sur certains principes, sans avoir à les lui répéter constamment,
il est possible de lui fournir un fichier `prompt_system.txt`, contenant les directives. Par exemple :

```txt
Tu es un expert en Symfony et PHP 8.2+.
Ta mission est d'analyser le code fourni et de proposer des améliorations de modernisation.

STRUCTURE TA RÉPONSE :
1. ANALYSE :
Explique brièvement (en français) les changements nécessaires et pourquoi (ex : typage, attributs, performances).
2. INSTRUCTIONS POUR AIDER :
Termine ta réponse par une section claire commençant par "### ACTIONS POUR AIDER".
Dans cette section, donne des instructions directes et techniques que l'outil Aider pourra exécuter
(ex : "Remplace les annotations @Route par des Attributs #[Route]", "Ajoute le typage string à la propriété $name").

Sois précis et technique. Évite les bavardages inutiles.
```

Ce fichier **Prompt System** est importé à chaque appel du scrfipt **ask.py**, 
dans lequel un chemin par défaut a été ajouté : `C:\Users\mon_user\.local\bin\prompt_system.txt`.

##⚡Étape 4 : Création de la commande gemini (Alias Cmder) 

Pour faciliter l'appel du script **ask.py**, un alias peut être configuré. 
Pour cela, ouvrir le fichier `C:\laragon\bin\cmder\config\user_aliases.cmd` (ou le dossier cmder) et ajouter :

```DOS
gemini="C:\laragon\bin\python\python-3.10\python.exe" C:\Users\mon_user\.local\bin\ask.py $*
```

## ⌨️ Utilisation de l'alias **gemini**

Pour interroger **Gemini** depuis le terminal :

```bash
$ gemini "Génère un jeu du pendu en javascript"
```

Il est également possible de fournir le prompt sous la forme d'un fichier texte.
Par exemple, avec un fichier `prompt.txt` contenant la question précédente :

```bash
$ gemini -f prompt.txt
```

### 📂 Fournir du contexte

Pour fournir du contexte à Gemini, que ce soit des fichiers dont il doit avoir connaissance ou des fichiers à modifier,
on peut utiliser la commande **cat** :

```bash
$ cat app.js | gemini "Ajoute un formulaire de connexion au fichier app.js" 
```

Pour lire le prompt et le code source ensemble :

```bash
$ cat prompt.txt app.js | gemini
```

### Redirection de fichier

Si tout le contenu (instructions + code) est mis dans un seul fichier **audit.txt** :

```Bash
gemini < audit.txt
```

## Considération

**⚠️ Attention à la taille**

Bien que Gemini Flash accepte énormément de texte, envoyer tout un projet (ex: le dossier vendor/), 
aura pour conséquence d'épuiser le quota inutilement et de "noyer" l'IA dans des informations inutiles.

🎯 L'idée est de cibler : Instruction / prompt + 1 ou 2 fichiers **maximum** pour une précision optimale.

## 🤝 Coopération d'IA : Gemini + Aider

Le projet vise à optimiser un flux de travail utilisant Gemini comme cerveau et Aider comme acteur.

Pour ce faire, les deux outils sont installés globalement :

- Gemini est fourni par le SDK genai sous Python 3.10 (installation avec pip)
- Aider est installé avec pipx (donc dans un environnement virtuel, mais une visibilité globale)

L'idée est de faire coopérer les deux outils en passant la sortie de l'un à l'autre.

💾 Pour ne pas perdre l'historique des discussions, 
tout en fournissant un fichier qui contienne uniquement les informations pertinentes,
la dernière sortie est enregistrée seule dans un fichier `dernier_plan.md`, 
mais également ajoutée par concaténation à un autre fichier, nommé `historique_global.md`.

Dans ce cas, ce qui est exécuté par le script est la commande suivante :

```bash
$ gemini "Ma question" > dernier_plan.md & type dernier_plan.md >> historique_global.md
```

Pour exécuter cette commande de manière systématique, un alias **glog** (Gemini + Log) peut être ajouté :

```bash
$ glog=gemini $* > dernier_plan.md & type dernier_plan.md >> historique_global.md & type dernier_plan.md
```

Il s'utilise alors de cette façon :

```bash
$ glog "Analyse ce contrôleur pour PHP 8.2"
```

Et la sortie se trouve enregistrée dans les fichiers `dernier_plan.md` et `historique_global.md` de manière automatique.

## 🛠️ Exploiter la sortie avec **Aider**

Pour demander à **Aider** d'exécuter les dernières instructions listées par Gemini dans le fichier `dernier_plan.md` :

```bash
$ aider src/Controller/OldController.php --message "$(cat dernier_plan.md)"
```

Pour que **Gemini** produise un résultat exploitable par **Aider**, 
un fichier de contexte global `prompt_system.txt` est ajouté. Ce fichier est modifiable selon le contexte.
Par exemple :

```text
Tu es un expert en migration Symfony et PHP 8.2+.
Ta mission est d'analyser le code fourni et de proposer des améliorations de modernisation.

STRUCTURE TA RÉPONSE :
1. ANALYSE : Explique brièvement (en français) les changements nécessaires et pourquoi (ex: typage, attributs, performances).
2. INSTRUCTIONS POUR AIDER : Termine ta réponse par une section claire commençant par "### ACTIONS POUR AIDER". Dans cette section, donne des instructions directes et techniques que l'outil Aider pourra exécuter (ex: "Remplace les annotations @Route par des Attributs #[Route]", "Ajoute le typage string à la propriété $name").

Sois précis et technique. Évite les bavardages inutiles.
```

Il est automatiquement intégré lors de l'appel du script Python `ask.py` au moyen de la variable `system_prompt_path`.

>NOTE : pour que l'encodage UTF-8 généré par Gemini en raison du markdown ne génère pas d'erreur, 
> je force l'encodage UTF-8 pour Python.
>Pour ne pas avoir à saisir cette configuration à chaque ouverture d'un terminal, 
> je la place dans le fichier `Cmder C:\laragon\etc\cmder\user_profile.cmd` :

```bash
$ set PYTHONIOENCODING=utf-8
```

## ⚙️ Déclaration de variables d'environnement

Pour simplifier et harmoniser les chemins appelés depuis les scripts Python et les alias Cmder, 
les variables peuvent être déclarées dans le fichier de configuration du terminal 
(`C:\laragon\bin\cmder\config\user_profile.cmd`) :

```cmd
:: Ajout du dossier des scripts Gemini au PATH
set "PATH=C:\Users\mon_user\.local\bin;%PATH%"

:: Déclare l'encodage UTF-8 pour les scripts Python
set PYTHONIOENCODING=utf-8

:: Chemins vers les exécutables et scripts
set LOCAL_BIN=C:\Users\mon_user\.local\bin
set PYTHON_BIN=C:\laragon\bin\python\python-3.10\python.exe
set ASK_SCRIPT=C:\Users\mon_user\.local\bin\ask.py
```

## 🧠 Alias Gemini + journalisation

Un autre alias peut également être créé dans le fichier de configuration du terminal 
(`C:\laragon\bin\cmder\config\user_aliases.cmd`) : par exemple **glog** (Gemini + Log)

```cmd
glog=%PYTHON_BIN% %LOCAL_BIN%\glog.py $*
```

Cet alias fait alors appel au script **glog.py**, avec le contenu suivant :

```python
import sys
import subprocess
import datetime
import os

def run():
    # 1. Vérification et création du dossier de scripts si nécessaire
    # On récupère le chemin depuis l'environnement ou on utilise celui par défaut
    local_bin = os.environ.get('LOCAL_BIN', r'C:\Users\mon_user\.local\bin')
    if not os.path.exists(local_bin):
        try:
            os.makedirs(local_bin, exist_ok=True)
        except Exception as e:
            print(f"Erreur lors de la création du dossier {local_bin} : {e}")

    # 2. Récupérer le prompt passé en argument
    prompt = " ".join(sys.argv[1:])
    if not prompt:
        print("Erreur : Aucun prompt fourni.")
        return

    # Configuration des chemins
    ask_script = os.environ.get('ASK_SCRIPT', os.path.join(local_bin, 'ask.py'))
    python_bin = os.environ.get('PYTHON_BIN', 'python')
    hist_file = 'historique_global.md'
    plan_file = 'dernier_plan.md'

    # 3. Préparer l'en-tête de l'historique
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    divider = "=" * 50
    header = f"\n{divider}\nDATE   : {timestamp}\nPROMPT : {prompt}\n{'-' * 50}\n"

    try:
        with open(hist_file, 'a', encoding='utf-8') as h:
            h.write(header)
    except Exception as e:
        print(f"Erreur lors de l'écriture dans l'historique : {e}")

    # 4. Exécuter ask.py et capturer la sortie
    # stdin=sys.stdin permet de transmettre le flux (ex: cat fichier | glog)
    try:
        result = subprocess.run(
            [python_bin, ask_script, prompt],
            capture_output=True,
            text=True,
            encoding='utf-8',
            stdin=sys.stdin  # Transmet le contenu du pipe (ex: cat file | ...)
        )

        if result.returncode != 0:
            # On affiche l'erreur sur le flux d'erreur standard
            print(f"Erreur lors de l'exécution de Gemini :\n{result.stderr}", file=sys.stderr)
            return

        # 5. Écrire dans dernier_plan.md et historique_global.md
        content = result.stdout
        
        with open(plan_file, 'w', encoding='utf-8') as p:
            p.write(content)

        with open(hist_file, 'a', encoding='utf-8') as h:
            h.write(content)

        # 6. Afficher le résultat dans le terminal
        print(content)

    except Exception as e:
        print(f"Une erreur système est survenue : {e}")

if __name__ == "__main__":
    run()
```

Ce script demande à l'IA d'effectuer les actions suivantes :
- récupère le prompt passé en argument de la commande
- appelle le script `ask.py` avec le prompt précédent en argument
- affiche la réponse en corrigeant l'encodage
- enregistre la réponse dans le fichier `dernier_plan.md`
- ajoute la réponse dans le fichier `historique_global.md`, précédée du prompt et datée

De cette manière, un historique complet du flux de questions et réponses de la discussion est conservée.

## 🏃 Alias **ago** (Aider Go)

Pour simplifer l'appel à **Aider**, 
un alias **ago** (Aider Go !) peut être créé dans le fichier de configuration du terminal 
(`C:\laragon\bin\cmder\config\user_aliases.cmd`) :

```cmd
ago=aider --no-gitignore --no-auto-commits --message-file dernier_plan.md $*
```

Cet alias appel **Aider** en lui passant en argument le fichier `dernier_plan.md` généré par Gemini.

Il précise également de ne pas faire de commit et de ne pas demander l'ajout du fichier `.env` à chaque appel.
Charge au développeur de faire ces actions après revue et validation des modifications.

## 📜 Le prompt_system d'Aider

À chaque initialisation, **Aider** recherche à la racine du projet un fichier nommé `instruction.md`,
dont il charge les directives en tant que **System Prompt** qui s'ajoute au message.

La répartition des rôles entre **Gemini** et **Aider** devient donc celle-ci :

**glog** (Gemini) : C'est l'architecte qui analyse le code, 
réfléchit à la stratégie et produit le fichier `dernier_plan.md`. 
Il n'a pas connaissance du fichier `.aider.instructions.md` (à moins de le lui donner explicitement).

**ago** (Aider) : C'est l'ouvrier spécialisé. 
Il prend le plan de l'architecte (`--message-file dernier_plan.md`) 
et l'exécute en respectant ses propres consignes de sécurité ou de style 
(celles contenues dans `.aider.instructions.md`).

Voici un exemple de ce prompt :

```md
# Instructions

Tu agis en tant qu'exécuteur technique. 
Ta priorité absolue est d'appliquer les changements décrits dans le message de l'utilisateur 
(qui provient d'un plan d'analyse Gemini).

## Principes d'application

1. **Fidélité au plan :** 
    - Applique scrupuleusement les modifications demandées dans la section "ACTIONS POUR AIDER" du message.

2. **Standard de structure :**
   - Assure-toi que `declare(strict_types=1);` est présent.
   - Si le plan demande des Attributs PHP 8, 
     supprime systématiquement les anciennes annotations DocBlock correspondantes pour éviter les doublons.

3. **Cohérence Symfony :**
   - Utilise l'injection par constructeur si le plan mentionne l'ajout de services.
   - Respecte le typage strict (arguments et types de retour) même si le plan est incomplet sur ce point.

4. **Auto-correction :** 
   - Si le plan suggère une syntaxe obsolète (rare avec Gemini), privilégie toujours la syntaxe moderne PHP 8.2+.

Concentre-toi sur l'édition parfaite du code source.

## Validation de contexte

- Avant d'appliquer le plan, vérifie si les classes ou services mentionnés existent réellement dans le projet.
- Si le plan suggère une classe inexistante, mais qu'une alternative équivalente existe dans le projet, 
  privilégie l'alternative locale.
- En cas de contradiction majeure entre le plan et l'architecture actuelle du projet, 
  propose une correction dans le chat avant d'éditer le fichier.
```

## 💬 Saisie interactive

Pour faciliter les saisies complexes, un script interactif a été créé : **glog_interactive.py**. 
Il ajoute les fonctionnalités suivantes :

- ✨ auto-complétion des chemins des fichiers fournis en contexte
- ✂️ possibilité de fournir une ou plusieurs parties d'un même fichier en les délimitant (par ex : 100-150)
- 🌀 ajout d'un spinner pour signifier que la recherche est en cours

### Installation de la librairie pyreadline3

Pour récupérer les chemins et permettre l'auto-complétion sous Windows, 
il faut installer la librairie pyreadline3 :

```bash
pip install pyreadline3
```

Le script peut être appelé depuis un alias, par exemple **glogi** :

```cmd
:: alias interrogeant l'IA de manière interractive
glogi=%PYTHON_BIN% %LOCAL_BIN%\glog_interactive.py
```

## Utilisation de l'alias

Il suffit de saisir l'alias (**glogi** ici) dans le terminal :

```bash
$ glogi
=== ASSISTANT DE CONTEXTE GEMINI ===
Votre question / instruction : "Modifie le controller HomeController et sa vue de manière à afficher le calcul de la TVA en utilisant le service VatCalculator"                               
                                                                                                                                                                                              
Fichier à ajouter (TAB pour compléter, Entrée pour terminer) : src\Controller\HomeController.php                                                                                              
Plages de lignes pour 'src\Controller\HomeController.php' (ex: 1-20,150-180 ou Entrée pour tout) :                                                                                            
                                                                                                                                                                                              
Fichier à ajouter (TAB pour compléter, Entrée pour terminer) : tem                                                                                                                            
templates\   temp_ctx.txt                                                                                                                                                                     
                                                                                                                                                                                              
Fichier à ajouter (TAB pour compléter, Entrée pour terminer) : templates\home\index.html.twig                                                                                                 
Plages de lignes pour 'templates\home\index.html.twig' (ex: 1-20,150-180 ou Entrée pour tout) : src\Service\Va                                                                                
src\Service\VatCalculator.php          src\Service\VatCalculatorInterface.php                                                                                                                 
Plages de lignes pour 'templates\home\index.html.twig' (ex: 1-20,150-180 ou Entrée pour tout) : src\Service\VatCalculator.php                                                                 
                                                                                                                                                                                              
Fichier à ajouter (TAB pour compléter, Entrée pour terminer) :                                                                                                                                
                                                                                                                                                                                              
=== RÉPONSE DE GEMINI ===                                                                                                                                                                     
                                                                                                                                                                                              
1. ANALYSE :                                                                                                                                                                                  
                                                                                                                                                                                              
Le code du contrôleur `HomeController` est déjà très moderne
...
