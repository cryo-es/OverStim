import configparser
import winsound
import logging
import asyncio
import time
import sys
import os
import re
import random

from buttplug import Client, WebsocketConnector, ProtocolSpec
import PySimpleGUI as sg
import psutil as ps

from owstate import OverwatchStateTracker


def resource_path(relative_path):
    return os.path.join(os.path.abspath("."), relative_path)

def kill_other_overstim_instances():
    current_pid = os.getpid()
    for p in ps.process_iter():
        is_instance_of_overstim = re.search("OverStim_v\d{1,3}\.\d{1,3}\.\d{1,3}\.exe$", p.name())
        if is_instance_of_overstim:
            is_this_instance = (p.pid == current_pid)
            if not is_this_instance:
                p.terminate()

def update_device_count(last_device_count):
    current_device_count = len(client.devices)
    if current_device_count != last_device_count:
        window["-DEVICE_COUNT-"].update(current_device_count)
        return current_device_count

async def stop_all_devices():
    for key in timed_vibes:
        timed_vibes[key].clear()
    current_intensity = 0
    for device_id in client.devices:
        try:
            device = client.devices[device_id]
            await device.stop()
        except Exception as err:
            print("A device experienced an error while being stopped.")
            print(err)
    print("Stopped all devices.")
    try:
        window["-CURRENT_INTENSITY-"].update(f"{int(current_intensity*100)}%")
    except Exception as err:
        print(f"Experienced an error while updating the window:\n{err}")

def get_expired_items(array, expiry_index):
    current_time = time.time()
    expired_items = []
    for item in array:
        if item[expiry_index] <= current_time:
            expired_items.append(item)
    return expired_items

def limit_value(value, max_value, min_value=0, value_name="value"):
    if value > max_value:
        value = max_value
    elif value < min_value:
        print(f"Tried to set {value_name} to {value} but it cannot be lower than {min_value}. Setting it to {min_value}.")
        value = min_value
    return value

def round_value_to_nearest_step(value, step):
    digits_to_round_to = len(str(float(step)).split(".")[1])
    return round(step * round(value / step, 0), digits_to_round_to)

async def alter_intensity(amount, event_type):
    global current_intensity

    # Alter the intensity
    if SCALE_ALL_INTENSITIES_BY_MAX_INTENSITY:
        amount = amount * MAX_VIBE_INTENSITY
    current_intensity = abs(round(current_intensity + amount, 4))
    real_intensity = limit_value(current_intensity, MAX_VIBE_INTENSITY, value_name="intensity")
    print(f"Updated intensity: {current_intensity}" + ("" if current_intensity == real_intensity else f" ({real_intensity})") + f" | {event_type}")

    # Send new intensity to all devices
    for device_id in client.devices:
        device = client.devices[device_id]
        try:
            if device.name != "XBox (XInput) Compatible Gamepad":
                # Send new intensity to every actuator within the device
                actuator_intensities = []
                for actuator in device.actuators:

                    # Set actuator intensity to the closest step supported by that actuator, and limit it to the user-defined max intensity
                    actuator_min_intensity_step = 1 / actuator.step_count
                    actuator_max_intensity = round_value_to_nearest_step(MAX_VIBE_INTENSITY, actuator_min_intensity_step)
                    if actuator_max_intensity > MAX_VIBE_INTENSITY:
                        actuator_max_intensity -= actuator_min_intensity_step
                    actuator_intensity = limit_value(round_value_to_nearest_step(current_intensity, actuator_min_intensity_step), actuator_max_intensity, value_name="actuator intensity")
                    actuator_intensities.append(actuator_intensity)
                    await device.actuators[0].command(actuator_intensity)
                
                # Print new intensities of device actuators
                intensity_string = f"[{device.name}] Vibe 1: {actuator_intensities[0]}"
                for index in range(len(actuator_intensities) - 1):
                    intensity_string = f"{intensity_string}, Vibe {index+2}: {actuator_intensities[index + 1]}"
                print(intensity_string)

        except Exception as err:
            print(f"Stopping {device.name} due to an error when altering its vibration.")
            print(err)
            await device.stop()

    # Update the GUI with new intensity, and beep if enabled.
    window["-CURRENT_INTENSITY-"].update(str(int(current_intensity*100)) + ("%" if current_intensity == real_intensity else f"% (max {int(MAX_VIBE_INTENSITY*100)}%)"))
    if BEEP_ENABLED:
        winsound.Beep(int(1000 + (real_intensity*5000)), 20)

