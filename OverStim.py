import configparser
import winsound
import logging
import asyncio
import json
import time
import sys
import os
import re

from buttplug import Client, WebsocketConnector, ProtocolSpec
from pynput import keyboard
import PySimpleGUI as sg
import psutil as ps

from owstate import OverwatchStateTracker


def resource_path(relative_path):
    return os.path.join(os.path.abspath("."), relative_path)


def kill_other_overstim_instances():
    current_pid = os.getpid()
    for p in ps.process_iter():
        is_instance_of_overstim = re.search("OverStim_v\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}\\.exe$", p.name())
        if is_instance_of_overstim:
            is_this_instance = (p.pid == current_pid)
            if not is_this_instance:
                p.terminate()


def clamp_value(value, max_value, min_value=0, value_name="value"):
    if value > max_value:
        value = max_value
    elif value < min_value:
        print(f"Tried to set {value_name} to {value} but it cannot be lower than {min_value}. Setting it to {min_value}.")
        value = min_value
    return value


def round_value_to_nearest_step(value, step):
    digits_to_round_to = len(str(float(step)).split(".")[1])
    return round(step * round(value / step, 0), digits_to_round_to)


def get_devices():
    return [device for device in client.devices.values() if device.name not in EXCLUDED_DEVICE_NAMES]


def update_device_count(last_device_count):
    current_device_count = len(get_devices())
    if current_device_count != last_device_count:
        window["-DEVICE_COUNT-"].update(current_device_count)
        return current_device_count


def for_canonical(f):
    return lambda k: f(emergency_stop_listener.canonical(k))


def emergency_stop():
    vibe_manager.stopped = True


class Vibe:
    def __init__(self, pattern, trigger, current_time, loop_count=None, total_duration=None):
        self.pattern_template = [{"Intensity": pair[0], "Expiry": pair[1]} for pair in pattern]
        self.pattern = self._build_pattern(current_time)
        self.trigger = trigger
        self.current_index = 0
        self.creation_time = current_time

        if total_duration:
            self.expiry = current_time + total_duration
        elif loop_count:
            self.expiry = current_time + ((self.pattern[-1]["Expiry"] - current_time) * loop_count)
        else:
            # Hopefully nobody has a session this long
            self.expiry = current_time * 2

    def _build_pattern(self, current_time):
        pattern = []
        expiry = current_time
        for pair in self.pattern_template:
            expiry += pair["Expiry"]
            pattern.append({"Intensity": pair["Intensity"], "Expiry": expiry})
        return pattern

    def get_intensity(self, current_time):
        if current_time >= self.expiry:
            return -1
        while current_time >= self.pattern[self.current_index]["Expiry"]:
            self.current_index += 1
            if self.current_index > len(self.pattern) - 1:
                self.current_index = 0
                self.pattern = self._build_pattern(current_time)
        return self.pattern[self.current_index]["Intensity"]


class PermanentVibe(Vibe):
    def __init__(self, pattern, trigger, current_time):
        super().__init__(pattern=pattern, trigger=trigger, current_time=current_time)


class TimedVibe(Vibe):
    def __init__(self, pattern, trigger, total_duration, current_time):
        super().__init__(pattern=pattern, trigger=trigger, current_time=current_time, total_duration=total_duration)


class LoopedVibe(Vibe):
    def __init__(self, pattern, trigger, loop_count, current_time):
        super().__init__(pattern=pattern, trigger=trigger, current_time=current_time, loop_count=loop_count)


