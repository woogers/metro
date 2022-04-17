"""
    TODO: Download station and line information every six months and save to file.
    TODO: Display "Station is closed" outside of operating hours
    TODO: Show station closed message for 30 minutes after closing
    TODO: Have custom display for end of line stations:
          X Line to Y
          Z-Car Train
          Departing in W min
"""

import json
import logging
import sys
import time
from logging import handlers

from requests_futures.sessions import FuturesSession
from rgbmatrix import RGBMatrix, RGBMatrixOptions, graphics

# logging config
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
lh = handlers.RotatingFileHandler(
    filename="metro/logs/driver.log", maxBytes=500000, backupCount=20
)
lh.setLevel(logging.DEBUG)
formatter = logging.Formatter("%(asctime)s - %(levelname)s: %(message)s")
lh.setFormatter(formatter)
logger.addHandler(lh)

station_id = "D05"  # Capitol South is D05.
# For multilevel stations, separate the codes with a comma.
# For example, Metro Center would be "A01,C01"
api_key = ""
api_root = "https://api.wmata.com/"  # Root URL for WMATA REST API
api_predictions = (
    "StationPrediction.svc/json/GetPrediction/"  # Rail Arrival Predictions endpoint
)
api_incidents = "Incidents.svc/json/Incidents"  # Service Incidents endpoint
current_id = 0

incidents = []
queue = []
predictions = []
headers = {"api_key": api_key}


class Train:
    train_id = 0  # Unique train identifier
    cars = 0  # Number of cars in train
    direction = 1  # Direction of travel/track number
    destination_code = "X01"  # RTU for train's destination
    destination_name = "Jackson Graham Building"  # Human-readable destination name
    destination_display = "Jac"  # What to actually show for the destination on the sign
    line = "Red"  # Line name for train
    route = "X"  # Route name for train
    at_station = False  # Is train at a station?
    at_station_id = "X01"  # If true, RTU for current station
    minutes = 0  # Predicted time to arrival
    status = "0"  # Boarding (BRD), Arriving (ARR), or number of minutes if > 0

    def __init__(
        self, cars, direction, destination_code, destination_name, line, minutes
    ):
        self.train_id = current_id
        self.cars = cars
        self.direction = direction
        self.destination_code = destination_code
        self.destination_name = destination_name
        """self.line = {
            "RD": "Red",
            "BL": "Blue",
            "OR": "Orange",
            "YL": "Yellow",
            "GR": "Green",
            "SV": "Silver",
            "--": "Unknown",
            "No": "No",
        }[line]"""
        self.line = line
        if minutes != "BRD" or minutes != "ARR":
            self.minutes = minutes
            self.status = str(minutes)
        else:
            self.minutes = 0
            if minutes == "BRD":
                self.status = "BRD"
            elif minutes == "ARR":
                self.status = "ARR"
            else:
                self.status = minutes


class Incident:
    incident_id = ""  # Unique incident identifier
    description = ""  # Free text description of the incident
    delay_type = 0  # 0 for delay, 1 for alert
    lines = []  # Lines affected by incident

    def __init__(self, incident_id, description, delay_type, lines):
        self.incident_id = incident_id
        self.description = description
        if delay_type == "Delay":
            self.delay_type = 0
        if delay_type == "Alert":
            self.delay_type = 1
        self.lines = list(filter(None, lines.split(";")))


