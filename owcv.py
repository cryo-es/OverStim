import os

import numpy as np
import cv2 as cv
import dxcam_cpp


# This is necessary to access files when it's compiled into an executable
def resource_path(relative_path):
    return os.path.join(os.path.abspath("."), relative_path)


class ComputerVision:
    def __init__(self, coords, mask_names, print_detected_resolution=True):
        self.base_resolution = {"width": 1920, "height": 1080}
        self.screen = dxcam_cpp.create(max_buffer_len=1)

        # Detect the user's screen resolution
        detected_resolution = self.screen.grab().shape[:2]
        self.final_resolution = {"width": detected_resolution[1], "height": detected_resolution[0]}
        if print_detected_resolution:
            print("Detected resolution as {0}x{1}.".format(self.final_resolution["width"], self.final_resolution["height"]))

        self.screenshot_region = (0, 0, self.final_resolution["width"], self.final_resolution["height"])
        self.coords = coords
        self.templates = {key: cv.cvtColor(cv.imread(resource_path(f"data\\t_{key}.png")), cv.COLOR_RGB2GRAY) for key in self.coords}
        self.mask_names = mask_names
        self.masks = {key: cv.cvtColor(cv.imread(resource_path(f"data\\m_{key}.png")), cv.COLOR_RGB2GRAY) for key in self.mask_names}
        self.frame = []

    def start_capturing(self, target_fps=60):
        self.screen.start(target_fps=target_fps, video_mode=True)

    def stop_capturing(self):
        self.screen.stop()

    def capture_frame(self):
        screenshot = self.screen.get_latest_frame()
        # crop screenshots of incorrect aspect ratios
        target_ratio = self.base_resolution["width"] / self.base_resolution["height"]
        # crop width of screen grab, e.g. for 21:9 ultrawide aspect ratio
        max_width = int(screenshot.shape[0] * target_ratio)
        if screenshot.shape[1] > max_width:
            crop_x = (screenshot.shape[1] - max_width) // 2
            screenshot = screenshot[:, crop_x:-crop_x]
        # crop height of screen grab, e.g. for 4:3 standard aspect ratio
        max_height = int(screenshot.shape[1] / target_ratio)
        if screenshot.shape[0] > max_height:
            crop_y = (screenshot.shape[0] - max_height) // 2
            screenshot = screenshot[crop_y:-crop_y]
        # resize screenshot of incorrect resolution
        if self.final_resolution != self.base_resolution:
            screenshot = cv.resize(screenshot, (self.base_resolution["width"], self.base_resolution["height"]))
        self.frame = cv.cvtColor(screenshot, cv.COLOR_BGR2GRAY)

    def crop(self, image, template_name, coords_override=None):
        if coords_override is None:
            return image[self.coords[template_name][0]:self.coords[template_name][1], self.coords[template_name][2]:self.coords[template_name][3]]
        else:
            return image[coords_override[0]:coords_override[1], coords_override[2]:coords_override[3]]

    def match(self, template_name, coords_override=None):
        cropped_frame = self.crop(self.frame, template_name, coords_override)
        if template_name in self.mask_names:
            return cv.matchTemplate(cropped_frame, self.templates[template_name], cv.TM_CCOEFF_NORMED, mask=self.masks[template_name])
        else:
            return cv.matchTemplate(cropped_frame, self.templates[template_name], cv.TM_CCOEFF_NORMED)

    def detect_multiple(self, template_name, threshold=0.9):
        result = self.match(template_name)
        cv.threshold(result, threshold, 255, cv.THRESH_BINARY, result)
        return len(cv.findContours(result.astype(np.uint8), cv.RETR_LIST, cv.CHAIN_APPROX_SIMPLE)[0])

    def detect_single(self, template_name, threshold=0.9, coords_override=None):
        result = self.match(template_name, coords_override)
        return np.nanmax(result) > threshold