class VibeManager:
    def __init__(self):
        self.stopped = True
        self.current_time = 0
        self.vibes = {}
        self.current_intensity = 0
        self.real_intensity = 0

    def _add_vibe(self, vibe):
        if not self.stopped:
            self.vibes.setdefault(vibe.trigger, []).append(vibe)

    def add_permanent_vibe(self, amount, trigger):
        # The 60 here is arbitrary, as the pattern only has one intensity
        self._add_vibe(PermanentVibe([[amount, 60]], trigger, self.current_time))

    def add_timed_vibe(self, amount, trigger, duration):
        self._add_vibe(TimedVibe([[amount, duration]], trigger, duration, self.current_time))

    def add_permanent_pattern(self, pattern, trigger):
        self._add_vibe(PermanentVibe(pattern, trigger, self.current_time))

    def add_timed_pattern(self, pattern, trigger, duration):
        self._add_vibe(TimedVibe(pattern, trigger, duration, self.current_time))

    def add_looped_pattern(self, pattern, trigger, loop_count):
        self._add_vibe(LoopedVibe(pattern, trigger, loop_count, self.current_time))

    def _remove_vibe(self, vibe):
        self.vibes[vibe.trigger].remove(vibe)
        if not self.vibes[vibe.trigger]:
            del self.vibes[vibe.trigger]

    def remove_vibe_by_trigger(self, trigger, index=0):
        # Index of 0 removes the oldest vibe, index of -1 removes the newest vibe.
        if self.vibe_exists_for_trigger(trigger):
            vibe = self._get_vibes([trigger])[index]
            self._remove_vibe(vibe)

    def remove_pattern_by_trigger(self, trigger, index=0):
        self.remove_vibe_by_trigger(trigger=trigger, index=index)

    def toggle_vibe_to_condition(self, trigger, intensity, condition):
        vibe_exists_for_trigger = self.vibe_exists_for_trigger(trigger)
        if condition and not vibe_exists_for_trigger:
            self.add_permanent_vibe(intensity, trigger)
        elif not condition and vibe_exists_for_trigger:
            self.remove_vibe_by_trigger(trigger)

    def toggle_pattern_to_condition(self, trigger, pattern, condition):
        vibe_exists_for_trigger = self.vibe_exists_for_trigger(trigger)
        if condition and not vibe_exists_for_trigger:
            self.add_permanent_pattern(pattern, trigger)
        elif not condition and vibe_exists_for_trigger:
            self.remove_vibe_by_trigger(trigger)

    def clear_vibes(self, triggers=None):
        if triggers is None:
            self.vibes.clear()
        else:
            for trigger in triggers:
                del self.vibes[trigger]
    
    def clear_vibes_matching_regex(self, regex_pattern):
        regex = re.compile(regex_pattern)
        triggers = [trigger for trigger in self.vibes.keys() if regex.match(trigger)]
        self.clear_vibes(triggers)

    async def stop_all_devices(self):
        self.stopped = True
        self.clear_vibes()
        for device in get_devices():
            await device.stop()
        self.current_intensity = 0
        self.real_intensity = 0
        print("Stopped all devices.")
        window["-CURRENT_INTENSITY-"].update("0%")

    def _get_vibes(self, triggers=None):
        if triggers is None:
            triggers = self.vibes.keys()
        list_of_vibes = []
        for trigger in triggers:
            list_of_vibes.extend(self.vibes.get(trigger, []))
        return list_of_vibes

    def vibe_exists_for_trigger(self, trigger):
        if self._get_vibes([trigger]):
            return True
        return False

    def pattern_exists_for_trigger(self, trigger):
        return self.vibe_exists_for_trigger(trigger)

    def vibe_for_trigger_created_within_seconds(self, trigger, seconds):
        return len([vibe.creation_time > self.current_time - seconds for vibe in self._get_vibes([trigger])]) > 0

    def pattern_for_trigger_created_within_seconds(self, trigger, seconds):
        return self.vibe_for_trigger_created_within_seconds(trigger, seconds)

    def count_vibes_for_trigger(self, trigger):
        return len(self._get_vibes([trigger]))

    def count_patterns_for_trigger(self, trigger):
        return self.count_vibes_for_trigger(trigger)

    def _get_total_intensity(self, triggers=None):
        total_intensity = 0
        for vibe in self._get_vibes(triggers):
            intensity = vibe.get_intensity(self.current_time)
            if intensity == -1:
                self._remove_vibe(vibe)
            else:
                total_intensity += intensity
        return total_intensity

    async def _update_intensity_for_devices(self, devices):
        for device in devices:
            try:
                # Send new intensity to every actuator within the device
                actuator_intensities = []
                for actuator in device.actuators:

                    # Set actuator intensity to the closest step supported by that actuator, and limit it to the user-defined max intensity
                    actuator_min_intensity_step = 1 / actuator.step_count
                    actuator_max_intensity = round_value_to_nearest_step(MAX_VIBE_INTENSITY, actuator_min_intensity_step)
                    while actuator_max_intensity > MAX_VIBE_INTENSITY:
                        actuator_max_intensity -= actuator_min_intensity_step
                    actuator_intensity = clamp_value(round_value_to_nearest_step(self.real_intensity, actuator_min_intensity_step), actuator_max_intensity, value_name="actuator intensity")
                    actuator_intensities.append(actuator_intensity)

                    await actuator.command(actuator_intensity)

                # Print new intensities of device actuators
                intensity_string = f"[{device.name}] Vibe 1: {actuator_intensities[0]}"
                for index in range(len(actuator_intensities) - 1):
                    intensity_string = f"{intensity_string}, Vibe {index + 2}: {actuator_intensities[index + 1]}"
                print(intensity_string)

            except Exception as device_intensity_update_error:
                print(f"Stopping {device.name} due to an error while altering its vibration.")
                print(device_intensity_update_error)
                await device.stop()

    def print_active_triggers(self):
        active_triggers = []
        for trigger, vibes in self.vibes.items():
            trigger_quantity = len(vibes)
            # Trigger quantity should never be less than 1, because any time the last vibe for a trigger is removed, that trigger is also removed.
            active_triggers.append(trigger if trigger_quantity == 1 else f"{trigger} (x{trigger_quantity})")
        if active_triggers:
            # TODO: Break into two indented lines if line length > width of debug window
            print(f"  {', '.join(active_triggers)}")

    async def update(self, current_time):
        if self.stopped:
            if self.current_intensity != 0:
                await self.stop_all_devices()
            return
        self.current_time = current_time
        latest_intensity = self._get_total_intensity()
        if SCALE_ALL_INTENSITIES_BY_MAX_INTENSITY:
            latest_intensity *= MAX_VIBE_INTENSITY
        latest_intensity = abs(round(latest_intensity, 4))
        if self.current_intensity != latest_intensity:
            self.current_intensity = latest_intensity
            latest_clamped_intensity = clamp_value(self.current_intensity, MAX_VIBE_INTENSITY, value_name="intensity")
            print(f"Updated intensity: {self.current_intensity}" + ("" if self.current_intensity == latest_clamped_intensity else f" ({latest_clamped_intensity})"))
            if self.real_intensity != latest_clamped_intensity:
                self.real_intensity = latest_clamped_intensity
                self.print_active_triggers()
                await self._update_intensity_for_devices(get_devices())

                window["-CURRENT_INTENSITY-"].update(str(int(self.current_intensity * 100)) + ("%" if self.current_intensity == self.real_intensity else f"% (max {int(MAX_VIBE_INTENSITY * 100)}%)"))
                if BEEP_ENABLED:
                    winsound.Beep(int(1000 + (self.real_intensity * 5000)), 20)