class TransitDriver(object):
    line_colors = {
        "RD": [255, 0, 0],
        "BL": [0, 0, 255],
        "OR": [255, 100, 0],
        "YL": [204, 132, 0],
        "GR": [0, 255, 0],
        "SV": [255, 255, 255],
    }

    update_count = 0
    sleep_count = 0

    incidents = []
    queue = []

    font = graphics.Font()
    font.LoadFont("metro/5x7.bdf")

    MAIN_TEXT_COLOR = graphics.Color(204, 132, 0)
    NOW_TEXT_COLOR = graphics.Color(255, 0, 0)
    GOOD_TEXT_COLOR = graphics.Color(192, 255, 0)

    def draw_line_color_block(self, oc, line_name, led_index):
        if line_name != "No":
            for x in range(1, 4):
                for y in range((led_index * 7) - 6, led_index * 7):
                    oc.SetPixel(
                        x,
                        y,
                        self.line_colors[line_name][0],
                        self.line_colors[line_name][1],
                        self.line_colors[line_name][2],
                    )

    def draw_dest_text(self, oc, dest_name, led_index):
        if "Mt Vernon Sq" in dest_name:
            dest_name = "Mt Vernon Square"
        if "Nat''l Air" in dest_name:
            dest_name = "National Airport"
        graphics.DrawText(
            oc, self.font, 5, (led_index) * 7, self.MAIN_TEXT_COLOR, dest_name
        )

    def draw_status_text(self, oc, status, led_index):
        status_pos = 109
        try:
            int(status)
            if len(status) == 2:
                status_pos = 111
            if len(status) == 1:
                status_pos = 114
            graphics.DrawText(
                oc, self.font, status_pos, (led_index) * 7, self.MAIN_TEXT_COLOR, status
            )
        except ValueError:
            if self.sleep_count < 5:
                graphics.DrawText(
                    oc,
                    self.font,
                    status_pos,
                    (led_index) * 7,
                    self.NOW_TEXT_COLOR,
                    status,
                )

    def draw_delay_text(self, oc, delay, pos, finished):
        delay_len = graphics.DrawText(
            oc, self.font, pos, 31, self.MAIN_TEXT_COLOR, delay
        )
        if pos + delay_len < 0:
            pos = oc.width
            finished = True

        return finished

    def usleep(self, value):
        time.sleep(value / 1000000.0)

    def get_predictions(self, session):
        url = api_root + api_predictions
        future = session.get(url + station_id, headers=headers)
        return future

    def render_predictions(self, future):
        self.queue = []
        response = future.result()
        predictions = json.loads(response.text)["Trains"]
        for train in predictions:
            new_train = Train(
                train["Car"],
                train["Group"],
                train["DestinationCode"],
                train["DestinationName"],
                train["Line"],
                train["Min"],
            )
            self.queue.append(new_train)

    def get_alerts(self, session):
        url = api_root + api_incidents
        future = session.get(url, headers=headers)
        return future

    def render_alerts(self, future):
        self.incidents = []
        response = future.result()
        incident_list = json.loads(response.text)["Incidents"]
        for incident in incident_list:
            new_incident = Incident(
                incident["IncidentID"],
                incident["Description"],
                incident["IncidentType"],
                incident["LinesAffected"],
            )
            self.incidents.append(new_incident)

    def no_trains(self, oc):
        graphics.DrawText(
            oc, self.font, 1, 7, self.MAIN_TEXT_COLOR, "No trains due in next"
        )
        graphics.DrawText(oc, self.font, 1, 15, self.MAIN_TEXT_COLOR, "40 minutes.")

    def run(self):
        print("Running")
        offscreen_canvas = self.matrix.CreateFrameCanvas()
        session = FuturesSession()

        futurep = self.get_predictions(session)
        futurea = self.get_alerts(session)

        incident_count = 0
        finished = False
        delay_pos = 1

        while True:
            try:
                self.render_predictions(futurep)
                self.render_alerts(futurea)
                total_incidents = len(self.incidents)
                offscreen_canvas.Clear()
                if len(self.queue) == 0:
                    self.no_trains(offscreen_canvas)
                if len(self.queue) > 0:
                    self.draw_line_color_block(offscreen_canvas, self.queue[0].line, 1)
                    self.draw_dest_text(
                        offscreen_canvas, self.queue[0].destination_name, 1
                    )
                    self.draw_status_text(offscreen_canvas, self.queue[0].minutes, 1)
                if len(self.queue) > 1:
                    self.draw_line_color_block(offscreen_canvas, self.queue[1].line, 2)
                    self.draw_dest_text(
                        offscreen_canvas, self.queue[1].destination_name, 2
                    )
                    self.draw_status_text(offscreen_canvas, self.queue[1].minutes, 2)
                if len(self.queue) > 2:
                    self.draw_line_color_block(offscreen_canvas, self.queue[2].line, 3)
                    self.draw_dest_text(
                        offscreen_canvas, self.queue[2].destination_name, 3
                    )
                    self.draw_status_text(offscreen_canvas, self.queue[2].minutes, 3)
                if total_incidents > 0:
                    delay_text = (
                        ",".join(self.incidents[incident_count].lines)
                        + ": "
                        + self.incidents[incident_count].description
                    )
                    finished = self.draw_delay_text(
                        offscreen_canvas, delay_text, delay_pos, finished
                    )
                    delay_pos -= 1
                else:
                    graphics.DrawText(
                        offscreen_canvas,
                        self.font,
                        1,
                        31,
                        self.GOOD_TEXT_COLOR,
                        "Good service.",
                    )

                time.sleep(0.1)

                # sleep_count is so BRD and ARR flash every half second
                if self.sleep_count < 10:
                    self.sleep_count += 1
                else:
                    self.sleep_count = 0

                if self.update_count < 100:
                    self.update_count += 1
                else:
                    self.update_count = 0
                    futurep = self.get_predictions(session)

                if finished:
                    incident_count += 1
                    delay_pos = 1
                    finished = False
                    if incident_count == total_incidents:
                        incident_count = 0
                        futurea = self.get_alerts(session)

                offscreen_canvas = self.matrix.SwapOnVSync(offscreen_canvas)
            except Exception:
                logger.error("Something went wrong!", exc_info=True)

    def process(self):
        options = RGBMatrixOptions()

        options.hardware_mapping = "adafruit-hat"
        options.rows = 32
        options.cols = 64
        options.chain_length = 2
        options.parallel = 1
        options.row_address_type = 0
        options.multiplexing = 0
        options.pwm_bits = 11
        options.brightness = 100
        options.pwm_lsb_nanoseconds = 130
        options.led_rgb_sequence = "RGB"
        options.pixel_mapper_config = ""
        options.gpio_slowdown = 4

        self.matrix = RGBMatrix(options=options)

        try:
            print("Ctrl+C to stop")
            self.run()
        except KeyboardInterrupt:
            print("Stopping.")
            sys.exit(0)

        return True


if __name__ == "__main__":
    transit = TransitDriver()
    if not transit.process():
        print("Error.")