async def alter_intensity_for_duration(event_type, amount, duration):
    timed_vibes[event_type].append([time.time() + duration, amount])
    await alter_intensity(amount, event_type)

async def update_intensity():
    for event_type in timed_vibes:
        if event_type != "hacked":
            for expired_vibe in get_expired_items(timed_vibes[event_type], 0):
                timed_vibes[event_type].remove(expired_vibe)
                await alter_intensity(-expired_vibe[1], f"{event_type} expired")
        else:
            # Handles intensity randomization, len() will return 0 unless randomization is enabled and player is hacked
            if len(timed_vibes[event_type]) != 0:
                randomization_settings = timed_vibes[event_type][0]
                amount = randomization_settings["Amount"]
                frequency = randomization_settings["Frequency"]
                last_change = randomization_settings["Last Change"]
                current_time = time.time()
                if current_time >= last_change + frequency:
                    if current_intensity + amount > 1:
                        if random.choice([True, False]):
                            await alter_intensity(-amount, "hacked")
                    elif current_intensity - amount < 0:
                        await alter_intensity(amount, "hacked")
                    else:
                        await alter_intensity(random.choice([amount, -amount]), "hacked")
                last_change = current_time

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
        BEING_BEAMED_VIBE_INTENSITY =config["OverStim"].getfloat("BEING_BEAMED_VIBE_INTENSITY")
        BEING_ORBED_VIBE_INTENSITY =config["OverStim"].getfloat("BEING_ORBED_VIBE_INTENSITY")
        VIBE_FOR_RESURRECT = config["OverStim"].getboolean("VIBE_FOR_RESURRECT")
        RESURRECT_VIBE_INTENSITY = config["OverStim"].getfloat("RESURRECT_VIBE_INTENSITY")
        RESURRECT_VIBE_DURATION = config["OverStim"].getfloat("RESURRECT_VIBE_DURATION")
        VIBE_FOR_MERCY_BEAM = config["OverStim"].getboolean("VIBE_FOR_MERCY_BEAM")
        HEAL_BEAM_VIBE_INTENSITY = config["OverStim"].getfloat("HEAL_BEAM_VIBE_INTENSITY")
        DAMAGE_BEAM_VIBE_INTENSITY = config["OverStim"].getfloat("DAMAGE_BEAM_VIBE_INTENSITY")
        VIBE_FOR_HARMONY_ORB = config["OverStim"].getboolean("VIBE_FOR_HARMONY_ORB")
        HARMONY_ORB_VIBE_INTENSITY = config["OverStim"].getfloat("HARMONY_ORB_VIBE_INTENSITY")
        VIBE_FOR_DISCORD_ORB = config["OverStim"].getboolean("VIBE_FOR_DISCORD_ORB")
        DISCORD_ORB_VIBE_INTENSITY = config["OverStim"].getfloat("DISCORD_ORB_VIBE_INTENSITY")
        MAX_REFRESH_RATE = config["OverStim"].getint("MAX_REFRESH_RATE")
        DEAD_REFRESH_RATE = config["OverStim"].getfloat("DEAD_REFRESH_RATE")
        MERCY_BEAM_DISCONNECT_BUFFER = config["OverStim"].getint("MERCY_BEAM_DISCONNECT_BUFFER")
        ZEN_ORB_DISCONNECT_BUFFER = config["OverStim"].getint("ZEN_ORB_DISCONNECT_BUFFER")
    except Exception as err:
        config_fault[0] = True
        config_fault[1] = err

    # Initialize variables
    if not config_fault[0]:
        player = OverwatchStateTracker()
        player.mercy_beam_disconnect_buffer_size = MERCY_BEAM_DISCONNECT_BUFFER
        player.zen_orb_disconnect_buffer_size = ZEN_ORB_DISCONNECT_BUFFER
    being_beamed_vibe_active = False
    being_orbed_vibe_active = False
    hacked_effect_active = False
    heal_beam_vibe_active = False
    damage_beam_vibe_active = False
    harmony_orb_vibe_active = False
    discord_orb_vibe_active = False
    last_refresh = 0
    device_count = 0

    while True:
        # Gives main time to respond to pings from Intiface
        await asyncio.sleep(0)

        device_count = update_device_count(device_count)

        if USING_INTIFACE and not client.connected:
            window["-PROGRAM_STATUS-"].update("INTIFACE ERROR")
            window["Start"].update(disabled=True)
            print("Lost connection to Intiface. Make sure Intiface Central is started and then restart OverStim.")

            event, values = window.read()
            if event == sg.WIN_CLOSED or event == "Quit":
                window.close()
                print("Window closed.")
                break

        if config_fault[0]:
            window["Stop"].update(disabled=True)
            window["Start"].update(disabled=True)
            print(f"Error reading config: {config_fault[1]}")
            window["-PROGRAM_STATUS-"].update("CONFIG ERROR")

            event, values = window.read()
            if event == sg.WIN_CLOSED or event == "Quit":
                window.close()
                print("Window closed.")
                break

        event, values = window.read(timeout=500)
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

            player.start_tracking(MAX_REFRESH_RATE)
            
            counter = 0
            start_time = time.time()

            while True:
                # Gives main time to respond to pings from Intiface
                await asyncio.sleep(0)

                await update_intensity()
                device_count = update_device_count(device_count)
                if USING_INTIFACE and not client.connected:
                    break
                current_time = time.time()

                counter += 1
                if player.is_dead:
                    if current_time >= last_refresh + (1/float(DEAD_REFRESH_RATE)):
                        last_refresh = current_time
                        player.refresh()
                else:
                    last_refresh = current_time
                    player.refresh()

                    if not hacked_effect_active:
                        if VIBE_FOR_ELIM:
                            if player.new_eliminations > 0:
                                await alter_intensity_for_duration("elim", player.new_eliminations * ELIM_VIBE_INTENSITY, ELIM_VIBE_DURATION)

                        if VIBE_FOR_ASSIST:
                            if player.new_assists > 0:
                                await alter_intensity_for_duration("assist", player.new_assists * ASSIST_VIBE_INTENSITY, ASSIST_VIBE_DURATION)
                        
                        if VIBE_FOR_SAVE:
                            if player.new_saves > 0:
                                if not player.resurrecting:
                                    await alter_intensity_for_duration("save", player.new_saves * SAVE_VIBE_INTENSITY, SAVE_VIBE_DURATION)

                        if VIBE_FOR_BEING_BEAMED:
                            if being_beamed_vibe_active:
                                if not player.being_beamed:
                                    await alter_intensity(-BEING_BEAMED_VIBE_INTENSITY, "stopped being beamed")
                                    being_beamed_vibe_active = False
                            else:
                                if player.being_beamed:
                                    await alter_intensity(BEING_BEAMED_VIBE_INTENSITY, "being beamed")
                                    being_beamed_vibe_active = True

                        if VIBE_FOR_BEING_ORBED:
                            if being_orbed_vibe_active:
                                if not player.being_orbed:
                                    await alter_intensity(-BEING_ORBED_VIBE_INTENSITY, "stopped being orbed")
                                    being_orbed_vibe_active = False
                            else:
                                if player.being_orbed:
                                    await alter_intensity(BEING_ORBED_VIBE_INTENSITY, "being orbed")
                                    being_orbed_vibe_active = True

                    if HACKED_EVENT == 1:
                        if hacked_effect_active:
                            if not player.hacked:
                                await alter_intensity(0, "stopped being hacked")
                                hacked_effect_active = False
                        else:
                            if player.hacked:
                                for key in timed_vibes:
                                    timed_vibes[key].clear()
                                await alter_intensity(-current_intensity, "hacked")
                                hacked_effect_active = True
                    elif HACKED_EVENT == 2:
                        if hacked_effect_active:
                            if not player.hacked:
                                for key in timed_vibes:
                                    timed_vibes[key].clear()
                                await alter_intensity(-current_intensity, "stopped being hacked")
                                hacked_effect_active = False
                        else:
                            if player.hacked:
                                for key in timed_vibes:
                                    timed_vibes[key].clear()
                                await alter_intensity(0.5, "hacked")
                                timed_vibes["hacked"].append({"Amount":0.25, "Frequency":0.2, "Last Change":0})
                                hacked_effect_active = True

                    # Mercy
                    if VIBE_FOR_RESURRECT:
                        #TODO: Should consider allowing multiple active vibes for resurrect. What if people use a long duration and a lower intensity?
                        if player.resurrecting and len(timed_vibes["resurrect"]) == 0:
                            await alter_intensity_for_duration("resurrect", RESURRECT_VIBE_INTENSITY, RESURRECT_VIBE_DURATION)
                    if VIBE_FOR_MERCY_BEAM:
                        if player.heal_beam:
                            if not heal_beam_vibe_active:
                                if damage_beam_vibe_active:
                                    await alter_intensity(HEAL_BEAM_VIBE_INTENSITY-DAMAGE_BEAM_VIBE_INTENSITY, "heal beaming")
                                    heal_beam_vibe_active = True
                                    damage_beam_vibe_active = False
                                else:
                                    await alter_intensity(HEAL_BEAM_VIBE_INTENSITY, "heal beaming")
                                    heal_beam_vibe_active = True
                        elif player.damage_beam:
                            if not damage_beam_vibe_active:
                                if heal_beam_vibe_active:
                                    await alter_intensity(DAMAGE_BEAM_VIBE_INTENSITY-HEAL_BEAM_VIBE_INTENSITY, "damage beaming")
                                    damage_beam_vibe_active = True
                                    heal_beam_vibe_active = False
                                else:
                                    await alter_intensity(DAMAGE_BEAM_VIBE_INTENSITY, "damage beaming")
                                    damage_beam_vibe_active = True
                        elif heal_beam_vibe_active:
                            await alter_intensity(-HEAL_BEAM_VIBE_INTENSITY, "stopped heal beaming")
                            heal_beam_vibe_active = False
                        elif damage_beam_vibe_active:
                            await alter_intensity(-DAMAGE_BEAM_VIBE_INTENSITY, "stopped damage beaming")
                            damage_beam_vibe_active = False
                    #Zenyatta
                    if VIBE_FOR_HARMONY_ORB:
                        #TODO: Turn some of these ifs inside out
                        if harmony_orb_vibe_active:
                            if not player.harmony_orb:
                                await alter_intensity(-HARMONY_ORB_VIBE_INTENSITY, "stopped harmony orb")
                                harmony_orb_vibe_active = False
                        else:
                            if player.harmony_orb:
                                await alter_intensity(HARMONY_ORB_VIBE_INTENSITY, "harmony orb")
                                harmony_orb_vibe_active = True
                    if VIBE_FOR_DISCORD_ORB:
                        if discord_orb_vibe_active:
                            if not player.discord_orb:
                                await alter_intensity(-DISCORD_ORB_VIBE_INTENSITY, "stopped discord orb")
                                discord_orb_vibe_active = False
                        else:
                            if player.discord_orb:
                                await alter_intensity(DISCORD_ORB_VIBE_INTENSITY, "discord orb")
                                discord_orb_vibe_active = True

                    if player.hero_auto_detect and player.detected_hero != player.hero:
                        print(f"Hero switch detected: {player.detected_hero}")
                        window["-HERO_SELECTOR-"].update(player.detected_hero)
                        player.switch_hero(player.detected_hero)

                event, values = window.read(timeout=1)
                if event == sg.WIN_CLOSED or event == "Quit":
                    window.close()
                    break
                elif event == "Stop":
                    await stop_all_devices()
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

            if event == sg.WIN_CLOSED or event == "Quit":
                print("Window closed.")
                break
            
            duration = time.time() - start_time
            print(f"Loops: {counter} | Loops per second: {round(counter/duration, 2)} | Avg. time: {round(1000 * (duration/counter), 2)}ms")
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
    HEROES = ["Other", "Mercy", "Zenyatta"]
    #HEROES = ["D.Va", "Doomfist", "Junker Queen", "Orisa", "Rammatra", "Reinhardt", "Roadhog", "Sigma", "Winston", "Wrecking Ball", "Zarya", "Ashe", "Bastion", "Cassidy", "Echo", "Genji", "Hanzo", "Junkrat", "Mei", "Pharah", "Reaper", "Sojourn", "Soldier: 76", "Sombra", "Symmetra", "Torbjorn", "Tracer", "Widowmaker", "Ana", "Baptiste", "Brigitte", "Kiriko", "Lucio", "Mercy", "Moira", "Zenyatta"]
    try:
        OUTPUT_WINDOW_ENABLED = config["OverStim"].getboolean("OUTPUT_WINDOW_ENABLED")
        CONTINUOUS_SCANNING = config["OverStim"].getboolean("CONTINUOUS_SCANNING")
        WEBSOCKET_ADDRESS = config["OverStim"]["WEBSOCKET_ADDRESS"]
        WEBSOCKET_PORT = config["OverStim"]["WEBSOCKET_PORT"]
    except Exception as err:
        config_fault[0] = True
        config_fault[1] = err
    
    # Initialize variables
    scanning = False
    layout = [
        [sg.Text("Playing hero:"), sg.Combo(HEROES, readonly=True, disabled=True, enable_events=True, key="-HERO_SELECTOR-"), sg.Checkbox("Auto-detect", default=True, enable_events=True, key="-HERO_AUTO_DETECT-")],
        [sg.Text("Devices connected:"), sg.Text("0", size=(4,1), key="-DEVICE_COUNT-")],
        [sg.Text("Current intensity:"), sg.Text("0%", size=(17,1), key="-CURRENT_INTENSITY-")],
        [sg.Text("Program status:"), sg.Text("READY", size=(15,1), key="-PROGRAM_STATUS-")],
        [sg.Button("Start"), sg.Button("Stop", disabled=True), sg.Button("Quit")],
        ]

    # Set up GUI
    if OUTPUT_WINDOW_ENABLED:
        layout.insert(0, [sg.Multiline(size=(60,15), disabled=True, reroute_stdout=True, autoscroll=True)])
    window = sg.Window("OverStim", layout, finalize=True)
    window["-HERO_SELECTOR-"].update("Other")
    print("Ensure you read READ_BEFORE_USING.txt before using this program.")
    print("This output window can be disabled in the config, but for pre-releases please leave it enabled so you have it when reporting bugs.\n-")

    # Connect to Intiface
    if not config_fault[0]:
        if USING_INTIFACE:
            connector = WebsocketConnector(f"{WEBSOCKET_ADDRESS}:{WEBSOCKET_PORT}", logger=client.logger)
            try:
                await client.connect(connector)
                print("Connected to Intiface")
            #except DisconnectedError:
            #    window["-PROGRAM_STATUS-"].update("RECONNECTING")
            #    await client.reconnect()
            except Exception as ex:
                print(f"Could not connect to server: {ex}")
                print("Make sure you've started the Intiface server and that the websocket address/port matches.")
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
        await stop_all_devices()
        window["-PROGRAM_STATUS-"].update("CRITICAL ERROR")
        print(f"CRITICAL ERROR OCCURRED\nError caught: {ex}")
        if BEEP_ENABLED:
            winsound.Beep(1000, 500)
        event, values = window.read()
        if event == sg.WIN_CLOSED or event == "Quit":
            window["Stop"].update(disabled=True)
            window["Quit"].update(disabled=True)
            window.close()

    # Close program
    await stop_all_devices()
    if not config_fault[0]:
        if USING_INTIFACE:
            if client.connected:
                if scanning:
                    await client.stop_scanning()
                await client.disconnect()
                print("Disconnected.")
    window.close()
    print("Quitting.")

#Start

#Only allow one instance of OverStim to be running
kill_other_overstim_instances()

# Import config
config = configparser.ConfigParser()
config.read(resource_path('config.ini'))
config_fault = [False, ""]

# Define constants
try:
    BEEP_ENABLED = config["OverStim"].getboolean("BEEP_ENABLED")
    USING_INTIFACE = config["OverStim"].getboolean("USING_INTIFACE")
    MAX_VIBE_INTENSITY = limit_value(config["OverStim"].getfloat("MAX_VIBE_INTENSITY"), 1, value_name="MAX_VIBE_INTENSITY")
    SCALE_ALL_INTENSITIES_BY_MAX_INTENSITY = config["OverStim"].getboolean("SCALE_ALL_INTENSITIES_BY_MAX_INTENSITY")
except Exception as err:
    config_fault[0] = True
    config_fault[1] = err

# Define global variables
window = None
current_intensity = 0
timed_vibes = {key:[] for key in [
    "elim",
    "assist",
    "save",
    "resurrect",
    "hacked",
    ]}

client = Client("OverStim", ProtocolSpec.v3)

sg.theme("DarkAmber")
logging.basicConfig(stream=sys.stdout, level=logging.INFO)
asyncio.run(main(), debug=False)
