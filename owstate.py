import time

from owcv import ComputerVision


class OverwatchStateTracker:
    def __init__(self):
        coords = {
            "elimination": [749, 850, 832, 976],
            "assist": [749, 850, 832, 976],
            "save": [749, 850, 727, 922],
            "killcam": [89, 107, 41, 69],
            "death_spec": [66, 86, 1416, 1574],
            "being_beamed": [763, 807, 461, 508],
            "being_orbed": [760, 800, 465, 619], # Can be pushed right by Mercy beam icon
            "hacked": [858, 882, 172, 197],
            "overtime": [37, 57, 903, 1016],
            "baptiste_weapon": [963, 974, 1722, 1747],
            "brigitte_weapon": [958, 974, 1697, 1723],
            "kiriko_weapon": [964, 969, 1682, 1719],
            "lucio_weapon": [958, 968, 1702, 1742],
            "mercy_staff": [958, 974, 1768, 1789],
            "mercy_pistol": [946, 958, 1669, 1709],
            "mercy_pistol_ult": [945, 960, 1669, 1697], # Pistol icon changes during ult
            "mercy_heal_beam": [672, 706, 807, 841],
            "mercy_damage_beam": [673, 705, 1080, 1112],
            "mercy_resurrect_cd": [920, 1000, 1570, 1655],
            "zen_weapon": [966, 979, 1717, 1731],
            "zen_harmony": [954, 986, 738, 762],
            "zen_discord": [954, 985, 1157, 1182],
        }
        to_mask = [
        ]
        self.owcv = ComputerVision(coords, to_mask)
        self.current_time = 0
        self.hero = "Other"
        self.detected_hero = "Other"
        self.detected_hero_time = 0
        self.hero_auto_detect = True
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
        self.hacked = False

        # Mercy-specific attributes
        self.mercy_heal_beam = False
        self.mercy_damage_beam = False
        self.mercy_resurrecting = False
        self.mercy_heal_beam_buffer = 0
        self.mercy_damage_beam_buffer = 0
        self.mercy_beam_disconnect_buffer_size = 8

        # Zenyatta-specific attributes
        self.zen_harmony_orb = False
        self.zen_discord_orb = False
        self.zen_harmony_orb_buffer = 0
        self.zen_discord_orb_buffer = 0
        # Orbs take up to 0.8s to switch targets at max range (w/ ~40ms RTT)
        self.zen_orb_disconnect_buffer_size = 30

    def refresh(self, capture_frame_only=False):
        self.owcv.capture_frame()
        if capture_frame_only:
            return

        # TODO: Shouldn't check for things that aren't enabled in the config
        self.current_time = time.time()
        self.expire_notifs()

        self.total_new_notifs = 0
        self.new_eliminations = 0
        self.new_assists = 0
        self.new_saves = 0

        # TODO: Find out if the player is alive (there is a period of time between death and killcam, should handle that with "you were eliminated" message and a timer)
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

            self.hacked = self.owcv.detect_single("hacked")

            if self.hero == "Mercy":
                self.detect_mercy_beams()

                if self.count_notifs_of_type("save") > 0:
                    self.mercy_resurrecting = self.owcv.detect_single("mercy_resurrect_cd")

            elif self.hero == "Zenyatta":
                self.detect_zen_orbs()

            # Detect hero swaps for 0.1 second every 3 seconds
            current_second = self.current_time - int(self.current_time / 10) * 10
            if self.hero_auto_detect and int(current_second) % 3 == 0 and current_second % 1 < 0.1:
                self.detect_hero()

        # If player is dead:
        else:
            if not self.is_dead:
                self.is_dead = True
                self.being_beamed = False
                self.being_orbed = False
                self.hacked = False
                # Add a way to remove this duplication of code (repeats in switch_hero).
                # Probably, each hero should be a class and should have a method to zero its attributes. Instances could saved as self.mercy, self.zenyatta, etc. Or just as self.current_hero.
                if self.hero == "Mercy":
                    self.mercy_heal_beam = False
                    self.mercy_damage_beam = False
                    self.mercy_resurrecting = False
                    self.mercy_heal_beam_buffer = 0
                    self.mercy_damage_beam_buffer = 0
                elif self.hero == "Zenyatta":
                    self.zen_harmony_orb = False
                    self.zen_discord_orb = False
                    self.zen_harmony_orb_buffer = 0
                    self.zen_discord_orb_buffer = 0

    def detect_hero(self):
        hero_detected = False
        heroes = {
            "zen_weapon": "Zenyatta",
            "mercy_staff": "Mercy",
            "mercy_pistol": "Mercy",
            "mercy_pistol_ult": "Mercy",
            "baptiste_weapon": "Baptiste",
            "brigitte_weapon": "Brigitte",
            "kiriko_weapon": "Kiriko",
            "lucio_weapon": "Lucio",
        }
        for hero_weapon, hero_name in heroes.items():
            if self.owcv.detect_single(hero_weapon, threshold=0.97):
                self.detected_hero = hero_name
                self.detected_hero_time = self.current_time
                hero_detected = True
                break
        # If no supported hero has been detected within the last 8 seconds:
        if not hero_detected and self.detected_hero != "Other" and self.current_time > self.detected_hero_time + 8:
            self.detected_hero = "Other"

    def switch_hero(self, hero_name):
        if self.hero == "Mercy":
            self.mercy_heal_beam = False
            self.mercy_damage_beam = False
            self.mercy_resurrecting = False
            self.mercy_heal_beam_buffer = 0
            self.mercy_damage_beam_buffer = 0
        elif self.hero == "Zenyatta":
            self.zen_harmony_orb = False
            self.zen_discord_orb = False
            self.zen_harmony_orb_buffer = 0
            self.zen_discord_orb_buffer = 0
        self.hero = hero_name

    def detect_new_notifs(self, notif_type):
        if self.total_new_notifs >= 3:
            return 0
        notifs_detected = self.owcv.detect_multiple(notif_type)
        existing_notifs = self.count_notifs_of_type(notif_type)
        new_notifs = max(0, notifs_detected - existing_notifs)
        for _ in range(new_notifs):
            self.add_notif(notif_type)
        self.total_new_notifs += new_notifs
        return new_notifs

    def count_notifs_of_type(self, notif_type):
        return sum(notif[0] == notif_type for notif in self.notifs)

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
        if self.owcv.detect_single("mercy_heal_beam"):
            self.mercy_heal_beam_buffer = 0
            self.mercy_heal_beam = True
            self.mercy_damage_beam = False
            self.mercy_damage_beam_buffer = 0
        elif self.mercy_heal_beam:
            self.mercy_heal_beam_buffer += 1
            if self.mercy_heal_beam_buffer == self.mercy_beam_disconnect_buffer_size:
                self.mercy_heal_beam = False

        if self.owcv.detect_single("mercy_damage_beam"):
            self.mercy_damage_beam_buffer = 0
            self.mercy_damage_beam = True
            self.mercy_heal_beam = False
            self.mercy_heal_beam_buffer = 0
        elif self.mercy_damage_beam:
            self.mercy_damage_beam_buffer += 1
            if self.mercy_damage_beam_buffer == self.mercy_beam_disconnect_buffer_size:
                self.mercy_damage_beam = False

    def detect_zen_orbs(self):
        if self.owcv.detect_single("zen_harmony"):
            self.zen_harmony_orb_buffer = 0
            self.zen_harmony_orb = True
        elif self.zen_harmony_orb:
            self.zen_harmony_orb_buffer += 1
            if self.zen_harmony_orb_buffer == self.zen_orb_disconnect_buffer_size:
                self.zen_harmony_orb = False

        if self.owcv.detect_single("zen_discord"):
            self.zen_discord_orb_buffer = 0
            self.zen_discord_orb = True
        elif self.zen_discord_orb:
            self.zen_discord_orb_buffer += 1
            if self.zen_discord_orb_buffer == self.zen_orb_disconnect_buffer_size:
                self.zen_discord_orb = False

    def start_tracking(self, refresh_rate):
        self.owcv.start_capturing(refresh_rate)

    def stop_tracking(self):
        self.owcv.stop_capturing()