async def run_overstim():
    # Define constants
    try:
        VIBE_FOR_ELIM = config["OverStim"].getboolean("VIBE_FOR_ELIM")
        ELIM_VIBE_INTENSITY = config["OverStim"].getfloat("ELIM_VIBE_INTENSITY")
        ELIM_VIBE_DURATION = config["OverStim"].getfloat("ELIM_VIBE_DURATION")
        VIBE_FOR_ASSIST = config["OverStim"].getboolean("VIBE_FOR_ASSIST")
        ASSIST_VIBE_INTENSITY = config["OverStim"].getfloat("ASSIST_VIBE_INTENSITY")
        ASSIST_VIBE_DURATION = config["OverStim"].getfloat("ASSIST_VIBE_DURATION")
        VIBE_FOR_SAVE = config["OverStim"].getboolean("VIBE_FOR_SAVE")
        SAVE_VIBE_INTENSITY = config["OverStim"].getfloat("SAVE_VIBE_INTENSITY")
        SAVE_VIBE_DURATION = config["OverStim"].getfloat("SAVE_VIBE_DURATION")
        VIBE_FOR_BEING_BEAMED = config["OverStim"].getboolean("VIBE_FOR_BEING_BEAMED")
        VIBE_FOR_BEING_ORBED = config["OverStim"].getboolean("VIBE_FOR_BEING_ORBED")
        HACKED_EVENT = config["OverStim"].getint("HACKED_EVENT")
        HACKED_PATTERN = json.loads(config["OverStim"].get("HACKED_PATTERN"))
        BEING_BEAMED_VIBE_INTENSITY = config["OverStim"].getfloat("BEING_BEAMED_VIBE_INTENSITY")
        BEING_ORBED_VIBE_INTENSITY = config["OverStim"].getfloat("BEING_ORBED_VIBE_INTENSITY")

        # Juno-specific constants
        JUNO_VIBE_FOR_GLIDE_BOOST = config["OverStim"].getboolean("JUNO_VIBE_FOR_GLIDE_BOOST")
        JUNO_GLIDE_BOOST_PATTERN = json.loads(config["OverStim"].get("JUNO_GLIDE_BOOST_PATTERN"))
        JUNO_VIBE_FOR_PULSAR_TORPEDOES = config["OverStim"].getboolean("JUNO_VIBE_FOR_PULSAR_TORPEDOES")
        JUNO_PULSAR_TORPEDOES_PATTERN = json.loads(config["OverStim"].get("JUNO_PULSAR_TORPEDOES_PATTERN"))
        JUNO_PULSAR_TORPEDOES_FIRING_INTENSITY = config["OverStim"].getfloat("JUNO_PULSAR_TORPEDOES_FIRING_INTENSITY")

        # Lucio-specific constants
        LUCIO_VIBE_FOR_HEALING_SONG = config["OverStim"].getboolean("LUCIO_VIBE_FOR_HEALING_SONG")
        LUCIO_HEALING_SONG_PATTERN = json.loads(config["OverStim"].get("LUCIO_HEALING_SONG_PATTERN"))
        LUCIO_VIBE_FOR_SPEED_SONG = config["OverStim"].getboolean("LUCIO_VIBE_FOR_SPEED_SONG")
        LUCIO_SPEED_SONG_PATTERN = json.loads(config["OverStim"].get("LUCIO_SPEED_SONG_PATTERN"))

        # Mercy-specific constants
        MERCY_VIBE_FOR_RESURRECT = config["OverStim"].getboolean("MERCY_VIBE_FOR_RESURRECT")
        MERCY_RESURRECT_VIBE_INTENSITY = config["OverStim"].getfloat("MERCY_RESURRECT_VIBE_INTENSITY")
        MERCY_RESURRECT_VIBE_DURATION = config["OverStim"].getfloat("MERCY_RESURRECT_VIBE_DURATION")
        MERCY_VIBE_FOR_HEAL_BEAM = config["OverStim"].getboolean("MERCY_VIBE_FOR_HEAL_BEAM")
        MERCY_HEAL_BEAM_VIBE_INTENSITY = config["OverStim"].getfloat("MERCY_HEAL_BEAM_VIBE_INTENSITY")
        MERCY_VIBE_FOR_DAMAGE_BEAM = config["OverStim"].getboolean("MERCY_VIBE_FOR_DAMAGE_BEAM")
        MERCY_DAMAGE_BEAM_VIBE_INTENSITY = config["OverStim"].getfloat("MERCY_DAMAGE_BEAM_VIBE_INTENSITY")

        # Zen-specific constants
        ZEN_VIBE_FOR_HARMONY_ORB = config["OverStim"].getboolean("ZEN_VIBE_FOR_HARMONY_ORB")
        ZEN_HARMONY_ORB_VIBE_INTENSITY = config["OverStim"].getfloat("ZEN_HARMONY_ORB_VIBE_INTENSITY")
        ZEN_VIBE_FOR_DISCORD_ORB = config["OverStim"].getboolean("ZEN_VIBE_FOR_DISCORD_ORB")
        ZEN_DISCORD_ORB_VIBE_INTENSITY = config["OverStim"].getfloat("ZEN_DISCORD_ORB_VIBE_INTENSITY")

        # Other constants
        MAX_REFRESH_RATE = config["OverStim"].getint("MAX_REFRESH_RATE")
        DEAD_REFRESH_RATE = config["OverStim"].getfloat("DEAD_REFRESH_RATE")
        LUCIO_CROSSFADE_BUFFER = config["OverStim"].getint("LUCIO_CROSSFADE_BUFFER")
        MERCY_BEAM_DISCONNECT_BUFFER = config["OverStim"].getint("MERCY_BEAM_DISCONNECT_BUFFER")
        ZEN_ORB_DISCONNECT_BUFFER = config["OverStim"].getint("ZEN_ORB_DISCONNECT_BUFFER")
    except Exception as config_error:
        config_fault[0] = True
        config_fault[1] = config_error

    # Initialize variables
    if not config_fault[0] and window["-PROGRAM_STATUS-"].get() != "INTIFACE ERROR":
        player = OverwatchStateTracker()
        player.supported_heroes["Lucio"].crossfade_buffer_size = LUCIO_CROSSFADE_BUFFER
        player.supported_heroes["Mercy"].beam_disconnect_buffer_size = MERCY_BEAM_DISCONNECT_BUFFER
        player.supported_heroes["Zenyatta"].orb_disconnect_buffer_size = ZEN_ORB_DISCONNECT_BUFFER
    last_refresh = 0
    device_count = 0

    while True:
        # Gives main time to respond to pings from Intiface
        await asyncio.sleep(0)

        if config_fault[0]:
            window["Start"].update(disabled=True)
            window["-PROGRAM_STATUS-"].update("CONFIG ERROR")
            print(f"Error reading config: {config_fault[1]}")
            event, values = window.read()
            if event == sg.WIN_CLOSED or event == "Quit":
                window.close()
                print("Window closed.")
                break

        if USING_INTIFACE and not client.connected:
            if window["-PROGRAM_STATUS-"].get() != "INTIFACE ERROR":
                window["Start"].update(disabled=True)
                window["-PROGRAM_STATUS-"].update("INTIFACE ERROR")
                print("Lost connection to Intiface. Make sure Intiface Central is started and then restart OverStim.")
            event, values = window.read()
            if event == sg.WIN_CLOSED or event == "Quit":
                window.close()
                print("Window closed.")
                break

        device_count = update_device_count(device_count)

        event, values = window.read(timeout=10)
        if event == sg.WIN_CLOSED or event == "Quit":
            window.close()
            print("Window closed.")
            break

        elif event == "-HERO_SELECTOR-":
            hero_selected = values["-HERO_SELECTOR-"]
            player.switch_hero(hero_selected)
            print(f"Hero switched to {hero_selected}.")

        elif event == "-HERO_AUTO_DETECT-":
            checkbox_state = values["-HERO_AUTO_DETECT-"]
            player.hero_auto_detect = checkbox_state
            window["-HERO_SELECTOR-"].update(disabled=checkbox_state)

        elif event == "Start":
            window["Stop"].update(disabled=False)
            window["Start"].update(disabled=True)
            window["-PROGRAM_STATUS-"].update("RUNNING")
            print("Running...")
            vibe_manager.stopped = False

            player.start_tracking(MAX_REFRESH_RATE)

            counter = 0
            start_time = time.time()

            while True:
                # Gives main time to respond to pings from Intiface
                await asyncio.sleep(0)

                if USING_INTIFACE and not client.connected:
                    break  # TODO: Is this all that needs to be done?

                counter += 1
                device_count = update_device_count(device_count)
                current_time = time.time()
                await vibe_manager.update(current_time)

                event, values = window.read(timeout=1)
                if vibe_manager.stopped:
                    print("Emergency stop detected.")
                    event = "Stop"
                if event == sg.WIN_CLOSED or event == "Quit":
                    window.close()
                    break
                elif event == "Stop":
                    await vibe_manager.stop_all_devices()
                    window["-PROGRAM_STATUS-"].update("STOPPING")
                    window["Stop"].update(disabled=True)
                    window["Quit"].update(disabled=True)
                    print("Stopped.")
                    window.refresh()
                    break
                elif event == "-HERO_SELECTOR-":
                    hero_selected = values["-HERO_SELECTOR-"]
                    player.switch_hero(hero_selected)
                    print(f"Hero switched to {hero_selected}.")
                elif event == "-HERO_AUTO_DETECT-":
                    checkbox_state = values["-HERO_AUTO_DETECT-"]
                    player.hero_auto_detect = checkbox_state
                    window["-HERO_SELECTOR-"].update(disabled=checkbox_state)

                if (not player.is_dead) or (player.is_dead and current_time >= last_refresh + (1 / float(DEAD_REFRESH_RATE))):
                    last_refresh = current_time
                    player.refresh()

                    vibe_exists_for_being_hacked = vibe_manager.vibe_exists_for_trigger("hacked")
                    if HACKED_EVENT != 0:
                        if player.hacked and not vibe_exists_for_being_hacked:
                            if HACKED_EVENT == 1:
                                vibe_manager.clear_vibes()
                                vibe_manager.add_permanent_vibe(0, "hacked")
                            elif HACKED_EVENT == 2:
                                vibe_manager.clear_vibes()
                                vibe_manager.add_permanent_pattern(HACKED_PATTERN, "hacked")
                        elif not player.hacked and vibe_exists_for_being_hacked:
                            vibe_manager.remove_pattern_by_trigger("hacked")

                    if not vibe_exists_for_being_hacked:
                        if VIBE_FOR_ELIM:
                            new_elims = player.new_notifs.get("elimination", 0)
                            if new_elims > 0:
                                vibe_manager.add_timed_vibe(new_elims * ELIM_VIBE_INTENSITY, "elimination", ELIM_VIBE_DURATION)

                        if VIBE_FOR_ASSIST:
                            new_assists = player.new_notifs.get("assist", 0)
                            if new_assists > 0:
                                vibe_manager.add_timed_vibe(new_assists * ASSIST_VIBE_INTENSITY, "assist", ASSIST_VIBE_DURATION)

                        if VIBE_FOR_SAVE:
                            new_saves = player.new_notifs.get("save", 0)
                            if new_saves > 0 and (player.hero.name != "Mercy" or (player.hero.name == "Mercy" and not player.hero.resurrecting)):
                                vibe_manager.add_timed_vibe(new_saves * SAVE_VIBE_INTENSITY, "save", SAVE_VIBE_DURATION)

                        if VIBE_FOR_BEING_BEAMED:
                            vibe_manager.toggle_vibe_to_condition("being beamed", BEING_BEAMED_VIBE_INTENSITY, player.being_beamed)

                        if VIBE_FOR_BEING_ORBED:
                            vibe_manager.toggle_vibe_to_condition("being orbed", BEING_ORBED_VIBE_INTENSITY, player.being_orbed)

                        if player.hero.name == "Other":
                            pass

                        elif player.hero.name == "Juno":

                            if JUNO_VIBE_FOR_GLIDE_BOOST:
                            boost_time = 4
                            if JUNO_VIBE_FOR_GLIDE_BOOST:
                                if player.hero.glide_boost == True and vibe_manager.vibe_for_trigger_created_within_seconds("juno glide boost", 1) == False:       
                                    vibe_manager.add_timed_pattern(JUNO_GLIDE_BOOST_PATTERN,"juno glide boost",boost_time)
                            
                            if JUNO_VIBE_FOR_PULSAR_TORPEDOES:
                                vibe_manager.toggle_pattern_to_condition("juno pulsar torpedoes", JUNO_PULSAR_TORPEDOES_PATTERN, player.hero.pulsar_torpedoes and not player.hero.pulsar_torpedoes_firing)
                                vibe_manager.toggle_vibe_to_condition("juno pulsar torpedoes firing", JUNO_PULSAR_TORPEDOES_FIRING_INTENSITY, player.hero.pulsar_torpedoes_firing)
                        
                        elif player.hero.name == "Lucio":

                            if LUCIO_VIBE_FOR_HEALING_SONG:
                                vibe_manager.toggle_pattern_to_condition("lucio healing song", LUCIO_HEALING_SONG_PATTERN, player.hero.healing_song)

                            if LUCIO_VIBE_FOR_SPEED_SONG:
                                vibe_manager.toggle_pattern_to_condition("lucio speed song", LUCIO_SPEED_SONG_PATTERN, player.hero.speed_song)

                        elif player.hero.name == "Mercy":

                            if MERCY_VIBE_FOR_RESURRECT:
                                if player.hero.resurrecting and not vibe_manager.vibe_for_trigger_created_within_seconds("mercy resurrect", 3):
                                    vibe_manager.add_timed_vibe(MERCY_RESURRECT_VIBE_INTENSITY, "mercy resurrect", MERCY_RESURRECT_VIBE_DURATION)

                            if MERCY_VIBE_FOR_HEAL_BEAM:
                                vibe_manager.toggle_vibe_to_condition("mercy heal beam", MERCY_HEAL_BEAM_VIBE_INTENSITY, player.hero.heal_beam)

                            if MERCY_VIBE_FOR_DAMAGE_BEAM:
                                vibe_manager.toggle_vibe_to_condition("mercy damage beam", MERCY_DAMAGE_BEAM_VIBE_INTENSITY, player.hero.damage_beam)
                        
                        elif player.hero.name == "Zenyatta":

                            if ZEN_VIBE_FOR_HARMONY_ORB:
                                vibe_manager.toggle_vibe_to_condition("zenyatta harmony orb", ZEN_HARMONY_ORB_VIBE_INTENSITY, player.hero.harmony_orb)

                            if ZEN_VIBE_FOR_DISCORD_ORB:
                                vibe_manager.toggle_vibe_to_condition("zenyatta discord orb", ZEN_DISCORD_ORB_VIBE_INTENSITY, player.hero.discord_orb)

                    if player.hero_auto_detect and player.detected_hero != player.hero.name:
                        print(f"Hero switch detected: {player.detected_hero}")
                        window["-HERO_SELECTOR-"].update(player.detected_hero)
                        vibe_manager.clear_vibes_matching_regex(f"^{player.hero.name.lower()}")
                        player.switch_hero(player.detected_hero)

            if event == sg.WIN_CLOSED or event == "Quit":
                print("Window closed.")
                break

            duration = time.time() - start_time
            print(f"Loops: {counter} | Loops per second: {round(counter / duration, 2)} | Avg. time: {round(1000 * (duration / counter), 2)}ms")
            window.refresh()

            player.stop_tracking()

            window["-PROGRAM_STATUS-"].update("READY")
            window["Quit"].update(disabled=False)
            window["Start"].update(disabled=False)


