# QRMeet — Gestion des présences par QR Code

Application Flask pour gérer les feuilles d'émargement via QR Code.

## Installation

```bash
# 1. Cloner / extraire le projet
cd qr-meeting

# 2. Créer un environnement virtuel
python3 -m venv venv
source venv/bin/activate   # Linux/Mac
venv\Scripts\activate      # Windows

# 3. Installer les dépendances
pip install -r requirements.txt

# 4. Lancer l'application
python app.py
```

Accéder à : http://localhost:5000  
Identifiants par défaut : **admin / admin123**

> ⚠️ Changez le mot de passe admin en production !

---

## Déploiement sur serveur (ex: Ubuntu + Nginx)

### 1. Variables d'environnement

```bash
export BASE_URL="https://votre-domaine.com"
export SECRET_KEY="une-cle-secrete-longue-et-aleatoire"
```

### 2. Gunicorn (serveur WSGI)

```bash
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

### 3. Configuration Nginx

```nginx
server {
    listen 80;
    server_name votre-domaine.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /static/ {
        alias /chemin/vers/qr-meeting/static/;
    }
}
```

### 4. Service systemd (optionnel)

```ini
[Unit]
Description=QRMeet Flask App
After=network.target

[Service]
User=www-data
WorkingDirectory=/chemin/vers/qr-meeting
Environment="BASE_URL=https://votre-domaine.com"
ExecStart=/chemin/vers/venv/bin/gunicorn -w 4 -b 0.0.0.0:5000 app:app
Restart=always

[Install]
WantedBy=multi-user.target
```

---

## Fonctionnalités

- ✅ Création de réunions avec titre, date, lieu, description
- ✅ Génération automatique de QR Code unique par réunion
- ✅ Formulaire mobile-friendly pour les participants
- ✅ Anti-doublons : blocage si même email + même nom dans la même réunion
- ✅ Horodatage automatique au moment du scan
- ✅ Dashboard avec statistiques
- ✅ Export CSV des participants par réunion
- ✅ Recherche globale dans les participants
- ✅ Activation / désactivation des réunions
- ✅ Authentification admin sécurisée

## Structure du projet

```
qr-meeting/
├── app.py                  # Application principale
├── requirements.txt        # Dépendances Python
├── README.md
├── static/
│   └── qrcodes/            # QR codes générés (auto-créé)
└── templates/
    ├── base.html            # Layout admin
    ├── login.html           # Page connexion
    ├── dashboard.html       # Tableau de bord
    ├── meeting_form.html    # Création réunion
    ├── meeting_detail.html  # Détail réunion + participants
    ├── participants.html    # Vue globale participants
    ├── register.html        # Formulaire public (après scan QR)
    ├── register_success.html
    ├── register_duplicate.html
    └── register_closed.html
```
# qr-meeting
