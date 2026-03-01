# ===== TUNNEL CLOUDFLARE =====

## Problématique

Lors d'un requête vers Openrouter derrière un proxy, la traversée de celui-ci supprime la clé API des headers.
Pour contourner le problème, je crée donc un relais passant par mon homelab, qui ajoute la clé API aux requêtes.

## Architecture

Cloudflare Tunnel (via cloudflared) est la solution idéale : contrairement à une redirection de port classique (port forwarding), 
elle ne demande aucune ouverture de port entrant sur la box internet, n'exposant pas le homelab sur le net.

### Zéro exposition

Le serveur Proxmox initie une connexion sortante chiffrée vers le réseau de Cloudflare. 
De ce fait, l'IP publique reste "fermée" à toute intrusion.

### Contournement du Proxy

Puisque le tunnel crée une connexion HTTPS standard (ou gRPC) vers Cloudflare, 
le proxy ne verra qu'un simple trafic chiffré vers Cloudflare (généralement considéré comme un service de confiance), 
et non un accès direct à OpenRouter.

### Simple

Pas de VPN à gérer, pas de clés SSH à maintenir sur le PC qui initie la requête relayée.

## Procédure d'installation sur Proxmox

La méthode la plus propre est d'installer cloudflared dans un conteneur LXC dédié sur Proxmox.

### Étape A : Création du tunnel dans le dashboard Cloudflare

Se rendre sur **dash.cloudflare.com**.

Dans le menu de gauche, aller dans Zero Trust > Networks > Tunnels.

Cliquer sur Create a tunnel.

Lui donner un nom (ex : proxmox-tunnel).

Cloudflare fournit alors une commande d'installation (ex : cloudflared service install ...). La copier.

### Étape B : Installation dans Proxmox

Dans Proxmox, créer un nouveau conteneur LXC.

Accéder à la console du conteneur.

Installer le package Cloudflare :

```Bash
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared
chmod +x /usr/local/bin/cloudflared
Exécute la commande de connexion que tu as copiée à l'étape A. Elle va authentifier le conteneur auprès de ton compte Cloudflare.
```

Le service cloudflared se lancera automatiquement et le statut passera à "Active" dans le dashboard.

### Étape C : Configuration du routage

Dans le dashboard Cloudflare, sous l'onglet Public Hostnames du tunnel :

Ajouter un sous-domaine (ex : **api.tondomaine.com**).

**Service** : indiquer l'URL locale ou le service à atteindre.

Pour un simple relais pour des requêtes Python, 
Cloudflare Tunnel peut acheminer le trafic vers un service HTTP interne créé sur le conteneur (voir ci-dessous).

## La pièce finale : Le Relais HTTP (Python)

Une fois le conteneur accessible depuis l'extérieur via le nom de domaine (grâce au tunnel), 
il est possible de faire tourner un petit script qui "reçoit" un prompt, puis le transmet à **OpenRouter**.

Dans le conteneur LXC, il faut installer **fastapi** et **httpx**, puis créer un fichier `relais.py` :

```python
from fastapi import FastAPI, Request
import httpx
import os

app = FastAPI()

@app.post("/relay")
async def relay(request: Request):
    data = await request.json()
    headers = {
        "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
        "Content-Type": "application/json"
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post("https://openrouter.ai/api/v1/chat/completions", json=data, headers=headers)
        return resp.json()
```

## workflow final depuis  :un PC derrière un proxy

Le script Python n'appelle plus `openrouter.ai`, mais https://api.mondomaine.com/relay.

Le proxy ne voit alors qu'une requête POST vers api.mondomaine.com (site HTTPS classique).

Cloudflare reçoit la requête, le tunnel la pousse vers le conteneur Proxmox.

Le fichier `relais.py` ajoute la clé API et interroge **OpenRouter**.

Le résultat fait ensuite le chemin inverse.

## relai.py

Pour plus de sécurité, il est possible de chiffrer le contenu de la requête.

Ce script reçoit le paquet chiffré, le déchiffre, ajoute le jeton API et interroge OpenRouter.

