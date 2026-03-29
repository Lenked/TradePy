# Relance rapide : mode ABORDAGE / RECOVERY

Ce guide permet de relancer sans retoucher le code, juste en changeant le fichier de config.

## 1) Nettoyer l'état runtime (optionnel mais recommandé)

Si le bot est resté bloqué sur une ancienne journée/cooldown:

```bash
cp runtime/state.json runtime/state.json.bak 2>/dev/null || true
rm -f runtime/state.json
```

## 2) Démarrer en mode "ABORDAGE" (paper d'abord)

```bash
python main.py --mode paper --config config/profiles/abordage.yaml
```

Quand le comportement est validé (24h-48h), passer en live:

```bash
python main.py --mode live --config config/profiles/abordage.yaml --i-accept-live-risk
```

## 3) Basculer en mode "RECOVERY" si drawdown ou série de pertes

```bash
python main.py --mode paper --config config/profiles/recovery.yaml
```

Puis live si nécessaire:

```bash
python main.py --mode live --config config/profiles/recovery.yaml --i-accept-live-risk
```

## 4) Règle de bascule simple

- **ABORDAGE** tant que la courbe est stable et drawdown contenu.
- **RECOVERY** si drawdown journalier/perte en série devient inconfortable.

