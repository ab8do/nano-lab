# Nano Lab

**Interaction par gestes et par la voix sur un Arduino Nano avec un OLED 128×64**

[English](README.md) · [العربية](README.ar.md) · **Site :** `https://YOUR-USERNAME.github.io/nano-lab/`

## Résumé

Un Arduino Nano ne dispose que de 2 Ko de SRAM, trop peu pour traiter des images de caméra ou la parole. Ce dépôt étudie jusqu'où une telle carte peut servir de *terminal d'interaction* lorsque la perception est déléguée à un portable et que le microcontrôleur se limite à mettre à jour son état et à dessiner sur un OLED bicolore de 0,96 pouce. Trois prototypes de complexité croissante sont fournis : **(1) Dino**, un canal de commande unique (un octet par saut) ; **(2) Gesture Games**, un flux continu de 4 octets qui pilote quatre jeux d'arcade ; **(3) Robo**, un agent conversationnel dont le visage expressif est dessiné avec une mémoire bornée et dont le « cerveau » peut être un modèle cloud, une variante cloud économe en jetons ou une chaîne entièrement locale. Le code, les spécifications de protocole et un site trilingue sont inclus.

## Questions de recherche

1. Un ATmega328P (2 Ko de SRAM) peut-il faire tourner des jeux interactifs pilotés par gestes de la main, avec seulement une liaison série vers un portable ?
2. Quel est le plus petit protocole série suffisant pour chaque style d'interaction (commande isolée, état continu, conversation) ?
3. Comment dessiner un visage expressif (transitions fluides entre émotions, regard, synchronisation de la bouche) dans la mémoire du microcontrôleur ?
4. Quels compromis pratiques entre IA cloud, cloud économe et locale (coût, quotas, Internet, latence, qualité) ?

## Les trois prototypes

| Prototype | Entrée | Message série | Fichiers |
|---|---|---|---|
| Dino | main levée (MediaPipe Hands, index plus haut que le poignet de plus de 0,2 de la hauteur de l'image) | lettre `J` à 9600 bauds | `firmware/dino`, `software/dino` |
| Gesture Games | position de la paume et nombre de doigts | `255, x, y, f` à 57600 bauds | `firmware/gesture-games`, `software/gesture-games` |
| Robo | voix (micro) et visage de l'utilisateur (webcam) | `255,x,y` regard, `254,c` commandes, `253,v` volume, `252,e` énergie | `firmware/robo-face`, `software/robo` |

Les quatre jeux : Flappy Bird (poing puis main ouverte), Pong (hauteur de la main = raquette), Snake (écart de la main par rapport au centre = direction), Shooter (horizontal ; tir automatique). Valeurs détaillées dans [README.md](README.md) et sur le site.

## Câblage (tous les projets)

| Broche écran | Broche Nano |
|---|---|
| GND | GND |
| VCC | 5V |
| D0 (CLK) | D13 |
| D1 (MOSI) | D11 |
| RES | D8 |
| DC | D9 |
| CS | D10 |

Les broches du Nano doivent être **soudées**, sinon l'écran reste noir. Si l'écran ne s'allume pas, essayez la ligne SH1106 du sketch.

## Démarrage rapide

```bash
git clone https://github.com/YOUR-USERNAME/nano-lab.git
cd nano-lab
pip install -r software/dino/requirements.txt
python software/dino/dino_controller.py   # réglez d'abord PORT dans le fichier
```

Pour Robo avec Gemini, placez la clé dans la variable d'environnement `GEMINI_API_KEY` et ne la publiez jamais sur GitHub.

## État de la validation

La syntaxe des sketches a été vérifiée localement et la CI les compile pour `arduino:avr:nano`. Dino et Robo (v3 avec Gemini) ont été utilisés sur le matériel par l'auteur ; Gesture Games et les variantes économe et locale n'ont pas encore été rapportés. **Aucune mesure quantitative** (latence, précision) n'a été collectée ; un protocole est proposé dans `documentation/validation.md`.

## Vie privée

La webcam est traitée localement. Avec Gemini, l'enregistrement de votre voix est envoyé aux serveurs de Google. La variante locale n'envoie pas l'audio ; edge-tts envoie seulement le texte à prononcer.

## Licence et citation

Licence MIT. Pour citer, utilisez `CITATION.cff`. Le projet a été développé de façon itérative avec l'aide d'un modèle d'IA (Claude, Anthropic) pour la rédaction du code et de la documentation ; les choix de conception, le montage matériel et les essais sont l'œuvre de l'auteur.
