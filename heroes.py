import time


class Hero:
    def __init__(self, name, role, weapons=None):
        self.name = name
        self.role = role
        if weapons is None:
            self.weapons = [self.name.lower()+"_weapon"]
        else:
            self.weapons = weapons
        self.reset_attributes()
        
    def detect_hero(self, owcv):
        for weapon in self.weapons:
            if owcv.detect_single(weapon, threshold=0.97):
                return True
        return False
    
    def reset_attributes(self):
        return

    def detect_all(self, owcv):
        return


class Other(Hero):
    def __init__(self):
        super().__init__(name="Other", role="Other")
    
    def detect_hero(self, owcv=None):
        return


class Baptiste(Hero):
    def __init__(self):
        super().__init__(name="Baptiste", role="Support")


class Brigitte(Hero):
    def __init__(self):
        super().__init__(name="Brigitte", role="Support")


class Juno(Hero):
    def __init__(self):
        super().__init__(name="Juno", role="Support")
        self.pulsar_torpedoes_firing_lockout_duration = 0.5
        self.pulsar_torpedoes_last_start_time = 0
        self.pulsar_torpedoes_finish_lockout_duration = 0.3
        self.pulsar_torpedoes_last_finish_time = 0
    
    def reset_attributes(self):
        self.glide_boost = False
        self.pulsar_torpedoes = False
        self.pulsar_torpedoes_firing = False
    
    def detect_glide_boost(self, owcv):
        self.glide_boost = owcv.detect_single("juno_glide_boost")

    def detect_pulsar_torpedoes(self, owcv):
        current_time = time.time()
        time_since_pulsar_torpedoes_last_finished = current_time - self.pulsar_torpedoes_last_finish_time
        if time_since_pulsar_torpedoes_last_finished > self.pulsar_torpedoes_finish_lockout_duration:
            if owcv.detect_single("juno_pulsar_torpedoes"):
                if not self.pulsar_torpedoes:
                    self.pulsar_torpedoes_last_start_time = current_time
                    self.pulsar_torpedoes = True
                pulsar_torpedoes_time_elapsed = current_time - self.pulsar_torpedoes_last_start_time
                if pulsar_torpedoes_time_elapsed >= self.pulsar_torpedoes_firing_lockout_duration:
                    self.pulsar_torpedoes_firing = not owcv.detect_single("juno_pulsar_torpedoes_timer")
            elif self.pulsar_torpedoes and not owcv.detect_single("juno_pulsar_torpedoes_timer"):
                self.pulsar_torpedoes_last_finish_time = current_time
                self.pulsar_torpedoes = False
                self.pulsar_torpedoes_firing = False
    
    def detect_all(self, owcv):
        self.detect_glide_boost(owcv)
        self.detect_pulsar_torpedoes(owcv)


class Kiriko(Hero):
    def __init__(self):
        super().__init__(name="Kiriko", role="Support")


class Lucio(Hero):
    def __init__(self):
        super().__init__(name="Lucio", role="Support")
        self.crossfade_buffer_size = 6 # Overridden by config.ini
    
    def reset_attributes(self):
        self.healing_song = False
        self.speed_song = False
        self.healing_song_buffer = 0
        self.speed_song_buffer = 0
    
    def detect_song(self, owcv):
        if owcv.detect_single("lucio_heal"):
            self.healing_song = True
            self.speed_song = False
            self.healing_song_buffer = 0
            self.speed_song_buffer = 0
        elif self.healing_song:
            self.healing_song_buffer += 1
            if self.healing_song_buffer >= self.crossfade_buffer_size:
                self.healing_song = False
        
        # Can we skip this section if the previous section is True?
        if owcv.detect_single("lucio_speed"):
            self.speed_song = True
            self.healing_song = False
            self.speed_song_buffer = 0
            self.healing_song_buffer = 0
        elif self.speed_song:
            self.speed_song_buffer += 1
            if self.speed_song_buffer >= self.crossfade_buffer_size:
                self.speed_song = False
    
    def detect_all(self, owcv):
        self.detect_song(owcv)


class Mercy(Hero):
    def __init__(self):
        super().__init__(name="Mercy", role="Support", weapons=[
            "mercy_staff",
            "mercy_pistol",
            "mercy_pistol_ult",
        ])
        self.beam_disconnect_buffer_size = 8 # Overridden by config.ini

    def reset_attributes(self):
        self.heal_beam = False
        self.damage_beam = False
        self.resurrecting = False
        self.heal_beam_buffer = 0
        self.damage_beam_buffer = 0
    
    def detect_beams(self, owcv):
        if owcv.detect_single("mercy_heal_beam"):
            self.heal_beam = True
            self.damage_beam = False
            self.heal_beam_buffer = 0
            self.damage_beam_buffer = 0
        elif self.heal_beam:
            self.heal_beam_buffer += 1
            if self.heal_beam_buffer >= self.beam_disconnect_buffer_size:
                self.heal_beam = False
        
        # Can we skip this section if the previous section is True?
        if owcv.detect_single("mercy_damage_beam"):
            self.damage_beam = True
            self.heal_beam = False
            self.damage_beam_buffer = 0
            self.heal_beam_buffer = 0
        elif self.damage_beam:
            self.damage_beam_buffer += 1
            if self.damage_beam_buffer >= self.beam_disconnect_buffer_size:
                self.damage_beam = False
    
    def detect_resurrect(self, owcv):
        self.resurrecting = owcv.detect_single("mercy_resurrect_cd")


class Zenyatta(Hero):
    def __init__(self):
        super().__init__(name="Zenyatta", role="Support")
        # Orbs take up to 0.8s to switch targets at max range (w/ ~40ms RTT)
        self.orb_disconnect_buffer_size = 30 # Overridden by config.ini
    
    def reset_attributes(self):
        self.harmony_orb = False
        self.discord_orb = False
        self.harmony_orb_buffer = 0
        self.discord_orb_buffer = 0
    
    def detect_orbs(self, owcv):
        if owcv.detect_single("zenyatta_harmony"):
            self.harmony_orb = True
            self.harmony_orb_buffer = 0
        elif self.harmony_orb:
            self.harmony_orb_buffer += 1
            if self.harmony_orb_buffer >= self.orb_disconnect_buffer_size:
                self.harmony_orb = False

        if owcv.detect_single("zenyatta_discord"):
            self.discord_orb = True
            self.discord_orb_buffer = 0
        elif self.discord_orb:
            self.discord_orb_buffer += 1
            if self.discord_orb_buffer >= self.orb_disconnect_buffer_size:
                self.discord_orb = False
    
    def detect_all(self, owcv):
        self.detect_orbs(owcv)


# HEROES = [
#         "DVa", "Doomfist", "JunkerQueen", "Orisa", "Rammatra", "Reinhardt", "Roadhog", "Sigma", "Winston", "WreckingBall", "Zarya",
#         "Ashe", "Bastion", "Cassidy", "Echo", "Genji", "Hanzo", "Junkrat", "Mei", "Pharah", "Reaper", "Sojourn", "Soldier76", "Sombra", "Symmetra", "Torbjorn", "Tracer", "Widowmaker",
#         "Ana", "Baptiste", "Brigitte", "Kiriko", "Lucio", "Mercy", "Moira", "Zenyatta"
#     ]
# for hero in HEROES:
#     print(f"\nclass {hero}(Hero):\n    def __init__(self):\n        super().__init__(name=\"{hero}\")\n")