async def main():
    # Define global variables
    global window

    # Define constants
    OUTPUT_WINDOW_ENABLED = True
    HEROES = ["Other", "Baptiste", "Brigitte", "Kiriko", "Lucio", "Mercy", "Zenyatta","Juno"]
    # HEROES = [
    #         "DVa", "Doomfist", "JunkerQueen", "Orisa", "Rammatra", "Reinhardt", "Roadhog", "Sigma", "Winston", "WreckingBall", "Zarya",
    #         "Ashe", "Bastion", "Cassidy", "Echo", "Genji", "Hanzo", "Junkrat", "Mei", "Pharah", "Reaper", "Sojourn", "Soldier76", "Sombra", "Symmetra", "Torbjorn", "Tracer", "Widowmaker",
    #         "Ana", "Baptiste", "Brigitte", "Kiriko", "Lucio", "Mercy", "Moira", "Zenyatta"
    # ]
    try:
        OUTPUT_WINDOW_ENABLED = config["OverStim"].getboolean("OUTPUT_WINDOW_ENABLED")
        CONTINUOUS_SCANNING = config["OverStim"].getboolean("CONTINUOUS_SCANNING")
        WEBSOCKET_ADDRESS = config["OverStim"]["WEBSOCKET_ADDRESS"]
        WEBSOCKET_PORT = config["OverStim"]["WEBSOCKET_PORT"]
    except Exception as config_error:
        config_fault[0] = True
        config_fault[1] = config_error

    # Initialize variables
    scanning = False

    # Set up GUI
    layout = [
        [
            sg.Text("Playing hero:"),
            sg.Combo(HEROES, readonly=True, disabled=True, enable_events=True, key="-HERO_SELECTOR-"),
            sg.Checkbox("Auto-detect", default=True, enable_events=True, key="-HERO_AUTO_DETECT-"),
        ],
        [
            sg.Text("Devices connected:"),
            sg.Text("0", size=(4, 1), key="-DEVICE_COUNT-"),
        ],
        [
            sg.Text("Current intensity:"),
            sg.Text("0%", size=(17, 1), key="-CURRENT_INTENSITY-"),
        ],
        [
            sg.Text("Program status:"),
            sg.Text("READY", size=(15, 1), key="-PROGRAM_STATUS-"),
        ],
        [
            sg.Button("Start"),
            sg.Button("Stop", disabled=True),
            sg.Button("Quit"),
        ],
    ]
    if OUTPUT_WINDOW_ENABLED:
        layout.insert(0, [sg.Multiline(size=(60, 15), disabled=True, reroute_stdout=True, autoscroll=True)])
    window = sg.Window("OverStim", layout, finalize=True)
    window["-HERO_SELECTOR-"].update("Other")
    print("Ensure you read READ_BEFORE_USING.txt before using this program.\n-")

    if not config_fault[0]:
        emergency_stop_listener.start()
        # Connect to Intiface
        if USING_INTIFACE:
            connector = WebsocketConnector(f"{WEBSOCKET_ADDRESS}:{WEBSOCKET_PORT}", logger=client.logger)
            try:
                await client.connect(connector)
                print("Connected to Intiface")
            # except DisconnectedError:
            #    window["-PROGRAM_STATUS-"].update("RECONNECTING")
            #    await client.reconnect()
            except Exception as ex:
                print(ex)
                print("Make sure you've started the Intiface server, then restart OverStim.")
                window["-PROGRAM_STATUS-"].update("INTIFACE ERROR")
                window["Start"].update(disabled=True)

            try:
                if client.connected:
                    await client.start_scanning()
                    scanning = True
                    if not CONTINUOUS_SCANNING:
                        await asyncio.sleep(0.2)
                        await client.stop_scanning()
                        scanning = False
                    print("Started scanning")
            except Exception as ex:
                print(f"Could not initiate scanning: {ex}")
                window["Start"].update(disabled=True)

    # Initiate OverStim
    task = asyncio.create_task(run_overstim())
    try:
        await task
    except Exception as ex:
        await vibe_manager.stop_all_devices()
        window["-PROGRAM_STATUS-"].update("CRITICAL ERROR")
        print(f"CRITICAL ERROR OCCURRED\nError caught: {ex}")
        if BEEP_ENABLED:
            winsound.Beep(1000, 500)
        event, values = window.read()
        if event == sg.WIN_CLOSED or event == "Quit":
            window["Stop"].update(disabled=True)
            window["Quit"].update(disabled=True)
            window.close()

    try:
        emergency_stop_listener.stop()
    except Exception:
        pass

    # Close program
    await vibe_manager.stop_all_devices()
    if not config_fault[0]:
        if USING_INTIFACE and client.connected:
            if scanning:
                await client.stop_scanning()
            await client.disconnect()
            print("Disconnected.")
    window.close()
    print("Quitting.")


