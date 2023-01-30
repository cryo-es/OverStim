import configparser
import winsound
import logging
import asyncio
import time
import sys

from buttplug import Client, WebsocketConnector, ProtocolSpec
import PySimpleGUI as sg

from owstate import OverwatchStateTracker
from owcv import resource_path


def update_device_count(last_device_count):
    current_device_count = len(client.devices)
    if current_device_count != last_device_count:
        window["-DEVICE_COUNT-"].update(current_device_count)
        return current_device_count

async def stop_all_devices():
    for key in list(intensity_tracker):
        del intensity_tracker[key]
    for device_id in client.devices:
        try:
            device = client.devices[device_id]
            await device.stop()
        except Exception as err:
            print("A device experienced an error while being stopped.")
            print(err)
    print("Stopped all devices.")

def limit_intensity(intensity):
    if intensity > 1:
        intensity = 1
    elif intensity < 0:
        print(f"Intensity was {intensity} but it cannot be lower than 0. Setting it to 0.")
        intensity = 0
    return intensity

async def alter_intensity(amount):
    global current_intensity
    #global last_command_time
    current_intensity = round(MIN_INTENSITY_STEP * round((current_intensity + amount) / MIN_INTENSITY_STEP, 0), ROUNDING_AMOUNT)
    print(f"Current intensity: {current_intensity}")
    real_intensity = limit_intensity(current_intensity)
    print(f"Real intensity:    {real_intensity}")
    for device_id in client.devices:
        try:
            device = client.devices[device_id]
            for actuator in device.actuators:
                await device.actuators[0].command(real_intensity)
            print(f"Updated intensity for {device.name}")
        except Exception as err:
            await device.stop()
            print("An error occured when altering the vibration of a device.")
            print(err)
    #last_command_time = time.time()
    window["-CURRENT_INTENSITY-"].update(str(int(current_intensity*100)) + ("%" if current_intensity == real_intensity else "% (max 100%)"))
    if BEEP_ENABLED:
        winsound.Beep(int(1000 + (real_intensity*5000)), 20)

async def alter_intensity_for_duration(amount, duration, key="None"):
    current_time = time.time()
    if key == "None":
        intensity_tracker[current_time] = [current_time + duration, amount]
    else:
        intensity_tracker[key] = [current_time + duration, amount]
    await alter_intensity(amount)

async def update_intensity():
    current_time = time.time()
    for key in list(intensity_tracker):
        pair = intensity_tracker[key]
        if pair[0] <= current_time:
            del intensity_tracker[key]
            await alter_intensity(-pair[1])

