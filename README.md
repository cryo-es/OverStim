# OverStim
[Click here for download instructions](https://github.com/cryo-es/OverStim/releases)

Controls your vibrator/vibrating toy based on what's happening in Overwatch 2, using computer vision. Won't trigger anticheat, because all it's doing is recording the screen like Discord screenshare and OBS does.

Requires [Intiface Central](https://intiface.com/central/)  if you want to use it with a toy.

Default Settings (all triggers can be disabled or have their intensities/durations changed in the config):
- **Elimination:** +30% intensity for 6 seconds
- **Assist:** +15% intensity for 3 seconds
- **Mercy:**
  - **Resurrect:** +100% intensity for 4 seconds
  - **Heal beam:** +10% intensity while active
  - **Damage boost beam:** +30% intensity while active
- **Zenyatta:**
  - **Harmony orb:** +15% intensity while active
  - **Discord orb:** +20% intensity while active

Optional Settings (all disabled by default):
- **Saved someone:** +50% intensity for 4 seconds
- **Being beamed by Mercy:** +30% intensity while active
- **Being orbed by Zenyatta:** +30% intensity while active
- **Hacked by Sombra:** Either disable all vibration, or randomize it

Known Issues:
- Some features don't work with colourblind settings enabled.
- Doesn't work at aspect ratios other than 16:9.
- High latency to the game server causes Mercy's beam to reconnect to people slower when switching beam types. This can cause temporary gaps in vibration.
- Only Windows is officially supported ([join the Discord](https://discord.gg/AVpcVhQQhu) if you want Linux support, one guy managed to get it working).
