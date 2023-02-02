import time

from owcv import ComputerVision


class OverwatchStateTracker:
    def __init__(self, final_resolution):
        coords = {
            "elimination":[749, 850, 832, 976],
            "assist":[749, 850, 832, 976],
            "save":[749, 850, 727, 922],
            "killcam":[89, 107, 41, 69],
            "death_spec":[66, 86, 1416, 1574],
            "heal_beam":[650, 730, 790, 860],
            "damage_beam":[658, 719, 1065, 1126],
            "mercy_staff":[949, 988, 1681, 1762],
            "mercy_pistol":[947, 987, 1681, 1741],
            "resurrect_cd":[920, 1000, 1580, 1655],
            "being_beamed":[762, 807, 460, 508],
            "being_orbed":[859, 885, 170, 196],
            "overtime":[37, 57, 903, 1016],
            "hacked":[860, 884, 169, 193],
            "zen_weapon":[945, 993, 1701, 1765],
            "zen_harmony":[954, 986, 738, 762],
            "zen_discord":[954, 985, 1157, 1182],
            }
        to_mask = [
            "heal_beam",
            "damage_beam",
            ]
        self.owcv = ComputerVision(coords, to_mask, final_resolution)
        #TODO: Must implement change_hero method, to zero all hero related values of the old hero.
        self.hero = "Other"
        self.detected_hero = ""
        self.current_time = 0
        self.in_killcam = False
        self.death_spectating = False
        self.is_dead = False
        self.notifs = []
        self.total_new_notifs = 0
        self.new_eliminations = 0
        self.new_assists = 0
        self.new_saves = 0
        self.being_beamed = False
        self.being_orbed = False
        self.heal_beam = False
        self.damage_beam = False
        self.resurrecting = False
        self.heal_beam_active_confs = 0
        self.damage_beam_active_confs = 0
        self.pos_required_confs = 1
        self.neg_required_confs = 8
        self.harmony_orb = False
        self.discord_orb = False
        self.harmony_orb_buffer = 0
        self.discord_orb_buffer = 0
        # Orb takes up to 0.8s to reconnect
        self.zen_orb_neg_confs = 30

    def refresh(self, capture_frame_only=False):
        self.owcv.capture_frame()
        if capture_frame_only:
            return

        #TODO: Shouldn't check for things that aren't enabled in the config
        self.current_time = time.time()
        self.expire_notifs()

        self.total_new_notifs = 0
        self.new_eliminations = 0
        self.new_assists = 0
        self.new_saves = 0
        self.detected_hero = ""

        #TODO: Find out if the player is alive (there is a period of time between death and killcam, should handle that with "you were eliminated" message and a timer)
        self.in_killcam = self.owcv.detect_single("killcam")
        if not self.in_killcam:
            self.death_spectating = self.owcv.detect_single("death_spec")
        player_is_alive = not (self.in_killcam or self.death_spectating)

        if player_is_alive:
            if self.is_dead:
                self.is_dead = False

            self.new_eliminations = self.detect_new_notifs("elimination")

            self.new_assists = self.detect_new_notifs("assist")

            self.new_saves = self.detect_new_notifs("save")

            self.being_beamed = self.owcv.detect_single("being_beamed")

            self.being_orbed = self.owcv.detect_single("being_orbed")

            if self.hero == "Mercy":
                self.detect_mercy_beams()

                #if self.new_saves > 0: # Causes resurrect to never toggle off
                if self.count_notifs_of_type("save") > 0:
                    self.resurrecting = self.owcv.detect_single("resurrect_cd")

            elif self.hero == "Zenyatta":
                if self.owcv.detect_single("zen_harmony"):
                    self.harmony_orb_buffer = 0
                    if not self.harmony_orb:
                        self.harmony_orb = True
                else:
                    if self.harmony_orb:
                        self.harmony_orb_buffer -= 1
                        if self.harmony_orb_buffer == -self.zen_orb_neg_confs:
                            self.harmony_orb = False

                if self.owcv.detect_single("zen_discord"):
                    self.discord_orb_buffer = 0
                    if not self.discord_orb:
                        self.discord_orb = True
                else:
                    if self.discord_orb:
                        self.discord_orb_buffer -= 1
                        if self.discord_orb_buffer == -self.zen_orb_neg_confs:
                            self.discord_orb = False

            # Detect hero swaps
            if self.hero != "Zenyatta":
                if self.owcv.detect_single("zen_weapon", threshold=0.97):
                    self.detected_hero = "Zenyatta"
            if self.hero != "Mercy":
                if self.owcv.detect_single("mercy_staff", threshold=0.97) or self.owcv.detect_single("mercy_pistol", threshold=0.97):
                    self.detected_hero = "Mercy"

        else:
            if not self.is_dead:
                self.is_dead = True
                self.being_beamed = False
                self.being_orbed = False
                if self.hero == "Mercy":
                    self.heal_beam = False
                    self.damage_beam = False
                    self.resurrecting = False

    def switch_hero(self, hero_name):
        if self.hero == "Mercy":
            self.heal_beam = False
            self.damage_beam = False
            self.resurrecting = False
            self.heal_beam_active_confs = 0
            self.damage_beam_active_confs = 0
        elif self.hero == "Zenyatta":
            self.harmony_orb = False
            self.discord_orb = False
            self.harmony_orb_buffer = 0
            self.discord_orb_buffer = 0
        self.hero = hero_name

    def detect_new_notifs(self, notif_type):
        new_notifs = 0
        if self.total_new_notifs < 3:
            notifs_detected = self.owcv.detect_multiple(notif_type)
            existing_notifs = self.count_notifs_of_type(notif_type)
            if notifs_detected > existing_notifs:
                new_notifs = notifs_detected - existing_notifs
                for i in range(new_notifs):
                    self.add_notif(notif_type)
            self.total_new_notifs += new_notifs
        return new_notifs

    def count_notifs_of_type(self, notif_type):
        notif_count = 0
        for notif in self.notifs:
            if notif[0] == notif_type:
                notif_count += 1
        return notif_count

    def get_expired_items(self, array, expiry_index):
        expired_items = []
        for item in array:
            if item[expiry_index] <= self.current_time:
                expired_items.append(item)
            else:
                break
        return expired_items

    def expire_notifs(self):
        for expired_notif in self.get_expired_items(self.notifs, 1):
                self.notifs.remove(expired_notif)

    def add_notif(self, notif_type):
        if len(self.notifs) == 3:
            del self.notifs[0]
        self.notifs.append([notif_type, self.current_time + 2.705])

    def detect_mercy_beams(self):
        if self.owcv.detect_single("heal_beam"):
            if self.heal_beam_active_confs == self.pos_required_confs:
                if not self.heal_beam:
                    self.heal_beam = True
                    self.damage_beam = False
            else:
                if self.heal_beam_active_confs <= 0:
                    self.heal_beam_active_confs = 1
                else:
                    self.heal_beam_active_confs += 1
        else:
            if self.heal_beam_active_confs == (0 - self.neg_required_confs):
                if self.heal_beam:
                    self.heal_beam = False
            else:
                if self.heal_beam_active_confs >= 0:
                    self.heal_beam_active_confs = -1
                else:
                    self.heal_beam_active_confs -= 1

        if self.owcv.detect_single("damage_beam"):
            if self.damage_beam_active_confs == self.pos_required_confs:
                if not self.damage_beam:
                    self.damage_beam = True
                    self.heal_beam = False
            else:
                if self.damage_beam_active_confs <= 0:
                    self.damage_beam_active_confs = 1
                else:
                    self.damage_beam_active_confs += 1
        else:
            if self.damage_beam_active_confs == (0 - self.neg_required_confs):
                if self.damage_beam:
                    self.damage_beam = False
            else:
                if self.damage_beam_active_confs >= 0:
                    self.damage_beam_active_confs = -1
                else:
                    self.damage_beam_active_confs -= 1

    def start_tracking(self, refresh_rate):
        self.owcv.start_capturing(refresh_rate)

    def stop_tracking(self):
        self.owcv.stop_capturing()