```python
from fastapi import FastAPI, Request, HTTPException
from dotenv import load_dotenv
from cryptography.fernet import Fernet
import httpx
import os

load_dotenv()
app = FastAPI()
# La clé doit être la même sur le PC derrière le proxy et sur le serveur Proxmox
key = os.getenv("ENCRYPTION_KEY").encode()
cipher = Fernet(key)

@app.post("/relay")
async def relay(request: Request):
    # 1. Lire le corps chiffré
    body = await request.body()
    # 2. Déchiffrer
    try:
        decrypted_data = cipher.decrypt(body).decode()
        prompt_data = eval(decrypted_data) # Attention: utiliser json.loads en production
    except:
        raise HTTPException(status_code=403, detail="Déchiffrement échoué")

    # 3. Appeler OpenRouter avec le token ajouté localement
    headers = {"Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}"}
    async with httpx.AsyncClient() as client:
        resp = await client.post("https://openrouter.ai/api/v1/chat/completions", 
                                 json=prompt_data, headers=headers)
        return resp.json()
```

## Génération de la clé cryptée

Script a exécuter sur le PC :

```bash
from cryptography.fernet import Fernet
key = Fernet.generate_key()
print(key.decode()) # Copie cette chaîne de caractères !
 ```

## Appel depuis le PC derrière le proxy

Le script `ask.py` ne communique plus avec OpenRouter, mais avec le serveur, en chiffrant le contenu avant l'envoi.

```python
from cryptography.fernet import Fernet
import httpx

key = b'CLE_AES_GENEREE_PAR_FERNET' # Doit correspondre à celle du serveur
cipher = Fernet(key)

payload = {
    "secret_token": "MonMotDePasse",
    "model": "google/gemini-2.0-flash-001",
    "prompt": "..."
}

def send_to_relay(payload):
    # Chiffrer la charge utile
    encrypted_payload = cipher.encrypt(str(payload).encode())
    
    # Envoyer au serveur (via Cloudflare Tunnel)
    response = httpx.post("https://api.mon_domaine.fr/relay", content=encrypted_payload)
    return response.json()
```

## Exécution de geni en passant par le relais

Le script ask.py a été modifié en call_relay après y avoir modifié les appels directs à l'IA.
Ce script doit être présent dans le dossier appelé par la chaîne ASK_SCRIPT = os.path.join(LOCAL_BIN, 'call_relay.py').

De même, pour être appelé par geni, le script glog.py doit aussi être présent dans le dossier des binaires.
Ce script a en outre été modifié pour appeler le relais et utiliser l'IA pour générer les appels à la base vectorielle.
Ce script modifié a été nommé glog_relay.py.

Le script geni a également été modifié pour y ajouter une méthode appelant l'embedding en passant par le relais.
Le script modifié se nomme geni_relay.py.

## Appeler le relais depuis Aider

Aider utilise liteLLM pour traduire le code Python dans le langage de n'importe quelle API d'IA.
Mais Aider (via LiteLLM) ne sait pas chiffrer en AES/Fernet nativement, 
et il s'attend à parler à une API qui ressemble à celle d'OpenAI. 
Si on envoie un bloc de données chiffrées à la place du JSON attendu, 
LiteLLM ou le protocole HTTP standard côté client va bloquer.

Pour contourner ce problème, on va donc se créer un petit proxy local.
Pour cela, on va créer un micro-script Python local qui va faire l'interface.

### Le nouveau workflow d'Aider

- Aider envoie une requête JSON standard à http://localhost:5000.
- le Proxy Local intercepte le JSON, y injecte le internal_token, chiffre le tout en AES (Fernet), et l'envoie au relais LXC.
- le relais LXC déchiffre, valide, et transmet à OpenRouter.

#### Installer les paquets nécessaires 

```bash
c:\laragon\bin\python\python-3.10\python.exe -m pip install fastapi uvicorn httpx cryptography
```

