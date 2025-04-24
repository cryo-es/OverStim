# Note:
Many parts of the project are currently broken due to lack of maintenance. This is due to a combination of me being busy IRL and being focused on a rewrite. Another contributor has forked the project with a view to maintain and improve it in the meantime. I will link to their repo once they're ready for that. In the meantime, an alternative is Playful Plugins by Furi (PP). You can learn about PP, the OverStim fork, and the OverStim rewrite in [the Discord server](https://discord.gg/AVpcVhQQhu).

# OverStim
[Click here for download instructions](https://github.com/cryo-es/OverStim/releases)

Controls your vibrator/vibrating toy based on what's happening in Overwatch 2, using computer vision. Won't trigger anticheat, because all it's doing is recording the screen like Discord screenshare and OBS does.

Requires [Intiface Central](https://intiface.com/central/)  if you want to use it with a toy.

Default Settings (all triggers can be disabled or have their intensities/durations changed in the config):
- **Elimination:** +30% intensity for 6 seconds
- **Assist:** +15% intensity for 3 seconds
- **Lucio:**
  - **Healing song:** +15% intensity (or custom pattern) while active
  - **Speed song:** +30% intensity (or custom pattern) while active
- **Mercy:**
  - **Resurrect:** +100% intensity for 4 seconds
  - **Heal beam:** +10% intensity while active
  - **Damage boost beam:** +30% intensity while active
- **Zenyatta:**
  - **Harmony orb:** +15% intensity while active
  - **Discord orb:** +20% intensity while active
- **Hacked by Sombra:** Disable all vibration (optionally, let Sombra control the intensity with a preset pattern)

Optional Settings (all disabled by default):
- **Saved someone:** +50% intensity for 4 seconds
- **Being beamed by Mercy:** +30% intensity while active
- **Being orbed by Zenyatta:** +30% intensity while active

Known Issues:
- Doesn't work at aspect ratios other than 16:9.
- Some features don't work with colourblind settings enabled.
- Some features don't work with controller keybinds (detection of some abilities, maybe more).
- High latency to the game server causes Mercy's beam to reconnect to people slower when switching beam types. This can cause temporary gaps in vibration.
- Only Windows is officially supported (I will provide limited assistance if you want to add Linux support or create a Linux version).
