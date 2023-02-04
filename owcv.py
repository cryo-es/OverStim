import os

import numpy as np
import cv2 as cv
import dxcam


def resource_path(relative_path):
    return os.path.join(os.path.abspath("."), relative_path)

class ComputerVision:
    def __init__(self, coords, mask_names):
        self.base_resolution = {"width":1920, "height":1080}
        self.screen = dxcam.create(max_buffer_len=1)
        res = self.screen.grab().shape[:2]
        self.final_resolution = {"width":res[1], "height":res[0]}
        print("Detected resolution as {0}x{1}.".format(self.final_resolution["width"], self.final_resolution["height"]))
        self.screenshot_region = (0, 0, self.final_resolution["width"], self.final_resolution["height"])
        self.coords = coords
        self.templates = {key:cv.cvtColor(cv.imread(resource_path(f"data\\t_{key}.png")), cv.COLOR_RGB2GRAY) for key in self.coords}
        self.mask_names = mask_names
        self.masks = {key:cv.cvtColor(cv.imread(resource_path(f"data\\m_{key}.png")), cv.COLOR_RGB2GRAY) for key in self.mask_names}
        self.frame = []

    def start_capturing(self, target_fps=60):
        self.screen.start(target_fps=target_fps, video_mode=True)

    def stop_capturing(self):
        self.screen.stop()

    def capture_frame(self):
        if self.final_resolution != self.base_resolution:
            self.frame = cv.cvtColor(cv.resize(self.screen.get_latest_frame(), (self.base_resolution["width"], self.base_resolution["height"])), cv.COLOR_BGR2GRAY)
        else:
            self.frame = cv.cvtColor(self.screen.get_latest_frame(), cv.COLOR_BGR2GRAY)

    def crop(self, image, template_name):
        return image[self.coords[template_name][0]:self.coords[template_name][1], self.coords[template_name][2]:self.coords[template_name][3]]

    def match(self, template_name):
        if template_name in self.mask_names:
            return cv.matchTemplate(self.crop(self.frame, template_name), self.templates[template_name], cv.TM_CCOEFF_NORMED, mask=self.masks[template_name])
        else:
            return cv.matchTemplate(self.crop(self.frame, template_name), self.templates[template_name], cv.TM_CCOEFF_NORMED)

    def detect_multiple(self, template_name, threshold=0.9):
        result = self.match(template_name)
        cv.threshold(result, threshold, 255, cv.THRESH_BINARY, result)
        return len(cv.findContours(result.astype(np.uint8), cv.RETR_LIST, cv.CHAIN_APPROX_SIMPLE)[0])

    def detect_single(self, template_name, threshold=0.9):
        result = self.match(template_name)
        #TODO: Use np.nanmax(result) here instead?
        return result.max() > threshold