```python
import httpx
from fastapi import FastAPI, Request
from cryptography.fernet import Fernet
import os
import uvicorn
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()
cipher = Fernet(os.getenv("ENCRYPTION_KEY").encode())
RELAY_URL = "https://openrouter.webtrader.fr/relay"
SECRET_TOKEN = os.getenv("SECRET_TOKEN")

@app.post("/{path:path}")
async def handle_proxy(request: Request, path: str):
    # 1. Recevoir le JSON d'Aider
    payload = await request.json()
    
    # 2. Préparer l'enveloppe sécurisée
    data_to_encrypt = {
        "internal_token": SECRET_TOKEN,
        "payload": payload
    }
    
    # 3. Chiffrer
    encrypted_data = cipher.encrypt(str(data_to_encrypt).replace("'", '"').encode())
    
    # 4. Envoyer au LXC (via HTTPS standard, sans headers suspects)
    async with httpx.AsyncClient() as client:
        resp = await client.post(RELAY_URL, content=encrypted_data)
        return resp.json()

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=5000)
```

### Adaptation de l'alias **ago**

Maintenant, il faut dire à Aider de ne plus regarder vers internet, mais vers ton script local :

```bash
# On définit l'API sur le port de notre bridge local
set OPENROUTER_API_BASE=http://127.0.0.1:5000&& aider --config %AIDER_CONF% $*
```

### Pourquoi c'est la meilleure méthode ?

1. Contournement total du Proxy : pour le proxy, la requête ressemble à un simple POST HTTPS avec un corps binaire (le chiffrement). 
Comme il n'y a pas de header Authorization, il laisse passer.

2. Zéro Header ajouté : Le SECRET_TOKEN est caché à l'intérieur du bloc chiffré AES. 
Même si le proxy inspecte le corps du message (Deep Packet Inspection), il ne verra que du bruit aléatoire.

3. Sécurité maximale : On conserve le chiffrement de bout en bout mis en place pour les autres outils.

### .bat pour lancer le script local

```bat
@echo off
SETLOCAL

:: --- CONFIGURATION ---
:: Chemin vers ton environnement virtuel si nécessaire
SET VENV_PATH=C:\chemin\vers\ton\venv\Scripts\activate
:: Port local du bridge
SET LOCAL_PORT=5000
:: URL locale pour LiteLLM
SET OPENROUTER_API_BASE=http://127.0.0.1:%LOCAL_PORT%
:: Ta config Aider
SET AIDER_CONF=C:\Users\bulam\.local\bin\.aider.conf.yml

:: --- ETAPE 1 : Lancer le Local Bridge ---
:: On vérifie si le port est déjà occupé
netstat -ano | findstr :%LOCAL_PORT% > nul
if %errorlevel% == 0 (
    echo [INFO] Le pont local semble deja actif.
) else (
    echo [START] Lancement du bridge local...
    :: Lance le bridge dans une nouvelle fenêtre minimisée
    start /min "Relay_Bridge" cmd /c "call %VENV_PATH% && python local_bridge.py"
    :: Attente de 2 secondes pour laisser le serveur démarrer
    timeout /t 2 /nobreak > nul
)

:: --- ETAPE 2 : Lancer Aider ---
echo [AIDER] Initialisation de la session...
aider --config %AIDER_CONF% --message-file dernier_plan.md %*

:: --- ETAPE 3 : Nettoyage (Optionnel) ---
:: Si tu veux couper le bridge à la fermeture d'Aider, décommente la ligne suivante :
:: taskkill /FI "WINDOWTITLE eq Relay_Bridge" /F > nul

ENDLOCAL
````

Détails importants pour que cela fonctionne :
Chemin du Venv : Remplacer C:\chemin\vers\ton\venv\Scripts\activate par le chemin réel où est installé fastapi, 
uvicorn, httpx et cryptography sur ton PC local.

Emplacement du script : Placer ce `.bat` dans le même dossier que le `local_bridge.py`.

Le "Fake" API Key : Pour qu'Aider ne râle pas, 
s'assurer que le fichier .env local contient toujours OPENROUTER_API_KEY=sk-dummy-key 
(peu importe la valeur, LiteLLM a juste besoin de voir qu'une clé existe, même si c'est le pont qui gère la sécurité).

## TODO

Il reste à gérer les appels à Aider via l'alias **ago**, notamment les erreurs de modèle.
Il faut également qu'Aider passe par le relais lui aussi.

## Troubleshooting

L'interface pour créer les tunnels Cloudflare est accessible depuis https://one.dash.cloudflare.com/
Ne pas créer le tunnel depuis https://dash.cloudflare.com/