# Start

# Only allow one instance of OverStim to be running
kill_other_overstim_instances()

# Import config
config = configparser.ConfigParser()
config.read(resource_path('config.ini'))
config_fault = [False, ""]

# Define global constants
try:
    BEEP_ENABLED = config["OverStim"].getboolean("BEEP_ENABLED")
    USING_INTIFACE = config["OverStim"].getboolean("USING_INTIFACE")
    MAX_VIBE_INTENSITY = clamp_value(config["OverStim"].getfloat("MAX_VIBE_INTENSITY"), 1, value_name="MAX_VIBE_INTENSITY")
    SCALE_ALL_INTENSITIES_BY_MAX_INTENSITY = config["OverStim"].getboolean("SCALE_ALL_INTENSITIES_BY_MAX_INTENSITY")
    EXCLUDED_DEVICE_NAMES = json.loads(config["OverStim"].get("EXCLUDED_DEVICE_NAMES"))
    EMERGENCY_STOP_KEY_COMBO = keyboard.HotKey.parse(config["OverStim"]["EMERGENCY_STOP_KEY_COMBO"])
except Exception as err:
    config_fault[0] = True
    config_fault[1] = err

# Define global variables
window = sg.Window("OverStim")
client = Client("OverStim", ProtocolSpec.v3)
vibe_manager = VibeManager()

if not config_fault[0]:
    hotkey = keyboard.HotKey(EMERGENCY_STOP_KEY_COMBO, emergency_stop)
    emergency_stop_listener = keyboard.Listener(on_press=for_canonical(hotkey.press), on_release=for_canonical(hotkey.release))

sg.theme("DarkAmber")
logging.basicConfig(stream=sys.stdout, level=logging.INFO)
asyncio.run(main(), debug=False)