async def run_overstim():
    # Define constants
    try:
        SCREEN_WIDTH = config["OverStim"].getint("SCREEN_WIDTH")
        SCREEN_HEIGHT = config["OverStim"].getint("SCREEN_HEIGHT")
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
        BEING_BEAMED_VIBE_INTENSITY =config["OverStim"].getfloat("BEING_BEAMED_VIBE_INTENSITY")
        VIBE_FOR_RESURRECT = config["OverStim"].getboolean("VIBE_FOR_RESURRECT")
        RESURRECT_VIBE_INTENSITY = config["OverStim"].getfloat("RESURRECT_VIBE_INTENSITY")
        RESURRECT_VIBE_DURATION = config["OverStim"].getfloat("RESURRECT_VIBE_DURATION")
        VIBE_FOR_MERCY_BEAM = config["OverStim"].getboolean("VIBE_FOR_MERCY_BEAM")
        HEAL_BEAM_VIBE_INTENSITY = config["OverStim"].getfloat("HEAL_BEAM_VIBE_INTENSITY")
        DAMAGE_BEAM_VIBE_INTENSITY = config["OverStim"].getfloat("DAMAGE_BEAM_VIBE_INTENSITY")
        DEAD_REFRESH_DELAY = config["OverStim"].getfloat("DEAD_REFRESH_DELAY")
        MAX_REFRESH_RATE = config["OverStim"].getint("MAX_REFRESH_RATE")
        BEAM_DISCONNECT_BUFFER = config["OverStim"].getint("BEAM_DISCONNECT_BUFFER")
    except Exception as err:
        config_fault[0] = True
        config_fault[1] = err

    # Initialize variables
    if not config_fault[0]:
        player = OverwatchStateTracker({"width":SCREEN_WIDTH, "height":SCREEN_HEIGHT})
        player.neg_required_confs = BEAM_DISCONNECT_BUFFER
    heal_beam_vibe_active = False
    damage_beam_vibe_active = False
    being_beamed_vibe_active = False
    current_elim_count = 0
    current_assist_count = 0
    current_save_count = 0
    last_refresh = 0
    device_count = 0

    while True:
        # Gives main time to respond to pings from Intiface
        await asyncio.sleep(0)

        device_count = update_device_count(device_count)

        if USING_INTIFACE and not client.connected:
            window["-PROGRAM_STATUS-"].update("INTIFACE ERROR")
            window["Start"].update(disabled=True)
            print("Lost connection to Intiface.")

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

        event, values = window.read(timeout=100)
        if event == sg.WIN_CLOSED or event == "Quit":
            window.close()
            print("Window closed.")
            break
        
        elif event == "-HERO_SELECTOR-":
            hero_selected = values["-HERO_SELECTOR-"]
            player.hero = hero_selected
            print(f"Hero switched to {hero_selected}.")

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
                    if current_time >= last_refresh + DEAD_REFRESH_DELAY:
                        last_refresh = current_time
                        player.refresh()
                else:
                    last_refresh = current_time
                    player.refresh()

                    if VIBE_FOR_ELIM:
                        if player.elim_notifs > current_elim_count:
                            #New elim appeared
                            difference = player.elim_notifs - current_elim_count
                            current_elim_count = player.elim_notifs
                            await alter_intensity_for_duration(difference*ELIM_VIBE_INTENSITY, ELIM_VIBE_DURATION)
                        elif player.elim_notifs < current_elim_count:
                            #Old elim disappeared
                            current_elim_count = player.elim_notifs

                    if VIBE_FOR_ASSIST:
                        if player.assist_notifs > current_assist_count:
                            #New assist appeared
                            difference = player.assist_notifs - current_assist_count
                            current_assist_count = player.assist_notifs
                            await alter_intensity_for_duration(difference*ASSIST_VIBE_INTENSITY, ASSIST_VIBE_DURATION)
                        elif player.assist_notifs < current_assist_count:
                            #Old assist disappeared
                            current_assist_count = player.assist_notifs
                    
                    if VIBE_FOR_SAVE:
                        if player.saved_notifs > current_save_count:
                            #New save appeared
                            difference = player.saved_notifs - current_save_count
                            current_save_count = player.saved_notifs
                            if not player.resurrecting:
                                await alter_intensity_for_duration(difference*SAVE_VIBE_INTENSITY, SAVE_VIBE_DURATION)
                        elif player.saved_notifs < current_save_count:
                            #Old save disappeared
                            current_save_count = player.saved_notifs

                    if VIBE_FOR_BEING_BEAMED:
                        if being_beamed_vibe_active:
                            if not player.being_beamed:
                                await alter_intensity(-BEING_BEAMED_VIBE_INTENSITY)
                                being_beamed_vibe_active = False
                        else:
                            if player.being_beamed:
                                await alter_intensity(BEING_BEAMED_VIBE_INTENSITY)
                                being_beamed_vibe_active = True

                    if player.hero == "Mercy":
                        if VIBE_FOR_RESURRECT:
                            if player.resurrecting and "resurrect" not in intensity_tracker:
                                await alter_intensity_for_duration(RESURRECT_VIBE_INTENSITY, RESURRECT_VIBE_DURATION, key="resurrect")
                        
                        if VIBE_FOR_MERCY_BEAM:
                            if player.heal_beam:
                                if not heal_beam_vibe_active:
                                    if damage_beam_vibe_active:
                                        await alter_intensity(HEAL_BEAM_VIBE_INTENSITY-DAMAGE_BEAM_VIBE_INTENSITY)
                                        heal_beam_vibe_active = True
                                        damage_beam_vibe_active = False
                                    else:
                                        await alter_intensity(HEAL_BEAM_VIBE_INTENSITY)
                                        heal_beam_vibe_active = True
                            elif player.damage_beam:
                                if not damage_beam_vibe_active:
                                    if heal_beam_vibe_active:
                                        await alter_intensity(DAMAGE_BEAM_VIBE_INTENSITY-HEAL_BEAM_VIBE_INTENSITY)
                                        damage_beam_vibe_active = True
                                        heal_beam_vibe_active = False
                                    else:
                                        await alter_intensity(DAMAGE_BEAM_VIBE_INTENSITY)
                                        damage_beam_vibe_active = True
                            elif heal_beam_vibe_active:
                                await alter_intensity(-HEAL_BEAM_VIBE_INTENSITY)
                                heal_beam_vibe_active = False
                            elif damage_beam_vibe_active:
                                await alter_intensity(-DAMAGE_BEAM_VIBE_INTENSITY)
                                damage_beam_vibe_active = False

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
                    player.hero = hero_selected
                    print(f"Hero switched to {hero_selected}.")

            if event == sg.WIN_CLOSED or event == "Quit":
                print("Window closed.")
                break
            
            duration = time.time() - start_time
            print(f"Loops: {counter} | Loops per second: {round(counter/(duration), 2)} | Avg. time: {round(1000 * (duration/counter), 2)}ms")
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
    HEROES = ["Other", "Mercy"]
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
        [sg.Text("Playing hero:"), sg.Combo(HEROES, readonly=True, enable_events=True, key="-HERO_SELECTOR-")],
        [sg.Text("Devices connected:"), sg.Text("0", size=(4,1), key="-DEVICE_COUNT-")],
        [sg.Text("Current intensity:"), sg.Text("0%", size=(17,1), key="-CURRENT_INTENSITY-")],
        [sg.Text("Program status:"), sg.Text("READY", size=(15,1), key="-PROGRAM_STATUS-")],
        [sg.Button("Start"), sg.Button("Stop", disabled=True), sg.Button("Quit")],]

    # Set up GUI
    if OUTPUT_WINDOW_ENABLED:
        layout.insert(0, [sg.Multiline(size=(60,15), disabled=True, reroute_stdout=True, autoscroll=True)])
    window = sg.Window("OverStim", layout, finalize=True)
    window["-HERO_SELECTOR-"].update("Other")
    print("This output window can be disabled in the config, but for pre-releases please leave it enabled so you have it when reporting bugs.")

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
        window["-PROGRAM_STATUS-"].update("UNKNOWN ERROR")
        print(f"Error caught: {ex}")
        if BEEP_ENABLED:
            winsound.Beep(1000, 500)

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


# Import config
config = configparser.ConfigParser()
config.read(resource_path('config.ini'))
config_fault = [False, ""]

# Define constants
try:
    BEEP_ENABLED = config["OverStim"].getboolean("BEEP_ENABLED")
    USING_INTIFACE = config["OverStim"].getboolean("USING_INTIFACE")
    # Maybe check step count of devices/actuators?
    MIN_INTENSITY_STEP = config["OverStim"].getfloat("MIN_INTENSITY_STEP")
    ROUNDING_AMOUNT = len(str(MIN_INTENSITY_STEP).split(".")[1])
except Exception as err:
    config_fault[0] = True
    config_fault[1] = err

# Define global variables
window = None
current_intensity = 0
intensity_tracker = {}
#last_command_time = 0
client = Client("OverStim", ProtocolSpec.v3)

sg.theme("DarkAmber")
logging.basicConfig(stream=sys.stdout, level=logging.INFO)
asyncio.run(main(), debug=False)
