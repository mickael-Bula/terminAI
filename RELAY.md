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

## TODO

Il reste à gérer les appels à Aider via l'alias **ago**, notamment les erreurs de modèle.
Il faut également qu'Aider passe par le relais lui aussi.

## Troubleshooting

L'interface pour créer les tunnels Cloudflare est accessible depuis https://one.dash.cloudflare.com/
Ne pas créer le tunnel depuis https://dash.cloudflare.com/

