import time

from owcv import ComputerVision
import heroes


class OverwatchStateTracker:
    def __init__(self):
        coords = {
            "elimination": [751, 779, 833, 975],
            "assist": [751, 779, 833, 975],
            "save": [751, 779, 729, 923],
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
            "lucio_heal": [668, 698, 796, 824],
            "lucio_speed": [668, 698, 1093, 1126],
            "mercy_staff": [958, 974, 1768, 1789],
            "mercy_pistol": [946, 958, 1669, 1709],
            "mercy_pistol_ult": [945, 960, 1669, 1697], # Pistol icon changes during ult
            "mercy_heal_beam": [672, 706, 807, 841],
            "mercy_damage_beam": [673, 705, 1080, 1112],
            "mercy_resurrect_cd": [920, 1000, 1570, 1655],
            "zenyatta_weapon": [966, 979, 1717, 1731],
            "zenyatta_harmony": [954, 986, 738, 762],
            "zenyatta_discord": [954, 985, 1157, 1182],
        }
        to_mask = [
        ]
        self.owcv = ComputerVision(coords, to_mask)
        self.current_time = 0
        self.supported_heroes = {
            "Baptiste": heroes.Baptiste(),
            "Brigitte": heroes.Brigitte(),
            "Kiriko": heroes.Kiriko(),
            "Lucio": heroes.Lucio(),
            "Mercy": heroes.Mercy(),
            "Zenyatta": heroes.Zenyatta()
        }
        self.hero = heroes.Other()
        self.detected_hero = "Other"
        self.detected_hero_time = 0
        self.last_hero_detection_attempt_time = 0
        self.hero_auto_detect = True
        self.in_killcam = False
        self.death_spectating = False
        self.is_dead = False
        self.notifs = []
        self.new_notifs = {}
        self.being_beamed = False
        self.being_orbed = False
        self.hacked = False

    def refresh(self, capture_frame_only=False):
        self.owcv.capture_frame()
        if capture_frame_only:
            return

        # TODO: Shouldn't check for things that aren't enabled in the config
        self.current_time = time.time()
        self.expire_notifs()
        self.new_notifs = {}

        # TODO: Find out if the player is alive (there is a period of time between death and killcam, should handle that with "you were eliminated" message and a timer)
        self.in_killcam = self.owcv.detect_single("killcam")
        if not self.in_killcam:
            self.death_spectating = self.owcv.detect_single("death_spec")
        player_is_alive = not (self.in_killcam or self.death_spectating)

        if player_is_alive:
            if self.is_dead:
                self.is_dead = False

            self.detect_new_notifs()

            self.being_beamed = self.owcv.detect_single("being_beamed")

            self.being_orbed = self.owcv.detect_single("being_orbed")

            self.hacked = self.owcv.detect_single("hacked")

            if self.hero.name == "Other":
                pass
            elif self.hero.name == "Mercy":
                self.hero.detect_beams(self.owcv)
                if self.count_notifs_of_type("save") > 0: # Could we use self.new_notifs here or is rez icon too delayed?
                    self.hero.detect_resurrect(self.owcv)
            else:
                self.hero.detect_all(self.owcv)

            if self.hero_auto_detect:
                # Check for current hero once per second.
                # If not found after 3 seconds, check for every hero each second (starting with heroes in the same role).
                # If not found after 6 seconds, switch to other.
                time_since_successful_hero_detection = self.current_time - self.detected_hero_time
                time_since_attempted_hero_detection = self.current_time - self.last_hero_detection_attempt_time
                if time_since_attempted_hero_detection >= 1:
                    if self.hero.name == "Other":
                        if time_since_attempted_hero_detection >= 2:
                            self.detect_hero() # Detect all heroes
                    else:
                        if time_since_successful_hero_detection >= 4:
                            self.detect_hero(prioritize_current_role=True) # Detect all heroes, starting with same role
                        else:
                            self.detect_hero(current_hero_only=True) # Detect just self.hero

        # If player is dead:
        else:
            if not self.is_dead:
                self.is_dead = True
                self.being_beamed = False
                self.being_orbed = False
                self.hacked = False
                self.hero.reset_attributes()

    def detect_hero(self, current_hero_only=False, prioritize_current_role=False):
        hero_detected = False
        if current_hero_only:
            if self.hero.detect_hero(self.owcv):
                self.detected_hero_time = self.current_time
                hero_detected = True
        else:
            if prioritize_current_role:
                heroes_to_detect = self.get_supported_heroes_prioritizing_current_role()
            else:
                heroes_to_detect = self.supported_heroes
            for hero in heroes_to_detect.values():
                if hero.detect_hero(self.owcv):
                    self.detected_hero = hero.name
                    self.detected_hero_time = self.current_time
                    hero_detected = True
                    break
        # If no supported hero has been detected within the last 8 seconds:
        time_since_successful_hero_detection = self.current_time - self.detected_hero_time
        if not hero_detected and self.detected_hero != "Other" and time_since_successful_hero_detection >= 6:
            self.detected_hero = "Other"
        self.last_hero_detection_attempt_time = self.current_time

    def switch_hero(self, hero_name):
        self.hero.reset_attributes()
        if hero_name == "Other":
            self.hero = heroes.Other()
        else:
            self.hero = self.supported_heroes[hero_name]

    def detect_new_notifs(self):
        # Coords are for the first row
        all_notif_coords = {
            "elimination": [751, 779, 833, 975],
            "assist": [751, 779, 833, 975],
            "save": [751, 779, 729, 923],
        }

        notifs = {}
        for row in range(0, 2):
            pixel_offset = row * 35 # Pixels between rows @ 1080p
            no_notif_detected = True
            for notif_type, notif_coords in all_notif_coords.items():
                notif_coords[0] += pixel_offset
                notif_coords[1] += pixel_offset
                if self.owcv.detect_single(notif_type, coords_override=notif_coords):
                    no_notif_detected = False
                    notifs[notif_type] = notifs.get(notif_type, 0) + 1
                    # If a notif was detected on this row, no need to check for other notifs on this row
                    break
            # If no notif was detected on this row, no need to check the next row
            if no_notif_detected:
                break
        
        for notif_type, notifs_detected in notifs.items():
            existing_notifs = self.count_notifs_of_type(notif_type)
            new_notifs = max(0, notifs_detected - existing_notifs)
            for _ in range(new_notifs):
                self.add_notif(notif_type)
            self.new_notifs[notif_type] = new_notifs
    
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

    def start_tracking(self, refresh_rate):
        self.owcv.start_capturing(refresh_rate)

    def stop_tracking(self):
        self.owcv.stop_capturing()

    def get_supported_heroes_prioritizing_current_role(self):
        current_role_heroes = {name: hero for name, hero in self.supported_heroes.items() if hero.role == self.hero.role}
        other_heroes = {name: hero for name, hero in self.supported_heroes.items() if hero.role != self.hero.role}
        sorted_heroes = {**current_role_heroes, **other_heroes}

        return sorted_heroes