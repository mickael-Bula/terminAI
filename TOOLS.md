# Remplace Aider par des tools

Aider consomme trop de tokens. 
On va donc le remplacer par des tools dont le rôle sera d'appliquer des diffs générés par l'IA.

## Plan

- supprimer Aider
- modifier le prompt_system pour demander des diffs
- ajouter des tools pour appliquer les diffs
- ajouter des tools pour rechercher, remplacer, éditer...

## Modif du prompt system

```md
"Tu agis comme un expert en refactoring. Pour chaque modification, utilise impérativement ce format :

FILE: chemin/du/fichier
SEARCH:
le code exact à trouver
REPLACE:
le nouveau code
END"
```

## diffs tool

Le fichier ayant pour fonction d'appliquer les diffs : `apply_edits.py` :

```python
import re
import os

def apply_gemini_edits(content):
    # Regex pour capturer les blocs FILE, SEARCH, REPLACE, END
    # Supporte les variations de guillemets et d'espaces
    pattern = r"FILE:\s*[`']?(.*?)`?\s*SEARCH:\s*(.*?)\s*REPLACE:\s*(.*?)\s*END"
    matches = re.findall(pattern, content, re.DOTALL)
    
    if not matches:
        print("ℹ️ Aucun bloc de modification trouvé.")
        return

    for file_path, search_text, replace_text in matches:
        # Nettoyage des chemins et des backticks
        file_path = file_path.strip().replace('`', '').replace("'", "")
        
        # Nettoyage des blocs de code markdown potentiels (```javascript ...)
        def clean_block(t):
            t = t.strip()
            t = re.sub(r'^```[a-z]*\n', '', t) # Enlève le début du bloc markdown
            t = re.sub(r'\n```$', '', t)      # Enlève la fin du bloc markdown
            return t.strip('`')               # Enlève les backticks résiduels

        search_text = clean_block(search_text)
        replace_text = clean_block(replace_text)
        
        # --- CAS 1 : NOUVEAU FICHIER ---
        # Si le chemin est "NEW_FILE" ou si SEARCH contient "NEW_FILE"
        if file_path == "NEW_FILE" or "NEW_FILE" in search_text:
            # Note: Dans ton fichier .md, le chemin du nouveau fichier semble 
            # être manquant dans le champ FILE. On va essayer de le déduire ou 
            # forcer index.js pour ton cas précis.
            target_path = "assets/js/index.js" if file_path == "NEW_FILE" else file_path
            
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            with open(target_path, 'w', encoding='utf-8') as f:
                f.write(replace_text)
            print(f"🆕 Fichier créé : {target_path}")
            
        # --- CAS 2 : MODIFICATION ---
        else:
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    file_content = f.read()
                
                if search_text in file_content:
                    new_content = file_content.replace(search_text, replace_text)
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(new_content)
                    print(f"✅ Modifié : {file_path}")
                else:
                    print(f"❌ Texte SEARCH non trouvé dans : {file_path}")
            else:
                print(f"⚠️ Fichier introuvable : {file_path}")

# --- EXECUTION ---
if __name__ == "__main__":
    nom_fichier = "dernier_plan.md"
    
    if os.path.exists(nom_fichier):
        with open(nom_fichier, 'r', encoding='utf-8') as f:
            plan_content = f.read()
        
        print(f"Lecture de {nom_fichier}...")
        apply_gemini_edits(plan_content)
    else:
        print(f"Erreur : Le fichier {nom_fichier} est introuvable.")
```

## Utilisation du script

Passez simplement la réponse texte de Gemini à la fonction `apply_gemini_edits`.

## Annuler les modifications rapidement

Une commande : `git checkout .`. Elle supprime toutes les modifications qui ne sont pas dans la **staging area**.



